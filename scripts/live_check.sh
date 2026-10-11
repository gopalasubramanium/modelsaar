#!/usr/bin/env bash
# Live verification against YOUR inference server and models. Nothing here downloads a model.
# Produces ./live-check-<date>/ with every command's output, suitable for attaching to an issue
# or for updating docs/verification-report.md.
#
# Usage:  scripts/live_check.sh [OLLAMA_URL]        (default http://127.0.0.1:11434)
# Requires: modelsaar installed in the current environment (pip install -e .), curl, jq (optional).
set -u
URL="${1:-http://127.0.0.1:11434}"
OUT="live-check-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
export MODELSAAR_HOME="$PWD/$OUT/home"
PORT=$((20000 + RANDOM % 20000))
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/summary.txt"; }
run() { local name="$1"; shift; log "== $name: $*"; "$@" > "$OUT/$name.txt" 2>&1; local rc=$?; log "   exit=$rc"; return $rc; }

log "ModelSaar live check; backend $URL; output in $OUT"
run 00-env bash -c "uname -a; python3 --version; modelsaar --version; ollama --version 2>/dev/null || echo 'ollama CLI not found (fine if the server runs elsewhere)'"
run 01-backend-version curl -sS -m 5 "$URL/api/version"
run 02-backend-tags curl -sS -m 10 "$URL/api/tags"
run 03-backend-ps curl -sS -m 5 "$URL/api/ps"
run 10-init modelsaar init --endpoint "$URL" --type ollama --port "$PORT" --force
run 11-discover modelsaar discover
run 12-doctor modelsaar doctor
run 13-probe-all modelsaar probe --all --timeout 300
run 14-discover-after-probe modelsaar discover
run 15-explain-chat modelsaar explain -m "Give me one sentence of encouragement before an exam."
run 16-explain-code-tools modelsaar explain -m "Fix the failing pytest in src/app.py" --tools
run 17-explain-vision modelsaar explain -m "What is in this picture?" --image
run 18-explain-schema modelsaar explain -m "Extract name and age from: Priya, 34" --json-schema

log "== starting gateway on port $PORT"
modelsaar serve > "$OUT/20-serve.log" 2>&1 &
GW=$!
sleep 3
KEY=$(head -1 "$MODELSAAR_HOME/keys/api_keys")
run 21-models curl -sS -m 10 "http://127.0.0.1:$PORT/v1/models" -H "Authorization: Bearer $KEY"
run 22-test modelsaar test
# Two-deployment routing demonstration: a plain chat and a vision request (if any vision model exists)
run 23-chat-auto curl -sS -D - -m 300 "http://127.0.0.1:$PORT/v1/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply with one word: ready"}],"max_tokens":8}'
run 24-code-auto curl -sS -D - -m 600 "http://127.0.0.1:$PORT/v1/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Write a Python function is_palindrome(s) that ignores case and punctuation. Return only code in a ```python block."}],"max_tokens":300}'
run 25-stream-auto bash -c "curl -sS -N -m 300 'http://127.0.0.1:$PORT/v1/chat/completions' -H 'Authorization: Bearer $KEY' -H 'Content-Type: application/json' -d '{\"model\":\"auto-fast\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Count from 1 to 5.\"}],\"max_tokens\":30}' | head -c 4000"
run 26-tools-auto curl -sS -D - -m 600 "http://127.0.0.1:$PORT/v1/chat/completions" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"What time is it in Paris? Use the tool."}],"tools":[{"type":"function","function":{"name":"get_current_time","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],"max_tokens":200}'
run 27-decisions modelsaar decisions --limit 20
run 28-status modelsaar status
kill $GW 2>/dev/null; wait $GW 2>/dev/null
log "== gateway stopped"

run 30-eval-live modelsaar eval --mode live --probe --save-measurements --out "$OUT/eval-live.json"
run 31-explain-after-eval modelsaar explain -m "Fix the failing pytest in src/app.py" --tools

log "done. Review $OUT/summary.txt and the numbered files; eval-live.json holds the full report."
log "Distinct deployments chosen in this run (from decisions):"
grep -ho "ollama/[^ ]*" "$OUT/27-decisions.txt" 2>/dev/null | sort | uniq -c | tee -a "$OUT/summary.txt"
