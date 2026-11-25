#!/usr/bin/env bash
# Start the real sites/functions/index.ts under Deno on loopback, run the
# artifact-contract checks, then always stop the Deno process again.
#
#   ./start_and_check.sh                            # production-faithful: index.ts on :8000
#   PORT=8012 ./start_and_check.sh                  # explicit port via the dev port shim
#   SKIP_LARGE=1 ./start_and_check.sh               # faster, skips the 50MB upload
#   ORIGIN=http://127.0.0.1:8000 ./start_and_check.sh   # reuse an already running function
#
# Port note: sites/functions/index.ts:195 calls Deno.serve(handler), whose
# default port is hard-wired to 8000 -- the PORT env var is ignored (measured
# with Deno 2.9.8). When 8000 is taken, this script therefore loads the same
# entrypoint through dev/acceptance/artifact-contract/port_launcher.ts, which
# injects ACCEPTANCE_PORT without editing production code.
#
# Nothing here touches production, Render, Qoder or git remotes.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
DENO_BIN="${DENO_BIN:-$HOME/.deno/bin/deno}"
REQUESTED_PORT="${PORT:-8000}"
SECRET="${WORKER_SHARED_SECRET:-test-secret}"
IMPORT_MAP="$REPO/dev/acceptance/sites-live/stubs/import_map.json"
MAX_PORT=$((REQUESTED_PORT + 20))

if [[ ! -x "$DENO_BIN" ]]; then
  echo "Deno not found at $DENO_BIN (set DENO_BIN=/path/to/deno)" >&2
  exit 1
fi
if [[ ! -f "$IMPORT_MAP" ]]; then
  echo "import map missing: $IMPORT_MAP" >&2
  exit 1
fi

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

LOG_DIR="$HERE/logs"
mkdir -p "$LOG_DIR"

DENO_PID=""
cleanup() {
  if [[ -n "$DENO_PID" ]] && kill -0 "$DENO_PID" 2>/dev/null; then
    kill "$DENO_PID" 2>/dev/null
    for _ in $(seq 1 30); do
      kill -0 "$DENO_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$DENO_PID" 2>/dev/null
    echo "stopped deno pid ${DENO_PID}"
  fi
}
trap cleanup EXIT INT TERM

if [[ -n "${ORIGIN:-}" ]]; then
  PORT="$(python3 -c 'import sys; from urllib.parse import urlsplit; u=urlsplit(sys.argv[1]); print(u.port or 80)' "$ORIGIN")"
  echo "reusing running function at ${ORIGIN}"
else
  PORT="$REQUESTED_PORT"
  while port_busy "$PORT"; do
    PORT=$((PORT + 1))
    if [[ "$PORT" -gt "$MAX_PORT" ]]; then
      echo "No free port in ${REQUESTED_PORT}..${MAX_PORT}" >&2
      exit 1
    fi
  done

  ENTRY="$REPO/sites/functions/index.ts"
  if [[ "$PORT" != "$REQUESTED_PORT" ]]; then
    ENTRY="$HERE/port_launcher.ts"
    echo "port ${REQUESTED_PORT} is busy -> using ${PORT} through port_launcher.ts (index.ts is fixed to 8000)"
  fi

  DENO_LOG="$LOG_DIR/deno-${PORT}.log"
  ACCEPTANCE_PORT="$PORT" \
  PYTHON_API_ORIGIN="${PYTHON_API_ORIGIN:-http://127.0.0.1:9}" \
  WORKER_SHARED_SECRET="$SECRET" \
    "$DENO_BIN" run --allow-net --allow-env --import-map="$IMPORT_MAP" "$ENTRY" \
    >"$DENO_LOG" 2>&1 &
  DENO_PID=$!

  for _ in $(seq 1 150); do
    if curl -sS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      break
    fi
    kill -0 "$DENO_PID" 2>/dev/null || { echo "deno exited early:"; cat "$DENO_LOG"; exit 1; }
    sleep 0.1
  done
  curl -sS --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 || {
    echo "deno did not become healthy on ${PORT}"; cat "$DENO_LOG"; exit 1;
  }
  echo "deno ready on http://127.0.0.1:${PORT} (pid ${DENO_PID}, log ${DENO_LOG})"
fi

SKIP_ARG=""
[[ "${SKIP_LARGE:-0}" == "1" ]] && SKIP_ARG="--skip-large"

# shellcheck disable=SC2086 # intentional word splitting of the optional flag
python3 "$HERE/contract_checks.py" --origin "http://127.0.0.1:${PORT}" --secret "$SECRET" $SKIP_ARG
CHECKS=$?
python3 "$HERE/origin_probe.py" --function-origin "http://127.0.0.1:${PORT}" --secret "$SECRET"
PROBE=$?

echo
if [[ $CHECKS -eq 0 && $PROBE -eq 0 ]]; then
  echo "artifact contract: PASS"
else
  echo "artifact contract: FAIL (checks=${CHECKS}, origin_probe=${PROBE}) — see report.md"
fi
[[ $CHECKS -eq 0 && $PROBE -eq 0 ]]
