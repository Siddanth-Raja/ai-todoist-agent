# Personal Chief of Staff

AI-assisted planning MVP with a FastAPI backend and a mobile-first Next.js frontend.

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Create `backend/.env` before running the server. See [backend/README.md](backend/README.md) for the full Todoist, Google Calendar, OpenAI, and `AGENT_API_KEY` setup.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

In the app, go to Settings and save:

- Backend URL: `http://127.0.0.1:8000`
- API key: the same value as `AGENT_API_KEY` in `backend/.env`

The Chat tab sends `POST /chat` with `Authorization: Bearer <AGENT_API_KEY>` and renders the assistant answer, action cards, confirmation prompts, and development-only debug errors.

## Using ngrok

Expose the backend:

```bash
ngrok http 8000
```

Copy the HTTPS forwarding URL, then save it in the frontend Settings as the Backend URL. Keep the same `AGENT_API_KEY`.

If you expose the frontend too, run a second tunnel:

```bash
ngrok http 3000
```

The backend includes CORS defaults for localhost development and `*.ngrok-free.app` origins.
