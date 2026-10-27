#!/bin/zsh
set -e
cd "$(dirname "$0")"
if curl -fsS http://127.0.0.1:8780/api/state >/dev/null 2>&1; then
 open http://127.0.0.1:8780
 exit 0
fi
if [ -f "$HOME/Library/LaunchAgents/com.gamefit.workforce.plist" ]; then
 launchctl kickstart "gui/$(id -u)/com.gamefit.workforce" || true
 for gamefit_attempt in {1..15}; do
  if curl -fsS http://127.0.0.1:8780/api/state >/dev/null 2>&1; then
   open http://127.0.0.1:8780
   exit 0
  fi
  sleep 1
 done
 echo "Background service unavailable. Check Application Support/Gamefit Workforce/data/service-error.log."
 exit 1
fi
if [ ! -x .venv/bin/python ]; then
 python3 -m venv .venv
 .venv/bin/pip install -r requirements.txt
fi
if ! .venv/bin/python -c "import zk,reportlab" >/dev/null 2>&1; then
 .venv/bin/pip install -r requirements.txt
fi
.venv/bin/python server.py &
gamefit_pid=$!
trap 'kill "$gamefit_pid" 2>/dev/null || true' EXIT INT TERM
for gamefit_attempt in {1..30}; do
 if curl -fsS http://127.0.0.1:8780/api/state >/dev/null 2>&1; then
  open http://127.0.0.1:8780
  break
 fi
 sleep 1
done
wait "$gamefit_pid"
