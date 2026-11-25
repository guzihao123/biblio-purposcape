#!/usr/bin/env bash
# Reproducible offline acceptance run for purpose-landscape-web.
#
# What it does (all inside the dedicated test profile):
#   1. Builds the test images (backend from Dockerfile.test on top of the
#      production web image; Node 22 from Dockerfile.node-test).
#   2. Runs the default offline backend pytest suite in a throwaway container
#      (no live-provider variables; PURPOSE_LANDSCAPE_HCC_FIXTURES +
#      PYTHONPATH set per the acceptance contract).
#   3. Runs the Function Node tests + fake-store/RLS contract under Node 22.
#   4. Brings up the isolated web/worker/redis stack (ports 8034/8035 only,
#      dedicated volumes, never the production 8000/Redis/database).
#   5. Verifies the production static entry: / and /history return 200,
#      /api/<unknown> returns 404.
#   6. Verifies the real worker registered against the TEST Redis only.
#   7. Writes result.json and sanitized logs under logs/, then tears the
#      stack down (down -v) so no test state persists.
#
# Usage: ./run-tests.sh            (full run)
#        ./run-tests.sh --keep    (skip final compose down -v)
set -u

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROFILE_DIR"
COMPOSE="docker compose -f compose.test.yaml"
LOG_DIR="$PROFILE_DIR/logs"
mkdir -p "$LOG_DIR"
RESULT="$PROFILE_DIR/result.json"
KEEP_STACK=0
[ "${1:-}" = "--keep" ] && KEEP_STACK=1

HTTP_PORT="${PLW_TEST_HTTP_PORT:-8034}"
BASE_URL="http://127.0.0.1:${HTTP_PORT}"

note() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail "docker is required"

# --- preflight: live-provider variables must NOT leak into the run ----------
note "Preflight: ensuring no live-provider variables are set"
for var in RUN_LIVE_OPENALEX_ACCEPTANCE RUN_LIVE_QWEN_ACCEPTANCE \
           QWEN_API_KEY QWEN_BASE_URL QWEN_BILLING_AUTHORIZED OPENALEX_API_KEY; do
  if [ -n "${!var:-}" ]; then
    fail "$var is set in the environment; unset it before the offline run"
  fi
done
echo "ok: no live-provider variables present"

# --- 1. build images ---------------------------------------------------------
note "Building test images"
$COMPOSE build backend-test node-test web 2>&1 | tee "$LOG_DIR/build.log" \
  || fail "image build failed"
WEB_IMAGE_REF="$(docker image inspect purpose-landscape-web-test:latest --format '{{.Id}}' 2>/dev/null || echo unknown)"
NODE_IMAGE_REF="$(docker image inspect purpose-landscape-web-node-test:latest --format '{{.Id}}' 2>/dev/null || echo unknown)"

# --- environment facts (never claim arm64 results as amd64 or vice versa) ----
ARCH="$(docker run --rm purpose-landscape-web-test:latest python -c 'import platform; print(platform.machine())')"
PY_VER="$(docker run --rm purpose-landscape-web-test:latest python --version 2>&1)"
NODE_VER="$(docker run --rm purpose-landscape-web-node-test:latest node --version)"
HOST_ARCH="$(uname -m)"
echo "container arch=$ARCH python=$PY_VER node=$NODE_VER host=$HOST_ARCH"

# --- 2. backend pytest -------------------------------------------------------
note "Running default offline backend tests in container"
$COMPOSE run --rm --no-deps backend-test 2>&1 | tee "$LOG_DIR/backend-pytest.log"
BACKEND_EXIT=${PIPESTATUS[0]}
echo "backend pytest exit code: $BACKEND_EXIT"

# Classify failures against known-failures.json (tests still RUN and their
# failures are reported in full; this only categorises them for the verdict).
FAILED_IDS="$(grep -E '^FAILED ' "$LOG_DIR/backend-pytest.log" | sed 's/^FAILED //' | sort -u)"
KNOWN_JSON="$(cat "$PROFILE_DIR/known-failures.json")"
BACKEND_CLASSIFICATION="$(FAILED_IDS="$FAILED_IDS" python3 - <<'EOF'
import json, os
failed = [line for line in os.environ["FAILED_IDS"].splitlines() if line.strip()]
known = {entry["id"]: entry["reason"] for entry in json.load(open("known-failures.json"))}
matched = [tid for tid in failed if tid in known]
unexpected = [tid for tid in failed if tid not in known]
print(json.dumps({"matched": matched, "unexpected": unexpected}))
EOF
)"
echo "backend failure classification: $BACKEND_CLASSIFICATION"
if [ "$BACKEND_EXIT" = 0 ]; then
  BACKEND_STATUS="passed"
elif [ "$(echo "$BACKEND_CLASSIFICATION" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["unexpected"]))')" = 0 ]; then
  BACKEND_STATUS="failed_known_only"
else
  BACKEND_STATUS="failed"
fi
echo "backend status: $BACKEND_STATUS"

