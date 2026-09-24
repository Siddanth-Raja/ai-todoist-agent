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
USER_TIMEZONE=America/Chicago

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini

AGENT_API_KEY=choose_a_private_api_key_for_chat_requests
```

`GOOGLE_CALENDAR_ID` defaults to `primary` if omitted.
`USER_TIMEZONE` defaults to `America/Chicago` if omitted.
`OPENAI_MODEL` defaults to `gpt-5.4-mini` if omitted.
`AGENT_API_KEY` is required for `POST /chat`.

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

Google Cloud setup for Desktop OAuth, recommended:

1. Open Google Cloud Console.
2. Create or select a project.
3. Enable the Google Calendar API.
4. Configure the OAuth consent screen.
5. Create an OAuth client ID. Use a Desktop app client.
6. Copy the client ID and client secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

Then run:

```bash
python scripts/google_oauth_setup.py --desktop --write-env
```

This uses `google-auth-oauthlib` `InstalledAppFlow`, opens a local consent flow on a random available port, prints the refresh token, and writes it into `backend/.env`.

Google Cloud setup for Web OAuth, alternate:

1. Create an OAuth client ID. Use a Web application client.
2. Add this authorized redirect URI:

```text
http://localhost
```

3. Copy the client ID and client secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
4. Run the local OAuth setup script:

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
- can write `GOOGLE_REFRESH_TOKEN` to `backend/.env` with `--write-env`
- prints client ID and refresh token prefixes for diagnostics
- warns if `calendar.events` is missing

If you do not pass `--write-env`, put the printed refresh token into `GOOGLE_REFRESH_TOKEN` manually.

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
  "mode": "ai_agent"
}
```

## SID-260 College read surface

The least-privilege College read surface is intentionally separate from the
main application entrypoint while the unrelated SID-249 changes there remain
paused. It exposes exactly two authenticated, side-effect-free operations:

- `GET /college/state` (`get_college_state`)
- `GET /college/update-status` (`get_update_status`)

Bind the existing bearer credential to a trusted server-side College principal:

```text
AGENT_API_KEY=choose_a_private_api_key
COLLEGE_ACTOR_ID=server_owned_actor_id
COLLEGE_WORKSPACE_ID=server_owned_workspace_id
COLLEGE_ALLOWED_COURSE_IDS=optional,comma,separated,course_ids
COLLEGE_ALLOW_CROSS_COURSE=true
```

Cross-course access defaults off unless `COLLEGE_ALLOW_CROSS_COURSE` is
explicitly enabled. An explicitly configured empty course allowlist authorizes
no College records or receipts.

Run the read-only surface from `backend/`:

```bash
uvicorn app.college_read_api:app --host 127.0.0.1 --port 8001
```

`get_college_state` requires an explicit `course` or `cross_course` scope,
timezone-aware bounded horizon, and IANA timezone. Course scope uses repeated
`course_id` query parameters. Results use `college-state-read/1.0`, return at
most 50 records per page, and use a signed cursor tied to one unchanged SQLite
snapshot. Malformed stored coverage is omitted from typed records and reported
through a bounded non-content diagnostic; returned coverage dimensions remain
within the contract enums. `get_update_status` accepts exactly one `command_id`,
`idempotency_key`, or `receipt_id` and uses `college-update-status/1.0`.

Actor/workspace values are never accepted from the request. The service opens
the existing SQLite database with `mode=ro` and `query_only`, returns
`uninitialized` without creating a database or schema, and never refreshes a
provider, produces an assessment, advances a baseline, acknowledges a receipt,
or executes an action.

## SID-261 College capture surface

The reviewed write adapter is also a separate entrypoint, leaving the paused
SID-249 `app.main` bytes untouched. It exposes one authenticated operation:

- `POST /college/update` (`record_college_update`)

It requires the existing SID-151 and SID-250 schemas to have been initialized
at an explicit migration/startup boundary. Bind actor, workspace, allowed
sections, reviewed conversation bindings, and reviewed shorthand server-side:

```text
AGENT_API_KEY=choose_a_private_api_key
COLLEGE_ACTOR_ID=server_owned_actor_id
COLLEGE_WORKSPACE_ID=server_owned_workspace_id
COLLEGE_ALLOWED_SECTION_IDS=section-calc,section-engr
COLLEGE_BINDINGS_BY_CONVERSATION_JSON={"conversation-id":["reviewed-binding-id"]}
COLLEGE_REVIEWED_REFERENTS_JSON={"Topic 4 individual":"work-item-id","team":"team-work-item-id"}
```

Run it from `backend/`:

```bash
uvicorn app.college_capture_api:app --host 127.0.0.1 --port 8002
```

Capture accepts a stable command ID/key, `chatgpt` or `app` surface, authenticated
conversation identity, timezone-aware assertion time, IANA timezone, and one of
the reviewed initial language patterns: the Calc topic/check/warning report, the
Topic 4 individual/team mixed update, or the derivatives/definition-problems
learning report. Structured assessment and lifecycle operations are separate.
This initial adapter does not claim arbitrary class-chat language understanding;
unmatched or consequentially ambiguous wording is retained for review rather
than guessed. The surface labels are provenance inputs, not evidence that a
ChatGPT tool or app client has been connected or deployed. Actor/workspace fields
are rejected. Exact active
`college-operational` opt-in and one valid reviewed course binding are required.
Ambiguous consequential content is retained through SID-151 as reviewable
evidence; clear facts are applied atomically through SID-250. Responses identify
`applied`, `saved_for_review`, `pending`, or `uncertain` outcomes and carry the
durable receipt/status identity. The adapter always emits
`action_intent=no_provider_action`; it never creates a task or Calendar event,
sends email, refreshes a provider, or grants standing provider approval.

## 8. Test Chat

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $AGENT_API_KEY" \
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
  "pending_action": null,
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
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"I feel tired. What should I work on right now?","current_time":"2026-06-04T14:00:00-05:00"}'
```

## Notes

- The model never calls Todoist or Google directly. It returns structured JSON, then the backend executes allowed safe actions.
- Unsafe actions are blocked: deletes, event moves, meeting cancellation, emails, attendee invites, and task completion unless explicitly requested.
- Missing Todoist or Google credentials are returned as clear response errors.
- `/chat` requires `Authorization: Bearer <AGENT_API_KEY>`. `/health` is public.
- If OpenAI fails or `OPENAI_API_KEY` is invalid, `/chat` falls back to deterministic planning.
- Secrets are loaded from `backend/.env`.
- The backend does not print or return secret values.
- Siri Shortcuts and Apple Reminders are intentionally out of scope for this version.
