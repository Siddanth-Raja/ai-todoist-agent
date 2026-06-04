# Personal Chief of Staff Backend

Read-only planning MVP for Personal Chief of Staff.

The MVP exposes:

- `GET /health`
- `POST /chat`

`POST /chat` reads active Todoist tasks, reads today's Google Calendar events, finds the current or next free block, ranks tasks, and returns 1 to 3 recommendations. It does not create, update, move, delete, or complete tasks or calendar events.

## 1. Create a Virtual Environment

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

## 2. Install Requirements

```bash
pip install -r requirements.txt
```

## 3. Add `.env`

Create `backend/.env`:

```bash
TODOIST_API_TOKEN=your_todoist_api_token

GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
GOOGLE_REFRESH_TOKEN=your_google_refresh_token
GOOGLE_CALENDAR_ID=primary

OPENAI_API_KEY=
```

`GOOGLE_CALENDAR_ID` defaults to `primary` if omitted.

## 4. Get a Todoist API Token

1. Open Todoist.
2. Go to Settings.
3. Open Integrations.
4. Open Developer.
5. Copy the API token.
6. Put it in `TODOIST_API_TOKEN`.

## 5. Get Google OAuth Credentials and Refresh Token

The backend uses `google-api-python-client` with a refresh token and the read-only Calendar scope:

```text
https://www.googleapis.com/auth/calendar.readonly
```

One practical setup path:

1. Open Google Cloud Console.
2. Create or select a project.
3. Enable the Google Calendar API.
4. Configure the OAuth consent screen.
5. Create an OAuth client ID. A Desktop app client is fine for local development.
6. Copy the client ID and client secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
7. Use OAuth 2.0 Playground or a local OAuth helper script to authorize the Calendar read-only scope.
8. Exchange the authorization code for tokens.
9. Copy the refresh token into `GOOGLE_REFRESH_TOKEN`.

If your OAuth app is in testing mode, make sure your Google account is listed as a test user.

## 6. Run the Server

From `backend/` with the virtual environment active:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 7. Test Health

```bash
curl http://127.0.0.1:8000/health
```

Expected shape:

```json
{
  "status": "ok",
  "mode": "planning_read_only"
}
```

## 8. Test Chat

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What should I work on right now?"}'
```

Expected response fields:

```json
{
  "answer": "Natural language recommendation...",
  "free_block": {},
  "recommended_tasks": [],
  "calendar_events": [],
  "mode": "planning_read_only",
  "errors": []
}
```

You can pass `current_time` for local testing:

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"I feel tired. What should I work on right now?","current_time":"2026-06-04T14:00:00-05:00"}'
```

## Notes

- This MVP is read-only.
- Missing Todoist or Google credentials are returned as clear response errors.
- Secrets are loaded from `backend/.env`.
- The backend does not print or return secret values.
- Siri Shortcuts, Apple Reminders, calendar writes, and Todoist writes are intentionally out of scope for the MVP.
