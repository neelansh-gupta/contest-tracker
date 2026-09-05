"""
Sync upcoming Codeforces / CodeChef / AtCoder contests from clist.by into a
Google Calendar.

Auth design (this is the whole point of this rewrite):
- clist.by: plain `username` + `api_key` query params. No OAuth, no client
  secret, no token that expires. Get the key once from https://clist.by/login/
  (shown on your profile once you're logged in) and it's good until you
  manually regenerate it.
- Google Calendar: a service account JSON key, not a user OAuth flow. Service
  account keys do not expire and never need a "re-consent" step. You just
  share your calendar with the service account's email address once.

Run every N hours via GitHub Actions (see .github/workflows/sync.yml).
"""

import os
from datetime import datetime, timezone

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CLIST_USERNAME = os.environ["CLIST_USERNAME"]
CLIST_API_KEY = os.environ["CLIST_API_KEY"]
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

CLIST_API_URL = "https://clist.by/api/v4/contest/"
RESOURCES = ["codeforces.com", "codechef.com", "atcoder.jp"]

PLATFORM_LABELS = {
    "codeforces.com": "Codeforces",
    "codechef.com": "CodeChef",
    "atcoder.jp": "AtCoder",
}
PLATFORM_COLORS = {
    "codeforces.com": "11",  # tomato
    "codechef.com": "5",     # banana
    "atcoder.jp": "9",       # blueberry
}

SYNC_TAG = "contest_tracker"  # used to find/own events without touching anything else on the calendar


def fetch_contests():
    """Pull upcoming contests for each platform using plain API-key auth."""
    all_contests = []
    for resource in RESOURCES:
        params = {
            "username": CLIST_USERNAME,
            "api_key": CLIST_API_KEY,
            "resource": resource,
            "upcoming": "true",
            "order_by": "start",
            "limit": 200,
            "format": "json",
            "timezone": "UTC",
        }
        resp = requests.get(CLIST_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        all_contests.extend(resp.json().get("objects", []))
    return all_contests


def get_calendar_service():
    """Auth via service account — no token to refresh, ever."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def to_rfc3339_utc(iso_str):
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def build_event_body(contest):
    platform = contest["resource"]
    label = PLATFORM_LABELS.get(platform, platform)
    start = to_rfc3339_utc(contest["start"])
    end = to_rfc3339_utc(contest["end"])
    return {
        "summary": f"[{label}] {contest['event']}",
        "description": (
            f"Platform: {label}\n"
            f"Duration: {contest['duration'] // 60} min\n"
            f"Link: {contest['href']}"
        ),
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "colorId": PLATFORM_COLORS.get(platform, "8"),
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 24 * 60},  # 1 day before
                {"method": "popup", "minutes": 30},        # 30 min before
            ],
        },
        "extendedProperties": {
            "private": {
                "contest_id": str(contest["id"]),
                "source": SYNC_TAG,
            }
        },
    }


def fetch_existing_events(service):
    """Only events this script created (tagged), so it never touches anything else on the calendar."""
    events = {}
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=GOOGLE_CALENDAR_ID,
                privateExtendedProperty=f"source={SYNC_TAG}",
                pageToken=page_token,
                maxResults=250,
                showDeleted=False,
            )
            .execute()
        )
        for item in resp.get("items", []):
            cid = item.get("extendedProperties", {}).get("private", {}).get("contest_id")
            if cid:
                events[cid] = item
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def needs_update(existing_event, new_body):
    return (
        existing_event.get("summary") != new_body["summary"]
        or existing_event.get("description", "") != new_body["description"]
        or existing_event.get("start", {}).get("dateTime") != new_body["start"]["dateTime"]
        or existing_event.get("end", {}).get("dateTime") != new_body["end"]["dateTime"]
        or existing_event.get("colorId") != new_body["colorId"]
        or existing_event.get("reminders", {}).get("overrides") != new_body["reminders"]["overrides"]
    )


def sync():
    print("Starting contest sync...")
    contests = fetch_contests()
    print(f"Fetched {len(contests)} upcoming contests from clist.by")

    service = get_calendar_service()
    existing = fetch_existing_events(service)
    print(f"Found {len(existing)} previously synced events on the calendar")

    seen_ids = set()
    created = updated = unchanged = 0

    for contest in contests:
        cid = str(contest["id"])
        seen_ids.add(cid)
        body = build_event_body(contest)

        if cid in existing:
            if needs_update(existing[cid], body):
                service.events().patch(
                    calendarId=GOOGLE_CALENDAR_ID,
                    eventId=existing[cid]["id"],
                    body=body,
                ).execute()
                updated += 1
            else:
                unchanged += 1
        else:
            service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
            created += 1

    deleted = 0
    for cid, event in existing.items():
        if cid not in seen_ids:
            try:
                service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event["id"]).execute()
                deleted += 1
            except HttpError as e:
                print(f"Could not delete event {event['id']}: {e}")

    print(f"Done. Created: {created}, Updated: {updated}, Unchanged: {unchanged}, Deleted: {deleted}")


if __name__ == "__main__":
    sync()
