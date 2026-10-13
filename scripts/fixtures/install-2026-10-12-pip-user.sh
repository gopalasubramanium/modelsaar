#!/bin/sh
# FIXTURE: the installer served before 2026-10-13 (pip --user fallback). Kept verbatim so scripts/installer_fallback_tests.py
# can reproduce the externally-managed-environment failure it caused. Do not use.
# ModelSaar installer — https://modelsaar.com/install.sh
#
# What this does, in order (nothing else):
#   1. checks the platform (macOS, Linux, WSL2) and finds a way to install a Python package:
#      uv (preferred; fetches Python 3.12 itself), pipx, or `python3 -m pip install --user` with Python >= 3.10;
#   2. installs the ModelSaar package from GitHub at the PINNED COMMIT below (a reviewed revision of the
#      development preview; no release has been tagged and no package is published);
#   3. runs `modelsaar init` if you have no configuration yet (looks for Ollama on 127.0.0.1:11434 and the
#      other documented loopback ports; writes ~/.modelsaar/config.yaml and private keys, mode 600);
#   4. starts a temporary gateway on the configured port, sends one request through `auto`, stops it and
#      prints the result and your next step.
# It never downloads a model, never accepts a model licence, never installs uv/pipx/Python for you, never
# overwrites an existing config, keys or state, and never changes a client's configuration.
#
# Options (environment variables):
#   MODELSAAR_REF=<sha>          install another commit (you take responsibility for it)
#   MODELSAAR_ENDPOINT=<url>     backend to configure instead of auto-detecting local Ollama
#   MODELSAAR_TYPE=ollama|openai_compatible   backend type for MODELSAAR_ENDPOINT (default ollama)
#   MODELSAAR_PORT=<port>        gateway port for a new config (default 8484)
#   MODELSAAR_NO_CHECK=1         skip the verification request
#   MODELSAAR_HOME=<dir>         where config/keys/state live (default ~/.modelsaar)
set -eu

REPO="https://github.com/gopalasubramanium/modelsaar"
REF="${MODELSAAR_REF:-__PINNED_SHA__}"
SOURCE="${MODELSAAR_SOURCE:-git+${REPO}}"   # testing hook: e.g. git+file:///path/to/checkout
PORT="${MODELSAAR_PORT:-8484}"
HOME_DIR="${MODELSAAR_HOME:-$HOME/.modelsaar}"

say() { printf '%s\n' "$*"; }
die() { printf 'modelsaar install: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- 1. platform -----------------------------------------------------------------------------------
OS="$(uname -s 2>/dev/null || echo unknown)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then PLATFORM="WSL2 (Linux)"; else PLATFORM="Linux"; fi ;;
  *) die "unsupported platform '$OS'. Supported: macOS, Linux, Windows via WSL2 (run this inside WSL)." ;;
esac
say "ModelSaar installer — $PLATFORM, commit ${REF}"

py_ok() {  # $1 = python executable; true if >= 3.10
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# ---- 2. install ------------------------------------------------------------------------------------
SPEC="${SOURCE}@${REF}"
METHOD=""
if have uv; then
  METHOD="uv"
  say "installing with uv (isolated tool environment; Python 3.12 is fetched by uv if needed)"
  uv tool install --force --python 3.12 "modelsaar @ ${SPEC}" || die "uv tool install failed"
  BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
elif have pipx; then
  METHOD="pipx"
  say "installing with pipx (isolated environment)"
  pipx install --force "modelsaar @ ${SPEC}" || die "pipx install failed"
  BIN_DIR="$HOME/.local/bin"
else
  PY=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$cand" && py_ok "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    die "no supported installer found. Install one of:
  - uv:    https://docs.astral.sh/uv/getting-started/installation/   (recommended; brings its own Python)
  - pipx:  https://pipx.pypa.io/stable/installation/
  - Python 3.10+ with pip (python3 --version shows $(python3 --version 2>&1 || echo 'none'))
then run this script again."
  fi
  METHOD="pip"
  say "installing with $PY -m pip install --user"
  "$PY" -m pip install --user --quiet "${SPEC}" || die "pip install failed"
  BIN_DIR="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("scripts", "posix_user"))' 2>/dev/null || echo "$HOME/.local/bin")"
fi
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) PATH="$BIN_DIR:$PATH"; export PATH; PATH_NOTE="add $BIN_DIR to your PATH to run 'modelsaar' from a new shell" ;; esac
have modelsaar || die "the 'modelsaar' command is not on PATH after installation (looked in $BIN_DIR)"
say "installed: $(modelsaar --version) via $METHOD ($(command -v modelsaar))"

# ---- 3. configure ------------------------------------------------------------------------------------
export MODELSAAR_HOME="$HOME_DIR"
if [ -f "$HOME_DIR/config.yaml" ]; then
  say "existing configuration kept: $HOME_DIR/config.yaml (keys and state untouched)"
  modelsaar keys ensure >/dev/null
else
  if [ -n "${MODELSAAR_ENDPOINT:-}" ]; then
    modelsaar init --endpoint "$MODELSAAR_ENDPOINT" --type "${MODELSAAR_TYPE:-ollama}" --port "$PORT" \
      || die "init failed for endpoint $MODELSAAR_ENDPOINT"
  else
    if ! modelsaar init --port "$PORT"; then
      die "no inference server found on the documented loopback ports (Ollama 11434, LM Studio 1234, llama.cpp 8080, vLLM 8000).
