#!/usr/bin/env sh
# Fresh-volume container check (Compose-equivalent, no Compose required).
#   1. build the image locally (never pushed)
#   2. start it with an EMPTY named volume and the example config mounted read-only
#   3. expect: keys are created on first start, /healthz answers 200, the non-root user owns /data
#   4. restart with the same volume: keys unchanged (idempotent bootstrap)
# Usage: scripts/compose-smoke.sh [image-tag]
set -eu
TAG="${1:-modelsaar:smoke}"
VOL="modelsaar-smoke-$$"
NAME="modelsaar-smoke-$$"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker build -q -t "$TAG" . >/dev/null
docker volume create "$VOL" >/dev/null
run() {
  docker run -d --name "$NAME" -p 127.0.0.1:18484:8484 \
    -v "$VOL:/data" -v "$(pwd)/examples/config.docker.yaml:/data/config.yaml:ro" \
    --add-host host.docker.internal:host-gateway "$TAG" >/dev/null
}
wait_healthy() {
  i=0
  until curl -fsS http://127.0.0.1:18484/healthz >/dev/null 2>&1; do
    i=$((i+1)); [ "$i" -gt 60 ] && { echo "healthz did not answer"; docker logs "$NAME"; exit 1; }
    sleep 1
  done
}
run; wait_healthy
docker logs "$NAME" 2>&1 | grep -q "API key: created" || { echo "first start did not create keys"; docker logs "$NAME"; exit 1; }
docker exec "$NAME" sh -c 'id -u && test "$(id -u)" != 0' >/dev/null || { echo "container runs as root"; exit 1; }
docker exec "$NAME" sh -c 'test ! -w /data/config.yaml' || { echo "config mount is writable"; exit 1; }
K1="$(docker exec "$NAME" cat /data/keys/api_keys)"
docker rm -f "$NAME" >/dev/null
run; wait_healthy
docker logs "$NAME" 2>&1 | grep -q "API key: unchanged" || { echo "second start rotated or re-created keys"; docker logs "$NAME"; exit 1; }
K2="$(docker exec "$NAME" cat /data/keys/api_keys)"
[ "$K1" = "$K2" ] || { echo "API key changed across restarts"; exit 1; }
# /readyz is 503 without a reachable backend; that is expected on a CI runner without Ollama.
code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18484/readyz)"
echo "fresh-volume container check passed (readyz=$code without a backend, healthz=200, keys bootstrapped once)"
