#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

mkdir -p "$LOG_DIR"

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    echo "Backend already running on http://127.0.0.1:8000 (pid $(cat "$BACKEND_PID_FILE"))"
    return
  fi

  cd "$ROOT_DIR/backend"
  local python_cmd="python3"
  if [[ -x ".venv/bin/python" ]]; then
    python_cmd=".venv/bin/python"
  fi

  nohup "$python_cmd" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 >"$LOG_DIR/backend.log" 2>&1 < /dev/null &
  echo "$!" > "$BACKEND_PID_FILE"
  echo "Backend starting on http://127.0.0.1:8000 (pid $(cat "$BACKEND_PID_FILE"))"
}

start_frontend() {
  if is_running "$FRONTEND_PID_FILE"; then
    echo "Frontend already running on http://localhost:3010 (pid $(cat "$FRONTEND_PID_FILE"))"
    return
  fi

  cd "$ROOT_DIR/frontend"
  nohup npm run dev >"$LOG_DIR/frontend.log" 2>&1 < /dev/null &
  echo "$!" > "$FRONTEND_PID_FILE"
  echo "Frontend starting on http://localhost:3010 (pid $(cat "$FRONTEND_PID_FILE"))"
}

start_backend
start_frontend

echo
echo "Open http://localhost:3010"
echo "Logs: $LOG_DIR"
echo "Stop both with ./stop.sh"
