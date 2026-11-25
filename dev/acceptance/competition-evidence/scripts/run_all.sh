#!/bin/bash
# Competition evidence runner: real Chromium + real FastAPI/SQLite/RQ/Redis
# with offline providers, on isolated ports. Nothing is published.
#
# Ports: API 8026 / Skill-regression API 8027 / frontend 5194 / regression frontend 5195 / Redis 6394
# Run dir: dev/acceptance/competition-evidence/run
set -euo pipefail

PROJECT=/Users/crisprcas_9/WorkBuddy/2026-11-06-20-49-06/purpose-landscape-web
EVID="$PROJECT/dev/acceptance/competition-evidence"
export PATH="/Users/crisprcas_9/.workbuddy/binaries/node/versions/22.22.2-6/bin:$PATH"

cd "$PROJECT/frontend"
exec "$PROJECT/.venv/bin/python" "$EVID/scripts/run_runtime.py" -- \
  npm exec -- playwright test --config="$EVID/scripts/playwright.competition.config.ts"