Start your backend (e.g. 'ollama serve' and 'ollama pull <model>') and run this script again, or point it at a server:
  MODELSAAR_ENDPOINT=http://host:port MODELSAAR_TYPE=ollama|openai_compatible sh install.sh"
    fi
  fi
fi

# ---- 4. verify ---------------------------------------------------------------------------------------
GW_PORT="$(modelsaar config show 2>/dev/null | awk '/^server:/{s=1} s && /^  port:/{print $2; exit}')"
GW_PORT="${GW_PORT:-$PORT}"
GW_URL="http://127.0.0.1:${GW_PORT}"
if [ "${MODELSAAR_NO_CHECK:-0}" = "1" ]; then
  say "verification skipped (MODELSAAR_NO_CHECK=1)"
else
  # Identify what listens on the port BEFORE anything is sent to it. Only the ModelSaar health
  # contract (unauthenticated GET /healthz returning JSON with "service":"modelsaar") counts as a
  # gateway; any other listener is a port collision. This is collision detection, not authentication.
  HEALTH="$(curl -sS -m 3 -o - -w '\n%{http_code}' -H 'Accept: application/json' "$GW_URL/healthz" 2>/dev/null || true)"
  HEALTH_CODE="$(printf '%s' "$HEALTH" | tail -n 1)"
  HEALTH_BODY="$(printf '%s' "$HEALTH" | sed '$d')"
  if [ "$HEALTH_CODE" = "200" ] && printf '%s' "$HEALTH_BODY" | grep -q '"service"[[:space:]]*:[[:space:]]*"modelsaar"'; then
    say "a ModelSaar gateway is already listening on $GW_URL (identified by its health contract); using it for the check"
    STARTED=""
  elif [ -n "$HEALTH_CODE" ] && [ "$HEALTH_CODE" != "000" ]; then
    die "port $GW_PORT is in use by something that is not a ModelSaar gateway (GET $GW_URL/healthz answered HTTP $HEALTH_CODE without the ModelSaar health contract). Nothing was sent to it. Choose another port: MODELSAAR_PORT=8585 sh install.sh (new config), or edit server.port in $HOME_DIR/config.yaml"
  elif (command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$GW_PORT" 2>/dev/null); then
    die "port $GW_PORT is in use by something that is not a ModelSaar gateway. Choose another port: MODELSAAR_PORT=8585 sh install.sh (new config), or edit server.port in $HOME_DIR/config.yaml"
  else
    say "starting a temporary gateway on $GW_URL for the check …"
    modelsaar serve >"$HOME_DIR/install-check.log" 2>&1 &
    STARTED=$!
    i=0
    until curl -fsS -m 2 "$GW_URL/healthz" 2>/dev/null | grep -q '"service"[[:space:]]*:[[:space:]]*"modelsaar"'; do
      i=$((i+1)); if [ "$i" -gt 40 ]; then kill "$STARTED" 2>/dev/null; die "gateway did not start; see $HOME_DIR/install-check.log"; fi
      sleep 0.5
    done
  fi
  say ""
  # `modelsaar test` re-identifies the gateway, sends the key only to it, and succeeds only when the
  # response carries ModelSaar routing attribution (request id + deployment) for the `auto` request.
  if modelsaar test --model auto; then
    RESULT="OK — 'auto' was routed by ModelSaar to the deployment shown above (request id printed)"
  else
    RESULT="the check did not pass (see the message above: no deployment qualified, or the listener is not a ModelSaar gateway); 'modelsaar doctor' explains the remedies"
  fi
  if [ -n "${STARTED:-}" ]; then kill "$STARTED" 2>/dev/null || true; wait "$STARTED" 2>/dev/null || true; say "temporary gateway stopped"; fi
  say ""
  say "verification: $RESULT"
fi

# ---- 5. next steps -------------------------------------------------------------------------------------
say ""
say "Gateway address:  ${GW_URL}/v1       (loopback only; see modelsaar.com/privacy to expose it deliberately)"
say "API key:          head -1 $HOME_DIR/keys/api_keys"
say "Config:           $HOME_DIR/config.yaml"
say ""
say "Next:"
say "  1. run the gateway:        modelsaar serve        (keep it running; examples/ has launchd and systemd units)"
say "                             (init has already run; do not run 'modelsaar init' again — it keeps your existing config)"
say "  2. check it:               modelsaar test         (in another terminal)"
say "  3. connect an app, one command per app:"
say "       modelsaar client-config open-webui     modelsaar client-config opencode   (or opencode-v2)"
say "       modelsaar client-config openclaw       modelsaar client-config hermes"
say "     or set Base URL ${GW_URL}/v1, model 'auto', and the API key in any OpenAI-compatible app:"
say "     run 'head -1 $HOME_DIR/keys/api_keys' and paste the printed msk_… line into the key field"
say "  verify capabilities once:  modelsaar probe --all  (while the gateway runs; uses your backend's compute)"
say "  diagnose:                  modelsaar doctor · modelsaar decisions · modelsaar explain -m \"…\""
say "  uninstall:                 modelsaar uninstall; then: uv tool uninstall modelsaar | pipx uninstall modelsaar | pip uninstall modelsaar"
[ -n "${PATH_NOTE:-}" ] && say "" && say "note: $PATH_NOTE"
exit 0
