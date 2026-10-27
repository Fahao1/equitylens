#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project_root="$PWD"
python="$project_root/.venv/bin/python"
vite="$project_root/frontend/node_modules/.bin/vite"
backend_log="$project_root/data/logs/backend.log"

if [[ ! -x "$python" || ! -x "$vite" ]]; then
  echo "Install project dependencies first using README.md (.venv and frontend/node_modules)." >&2
  exit 1
fi
"$python" -c 'import sys, yfinance; print("Python executable: " + sys.executable); print("Python version: " + sys.version.split()[0]); print("yfinance version: " + yfinance.__version__)'
"$python" - <<'PY'
import socket
import sys
for port in (8000, 5173):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            print(f"Port {port} is already in use. Stop the existing app using that port, then restart EquityLens. No existing process was stopped.", file=sys.stderr)
            raise SystemExit(1)
PY

mkdir -p "$(dirname "$backend_log")"
printf '\n--- EquityLens backend start %s ---\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$backend_log"
api_pid=''
web_pid=''
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n "$web_pid" ]]; then kill "$web_pid" 2>/dev/null || true; fi
  if [[ -n "$api_pid" ]]; then kill "$api_pid" 2>/dev/null || true; fi
  if [[ -n "$web_pid" ]]; then wait "$web_pid" 2>/dev/null || true; fi
  if [[ -n "$api_pid" ]]; then wait "$api_pid" 2>/dev/null || true; fi
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$python" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 >> "$backend_log" 2>&1 &
api_pid=$!
echo "Backend log: $backend_log"
ready=0
for ((attempt=0; attempt<60; attempt++)); do
  if ! kill -0 "$api_pid" 2>/dev/null; then
    echo "Backend exited before becoming ready. Full output: $backend_log" >&2
    tail -n 20 "$backend_log" >&2
    if wait "$api_pid"; then exit 1; else exit $?; fi
  fi
  if "$python" -c 'import json, urllib.request; response = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=0.5); raise SystemExit(0 if json.load(response).get("status") == "ok" else 1)' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.25
done
if [[ "$ready" != 1 ]]; then
  echo "Backend did not become ready. Full output: $backend_log" >&2
  tail -n 20 "$backend_log" >&2
  exit 1
fi

echo "Backend ready. Opening the frontend on http://127.0.0.1:5173"
(cd "$project_root/frontend"; exec "$vite" --host 127.0.0.1 --port 5173 --strictPort) &
web_pid=$!
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 0.25
done
if ! kill -0 "$api_pid" 2>/dev/null; then
  echo "Backend stopped; shutting down the frontend. Full output: $backend_log" >&2
  if wait "$api_pid"; then exit 1; else exit $?; fi
else
  echo "Frontend stopped; shutting down the backend." >&2
  if wait "$web_pid"; then exit 1; else exit $?; fi
fi
