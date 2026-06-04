# Personal Chief of Staff Backend

AI-assisted MVP for Personal Chief of Staff.

The MVP exposes:

- `GET /health`
- `POST /chat`

`POST /chat` reads active Todoist tasks, reads today's Google Calendar events, finds the current or next free block, and sends that context to OpenAI for a structured decision. The backend may execute only safe simple actions after the model returns JSON: create a simple Todoist task or create a simple Google Calendar event with no busy conflict. Deterministic planning remains as fallback if OpenAI fails.

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
OPENAI_MODEL=gpt-5.4-mini
```

`GOOGLE_CALENDAR_ID` defaults to `primary` if omitted.
`OPENAI_MODEL` defaults to `gpt-5.4-mini` if omitted.

## 4. Get a Todoist API Token

1. Open Todoist.
2. Go to Settings.
3. Open Integrations.
4. Open Developer.
5. Copy the API token.
6. Put it in `TODOIST_API_TOKEN`.

## 5. Get Google OAuth Credentials and Refresh Token

The backend uses `google-api-python-client` with a refresh token. The local setup script requests the exact Calendar scopes this app needs:

```text
https://www.googleapis.com/auth/calendar.readonly
https://www.googleapis.com/auth/calendar.events
```

Google Cloud setup:

1. Open Google Cloud Console.
2. Create or select a project.
3. Enable the Google Calendar API.
4. Configure the OAuth consent screen.
5. Create an OAuth client ID. Use a Web application client.
6. Add this authorized redirect URI:

```text
http://localhost
```

7. Copy the client ID and client secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

Then run the local OAuth setup script:

```bash
python scripts/google_oauth_setup.py --manual --redirect-uri http://localhost
```

The script:

- prints the consent URL
- opens it in your browser if possible
- uses the exact redirect URI you pass with `--redirect-uri`
- receives the callback locally when not using `--manual`
- exchanges the authorization code for tokens
- prints granted scopes
- prints the refresh token
- warns if `calendar.events` is missing

Put the printed refresh token into `GOOGLE_REFRESH_TOKEN`.

If you prefer the local callback flow, configure the matching redirect URI in Google Cloud and run one of:

```bash
python scripts/google_oauth_setup.py --redirect-uri http://localhost
python scripts/google_oauth_setup.py --redirect-uri http://localhost:8080/
```

Manual mode with `http://localhost` is the recommended workaround for redirect mismatch issues:

```bash
python scripts/google_oauth_setup.py --manual --redirect-uri http://localhost
```

The script also supports the old OOB URI, but Google may reject it for newer OAuth clients:

```bash
python scripts/google_oauth_setup.py --manual --redirect-uri urn:ietf:wg:oauth:2.0:oob
```

Important OAuth parameters used by the script:

```text
access_type=offline
prompt=consent
include_granted_scopes=false
```

If your OAuth app is in testing mode, make sure your Google account is listed as a test user.

To diagnose Google auth without printing secrets:

```bash
python scripts/debug_google_auth.py
```

After a successful setup, the diagnostics should include:

```text
Calendar write scope present: yes
Write permission status: ok
```

If read works but event creation fails with `invalid_scope`, generate a new refresh token with `python scripts/google_oauth_setup.py`.

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
  "intent": "plan",
  "actions_taken": [],
  "needs_confirmation": false,
  "confirmation_prompt": null,
  "free_block": {},
  "recommended_tasks": [],
  "calendar_events": [],
  "mode": "ai_agent",
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

- The model never calls Todoist or Google directly. It returns structured JSON, then the backend executes allowed safe actions.
- Unsafe actions are blocked: deletes, event moves, meeting cancellation, emails, attendee invites, and task completion unless explicitly requested.
- Missing Todoist or Google credentials are returned as clear response errors.
- If OpenAI fails or `OPENAI_API_KEY` is invalid, `/chat` falls back to deterministic planning.
- Secrets are loaded from `backend/.env`.
- The backend does not print or return secret values.
- Siri Shortcuts and Apple Reminders are intentionally out of scope for this version.
