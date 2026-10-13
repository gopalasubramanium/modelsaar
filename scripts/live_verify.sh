#!/usr/bin/env bash
# One-command, RESUMABLE live verification against your own inference server (nothing is downloaded).
#
#   scripts/live_verify.sh [OLLAMA_URL] [DEPLOYMENT ...]
#     OLLAMA_URL   default $OLLAMA_URL or http://127.0.0.1:11434
#     DEPLOYMENT   deployment ids or bare model names for the evaluation (default: 3 complementary
#                  models from the GX10 setup; adjust to what `modelsaar discover` shows)
#
# Output: ./live-verify-<commit>/ (fixed name per commit => re-running RESUMES: finished steps are
# skipped, the evaluation continues from its checkpoint). Every file is safe to share: keys are
# redacted and the evaluation records carry ids/status/latency/scorer detail only.
set -u
URL="${1:-${OLLAMA_URL:-http://127.0.0.1:11434}}"
shift || true
DEPS=("$@")
if [ ${#DEPS[@]} -eq 0 ]; then DEPS=(qwen3.6:latest gemma4:31b qwen3-coder:latest); fi
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
OUT="live-verify-$COMMIT"
mkdir -p "$OUT"
export MODELSAAR_HOME="$PWD/$OUT/home" PYTHONUNBUFFERED=1
PORT_FILE="$OUT/port"; [ -s "$PORT_FILE" ] || echo $((20000 + RANDOM % 20000)) > "$PORT_FILE"
PORT="$(cat "$PORT_FILE")"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/summary.txt"; }
# step NAME CMD...: runs once; a later run skips it when NAME.ok exists (delete the marker to redo)
step() {
  local name="$1"; shift
  if [ -e "$OUT/$name.ok" ]; then log "-- $name: done earlier (skip)"; return 0; fi
  log "== $name: $*"
  "$@" > "$OUT/$name.txt" 2>&1; local rc=$?
  log "   exit=$rc"
  [ $rc -eq 0 ] && touch "$OUT/$name.ok"
  return $rc
}
redact() { sed -E 's/(ms[ka]_)[A-Za-z0-9_-]+/\1REDACTED/g'; }

log "ModelSaar live verify; commit $COMMIT; backend $URL; eval deployments: ${DEPS[*]}; output $OUT"
step 00-env bash -c "uname -a; python3 --version; modelsaar --version; git rev-parse HEAD; git status --short | head -20"
step 01-backend-version curl -sS -m 5 "$URL/api/version"
step 02-backend-tags curl -sS -m 10 "$URL/api/tags"
step 03-backend-ps curl -sS -m 5 "$URL/api/ps"
if [ ! -e "$MODELSAAR_HOME/config.yaml" ]; then
  step 10-init modelsaar init --endpoint "$URL" --type ollama --port "$PORT" --force
else
  log "-- 10-init: config exists (skip)"
fi
step 10b-config-redacted bash -c "modelsaar config show | sed -E 's/(api_key:).*/\1 REDACTED/'"
step 11-discover modelsaar discover
step 12-doctor modelsaar doctor
# Probes run offline here (no gateway listening yet); they reserve through this process's admission.
step 13-probe-all modelsaar probe --all --timeout 300
step 14-discover-after-probe modelsaar discover --json
step 15-explain-chat modelsaar explain -m "Give me one sentence of encouragement before an exam."
step 16-explain-code-tools modelsaar explain -m "Fix the failing pytest in src/app.py" --tools
step 17-explain-vision modelsaar explain -m "What is in this picture?" --image
step 18-explain-schema modelsaar explain -m "Extract name and age from: Priya, 34" --json-schema

if [ ! -e "$OUT/29-client-checks.ok" ]; then
  log "== starting gateway on port $PORT"
  modelsaar serve > "$OUT/20-serve.log" 2>&1 &
  GW=$!
  for i in $(seq 1 50); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 0.2; done
  # keys stay in the environment so no command line (logged above) ever contains them
  export KEY=$(head -1 "$MODELSAAR_HOME/keys/api_keys") ADM=$(head -1 "$MODELSAAR_HOME/keys/admin_key") GW_URL="http://127.0.0.1:$PORT"
  step 21-models bash -c 'curl -sS -m 10 "$GW_URL/v1/models" -H "Authorization: Bearer $KEY"'
  step 22-test modelsaar test
  step 23-admin-probe-via-gateway bash -c 'curl -sS -m 600 -X POST "$GW_URL/admin/probe" -H "Authorization: Bearer $ADM" -H "Content-Type: application/json" -d "{\"deployment\":\"ollama/$1\",\"which\":[\"streaming\"]}"' _ "${DEPS[0]}"
  step 29-client-checks bash -c 'python3 "$1" "$GW_URL" "$KEY" "$2" "$ADM"' _ "$(dirname "$0")/live_client_checks.py" "$OUT/client-checks.json"
  step 27-decisions modelsaar decisions --limit 30
  step 28-status modelsaar status
  kill $GW 2>/dev/null; wait $GW 2>/dev/null
  log "== gateway stopped"
  rm -f "$OUT/27-decisions.ok" "$OUT/28-status.ok"  # cheap; always refreshed
else
  log "-- gateway/client checks: done earlier (skip)"
fi

# Evaluation: resumable. Closing the terminal keeps the checkpoint; re-running continues.
DEPARGS=(); for d in "${DEPS[@]}"; do DEPARGS+=("$d"); done
if [ ! -e "$OUT/30-eval-live.ok" ]; then
  log "== 30-eval-live (resumable; checkpoint $OUT/eval-live.json.records.jsonl)"
  modelsaar eval --mode live --save-measurements --deployments "${DEPARGS[@]}" \
    --out "$OUT/eval-live.json" --checkpoint "$OUT/eval-live.json.records.jsonl" --resume > "$OUT/30-eval-live.txt" 2>&1
  rc=$?; log "   exit=$rc"; [ $rc -eq 0 ] && touch "$OUT/30-eval-live.ok"
else
  log "-- 30-eval-live: done earlier (skip)"
fi
step 31-explain-after-eval modelsaar explain -m "Fix the failing pytest in src/app.py" --tools
step 32-discover-after-eval modelsaar discover --json
step 33-doctor-after-eval modelsaar doctor

# Real clients: run only what is installed; otherwise record NOT RUN with the exact command.
{
  echo "# Real client checks (installed clients only)"
  for c in opencode openclaw hermes; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c: installed at $(command -v "$c") -> run: modelsaar client-config $c --apply ; then use the client and inspect: modelsaar decisions"
    else echo "$c: NOT RUN (not installed). Command: modelsaar client-config $c --apply; then chat in the client; verify with: modelsaar decisions --limit 10"; fi
  done
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Image}}' 2>/dev/null | grep -qi open-webui; then
    echo "open-webui: container running -> connect with the snippet from: modelsaar client-config open-webui"
  else
    echo "open-webui: NOT RUN (no running container). Command: docker run -d -p 3000:8080 ghcr.io/open-webui/open-webui:main; set OPENAI_API_BASE_URL=http://host.docker.internal:$PORT/v1 (see modelsaar client-config open-webui)"
  fi
} > "$OUT/50-real-clients.txt"

# Redact keys anywhere in the outputs (summary, serve log, decisions)
for f in "$OUT"/*.txt "$OUT"/*.log; do [ -f "$f" ] && sed -i.bak -E 's/(ms[ka]_)[A-Za-z0-9_-]+/\1REDACTED/g' "$f" && rm -f "$f.bak"; done
log "done. Files: $OUT/ (eval-live.json, client-checks.json, numbered steps). Re-run the same command to resume/refresh."
