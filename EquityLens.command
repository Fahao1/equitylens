#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "EquityLens needs its project Python environment. Follow README.md once to install dependencies."
  read -r -p "Press Return to close. " reply
  exit 1
fi
if ! .venv/bin/python scripts/service.py start --open; then
  echo "EquityLens could not start. The error above identifies the next step."
  read -r -p "Press Return to close. " reply
  exit 1
fi