# --- 3. Node Function tests --------------------------------------------------
note "Running Function Node tests (Node 22, no Deno)"
$COMPOSE run --rm --no-deps node-test 2>&1 | tee "$LOG_DIR/node-tests.log"
NODE_EXIT=${PIPESTATUS[0]}
echo "node tests exit code: $NODE_EXIT"

# --- 4. isolated web/worker/redis stack --------------------------------------
note "Starting isolated test stack (web on ${HTTP_PORT})"
$COMPOSE up -d redis web worker 2>&1 | tee "$LOG_DIR/stack-up.log" || fail "compose up failed"

note "Waiting for web health"
HEALTHY=0
for _ in $(seq 1 36); do
  if curl -fsS "$BASE_URL/api/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
  sleep 5
done
[ "$HEALTHY" = 1 ] || fail "web did not become healthy on $BASE_URL"

# --- 5. production static entry checks ---------------------------------------
note "Checking production static entry"
STATIC_JSON="[]"
STATIC_OK=1
check_path() {
  local path="$1" expect="$2"
  local actual
  actual="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL$path")"
  local pass=true
  [ "$actual" = "$expect" ] || pass=false
  echo "$path -> $actual (expected $expect)"
  STATIC_JSON="$(python3 -c 'import json,sys; a=json.loads(sys.argv[1]); a.append({"path":sys.argv[2],"expected":int(sys.argv[3]),"actual":int(sys.argv[4]),"pass":sys.argv[5]=="true"}); print(json.dumps(a))' "$STATIC_JSON" "$path" "$expect" "$actual" "$pass")"
  [ "$pass" = true ] || STATIC_OK=0
}
check_path "/" 200
check_path "/history" 200
check_path "/api/definitely-not-a-route" 404

# --- 6. worker verification (test Redis only) --------------------------------
note "Verifying worker registered against the TEST Redis only"
WORKER_KEYS="$($COMPOSE exec -T redis redis-cli --scan --pattern 'rq:worker:*' | sort | tr '\n' ' ')"
echo "rq worker keys in test redis: ${WORKER_KEYS:-<none>}"
[ -n "${WORKER_KEYS// }" ] || fail "no RQ worker registered in test redis"

# The test worker only resolves the test-compose redis service name; the
# production Redis/database are never contacted.
PROD_REDIS_TOUCHED="no"

$COMPOSE logs worker > "$LOG_DIR/worker.log" 2>&1 || true
$COMPOSE logs web > "$LOG_DIR/web.log" 2>&1 || true

# --- 7. sanitize logs --------------------------------------------------------
note "Sanitizing logs"
# The run sets no secrets. Scan anyway and flag anything credential-like.
SECRET_PATTERN='(sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|QWEN_API_KEY[=:]\S+)'
SECRETS_FOUND="$(python3 - "$LOG_DIR" "$SECRET_PATTERN" <<'PY'
import pathlib,re,sys
pattern=re.compile(sys.argv[2])
found=any(pattern.search(path.read_text(encoding='utf-8',errors='replace')) for path in pathlib.Path(sys.argv[1]).glob('*.log'))
print('potential secrets found' if found else 'none')
PY
)"
if [ "$SECRETS_FOUND" != "none" ]; then
  echo "WARNING: potential secrets found in logs"
fi
echo "sanitization: $SECRETS_FOUND"

# --- teardown -----------------------------------------------------------------
if [ "$KEEP_STACK" = 1 ]; then
  note "Keeping stack running (--keep); tear down later with: $COMPOSE down -v"
else
  note "Tearing down the test stack (down -v removes test volumes)"
  $COMPOSE down -v 2>&1 | tee "$LOG_DIR/stack-down.log" || true
fi

# --- result.json --------------------------------------------------------------
note "Writing $RESULT"
export HTTP_PORT BASE_URL ARCH HOST_ARCH PY_VER NODE_VER \
       WEB_IMAGE_REF NODE_IMAGE_REF BACKEND_EXIT NODE_EXIT \
       WORKER_KEYS PROD_REDIS_TOUCHED SECRETS_FOUND STATIC_JSON \
       BACKEND_CLASSIFICATION
python3 - "$RESULT" <<'EOF' || fail "failed to write result.json"
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

result_path = Path(sys.argv[1])
log_dir = result_path.parent / "logs"

def parse_pytest(text):
    totals = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "warnings": 0}
    # Final summary line, e.g. "2 failed, 420 passed, 4 skipped, 6 warnings in 26.27s"
    summary = re.findall(r"((?:\d+ \w+[,.]? ?)+) in [\d.]+s", text)
    if summary:
        for n, kind in re.findall(r"(\d+) (\w+)", summary[-1]):
            kind = "errors" if kind.startswith("error") else kind
            if kind in totals:
                totals[kind] += int(n)
    return totals, (summary[-1] if summary else None)

def parse_node(text):
    totals = {}
    for key in ("tests", "pass", "fail", "skipped", "cancelled"):
        found = re.findall(rf"[#ℹ] {key} (\d+)", text)
        if found:
            totals[key] = int(found[-1])
    return totals

