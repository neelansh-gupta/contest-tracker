# Contest Tracker

Automatically syncs upcoming **Codeforces**, **CodeChef**, and **AtCoder**
contests into a Google Calendar — created, updated, and removed automatically
as contests change, with zero recurring manual maintenance.

## How it works

Every 6 hours (via GitHub Actions):

1. Fetch upcoming contests from the [clist.by](https://clist.by) API for
   Codeforces, CodeChef, and AtCoder.
2. Fetch this script's own previously-synced events from Google Calendar
   (tagged internally so it never touches anything else on your calendar).
3. Diff the two lists:
   - New contest → **create** event
   - Existing contest, details changed → **update** event
   - Event on calendar with no matching contest anymore → **delete** event
4. Done. Calendar reflects reality.

Each event includes:
- Title tagged by platform, e.g. `[Codeforces] Round 1023 (Div. 2)`
- Description with duration and a direct link to the contest
- Color-coded by platform (Codeforces / CodeChef / AtCoder)
- Two reminders: 1 day before and 30 minutes before

## Why this version doesn't break every week

Earlier versions of this used:
- A **user OAuth flow** for Google Calendar — refresh tokens expire on a
  rolling basis for unverified apps, so the token had to be manually
  regenerated constantly.
- An **OAuth client-credentials flow** for clist.by — which the contest
  endpoint doesn't reliably support, causing repeated 401 errors whenever
  the client secret was touched.

This version fixes both at the root:

| | Old approach | Now |
|---|---|---|
| Google Calendar | User OAuth (`token.json`), expires ~weekly | **Service account** — never expires, no re-consent |
| clist.by | OAuth client id/secret | Plain **`username` + `api_key`** — the auth method the API actually documents |

Once set up, there's nothing to renew on any schedule. The only way it
breaks again is by manually revoking the clist.by key or deleting the
service account.

## Project structure

```
contest-tracker/
├── .github/
│   └── workflows/
│       └── sync.yml        # runs sync.py every 6 hours + manual trigger
├── sync.py                 # main sync script
├── requirements.txt
└── SETUP.md                # one-time setup walkthrough
```

## Setup

See [`SETUP.md`](./SETUP.md) for the full one-time walkthrough (clist.by
key, Google service account, calendar sharing, GitHub secrets).

Required GitHub Actions secrets:

| Secret | Value |
|---|---|
| `CLIST_USERNAME` | your clist.by username |
| `CLIST_API_KEY` | your clist.by API key |
| `GOOGLE_SERVICE_ACCOUNT` | full contents of the service account JSON key |
| `GOOGLE_CALENDAR_ID` | target calendar's ID |

## Running locally

```bash
export CLIST_USERNAME=your_username
export CLIST_API_KEY=your_api_key
export GOOGLE_CALENDAR_ID=your_calendar_id
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service_account.json
pip install -r requirements.txt
python3 sync.py
```

## Tech

- Python 3.11
- Google Calendar API v3 (`google-api-python-client`)
- [clist.by API v4](https://clist.by/api/v4/doc/)
- GitHub Actions for scheduling

## Security note

Never commit the service account JSON key or `.env` files with real
credentials — they're git-ignored here (see `.gitignore`) and should only
ever live in GitHub Actions secrets.