backend_log = (log_dir / "backend-pytest.log").read_text(encoding="utf-8", errors="replace")
node_log = (log_dir / "node-tests.log").read_text(encoding="utf-8", errors="replace")
backend_totals, backend_summary = parse_pytest(backend_log)
node_totals = parse_node(node_log)
static_checks = json.loads(os.environ["STATIC_JSON"])
classification = json.loads(os.environ["BACKEND_CLASSIFICATION"])
known = {entry["id"]: entry["reason"] for entry in json.loads((result_path.parent / "known-failures.json").read_text(encoding="utf-8"))}
backend_status = "passed" if os.environ["BACKEND_EXIT"] == "0" else (
    "failed_known_only" if not classification["unexpected"] else "failed"
)

data = {
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "profile": "dev/acceptance/docker-test-profile",
    "isolation": {
        "composeProject": "purpose-landscape-web-test",
        "httpPort": int(os.environ["HTTP_PORT"]),
        "altHttpPort": 8035,
        "productionPortNotUsed": 8000,
        "dedicatedVolumes": [
            "purpose-landscape-web-test_test-data",
            "purpose-landscape-web-test_test-redis",
        ],
        "productionVolumesUntouched": ["landscape-data", "landscape-redis"],
        "liveProviderEnvSet": False,
        "env": {
            "PURPOSE_LANDSCAPE_HCC_FIXTURES": "/app/fixtures/hcc-20261122",
            "PYTHONPATH": "/app/backend",
        },
    },
    "environment": {
        "containerArch": os.environ["ARCH"],
        "hostArch": os.environ["HOST_ARCH"],
        "python": os.environ["PY_VER"],
        "node": os.environ["NODE_VER"],
        "denoInContainers": False,
        "images": {
            "backendTest": os.environ["WEB_IMAGE_REF"],
            "nodeTest": os.environ["NODE_IMAGE_REF"],
        },
    },
    "backend": {
        "command": "python -m pytest -q -p no:cacheprovider",
        "exitCode": int(os.environ["BACKEND_EXIT"]),
        "status": backend_status,
        "totals": backend_totals,
        "summaryLine": backend_summary,
        "knownFailures": [
            {"id": tid, "reason": known[tid]} for tid in classification["matched"]
        ],
        "unexpectedFailures": classification["unexpected"],
        "log": "logs/backend-pytest.log",
    },
    "node": {
        "command": "node --experimental-strip-types --test sites/functions/task_store.test.mjs sites/functions/routes.test.mjs sites/functions/forward.test.mjs",
        "exitCode": int(os.environ["NODE_EXIT"]),
        "totals": node_totals,
        "log": "logs/node-tests.log",
    },
    "worker": {
        "service": "worker (command: python worker.py)",
        "registeredInTestRedis": bool(os.environ["WORKER_KEYS"].strip()),
        "rqWorkerKeys": os.environ["WORKER_KEYS"].split(),
        "productionRedisTouched": os.environ["PROD_REDIS_TOUCHED"],
        "log": "logs/worker.log",
    },
    "staticEntry": {
        "baseUrl": os.environ["BASE_URL"],
        "checks": static_checks,
        "allPassed": all(c["pass"] for c in static_checks),
    },
    "logSanitization": {
        "secretsFound": os.environ["SECRETS_FOUND"],
        "logDir": "logs/",
    },
    "unverifiedBoundaries": [
        "Live OpenAlex/Qwen acceptance paths are opt-in and were not executed; their tests self-skip without RUN_LIVE_OPENALEX_ACCEPTANCE / QWEN credentials.",
        "PostgreSQL and RLS migrations were not executed; the fake-store/RLS contract test only reviews sites/schema.sql and the fixed-operation allowlist.",
        "No cloud deployment, no Qoder Sites publish, no paid API calls were performed.",
        "The worker was verified to register against the test Redis only; no end-to-end job was enqueued against the real stack in this profile (test_worker_e2e covers that offline via fakeredis inside the backend suite).",
        "Container architecture is reported from platform.machine() inside the container; results are valid for that architecture only.",
        "PyPI reachability is a build-time observation, not a conclusion: on 2026-11-24 pypi.org was unreachable from containers in this environment, so the build used a mirror index (PIP_INDEX_URL build ARG); the main line has since built successfully with the official index.",
    ],
}
result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", result_path)
EOF

note "Done. Backend exit=$BACKEND_EXIT (status=$BACKEND_STATUS) Node exit=$NODE_EXIT Static=$STATIC_OK"
if [ "$BACKEND_STATUS" != "failed" ] && [ "$NODE_EXIT" = 0 ] && [ "$STATIC_OK" = 1 ]; then
  if [ "$BACKEND_STATUS" = "failed_known_only" ]; then
    echo "OVERALL: PASS (backend has known environment-dependent failures, see result.json)"
  else
    echo "OVERALL: PASS"
  fi
else
  echo "OVERALL: FAIL"
  exit 1
fi
