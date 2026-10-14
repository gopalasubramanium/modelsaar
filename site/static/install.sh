#!/bin/sh
# ModelSaar installer — https://modelsaar.com/install.sh
#
# What this does, in order (nothing else):
#   1. checks the platform (macOS, Linux, WSL2) and chooses an ISOLATED way to install the package:
#        a. `uv` already on your PATH     -> `uv tool install` (its own environment), or
#        b. `pipx` already on your PATH   -> `pipx install` (its own environment), or
#        c. your Python 3.10+             -> a persistent, user-owned virtual environment under
#                                            ~/.local/share/modelsaar/envs/<commit>, or
#        d. none of the above usable      -> downloads ONE pinned, checksum-verified official uv binary into
#                                            ~/.local/share/modelsaar/uv (user-local; no sudo; nothing OS-wide)
#                                            and uses it to create that virtual environment (uv fetches a
#                                            Python of its own (3.10–3.13) into ~/.local/share/modelsaar/python
#                                            only if no Python 3.10+ is on the machine).
#      It NEVER runs `pip install --user` into the OS interpreter, never uses sudo, never touches an
#      EXTERNALLY-MANAGED marker and never uses --break-system-packages.
#   2. installs the ModelSaar package from the GitHub source archive of the PINNED COMMIT below (a reviewed
#      revision of the development preview; no release has been tagged and no package is published). Git is
#      not required.
#   3. runs `modelsaar init` if you have no configuration yet (looks for Ollama on 127.0.0.1:11434 and the
#      other documented loopback ports; writes ~/.modelsaar/config.yaml and private keys, mode 600);
#   4. starts a temporary gateway on the configured port, sends one request through `auto`, stops it and
#      prints the result and your next step.
# It never downloads a model, never accepts a model licence, never overwrites an existing config, keys or
# state, never edits your shell profile, and never changes a client's configuration.
# Repeat runs are safe: a complete installation of the same commit is reused; envs/current is switched to a
# new commit only after it has installed successfully, and the previous environment is kept (a running
# service keeps working until it is restarted; it is also the rollback target).
#
# Options (environment variables):
#   MODELSAAR_REF=<sha>          install another commit (you take responsibility for it)
#   MODELSAAR_ENDPOINT=<url>     backend to configure instead of auto-detecting local Ollama
#   MODELSAAR_TYPE=ollama|openai_compatible   backend type for MODELSAAR_ENDPOINT (default ollama)
#   MODELSAAR_PORT=<port>        gateway port for a new config (default 8484)
#   MODELSAAR_NO_CHECK=1         skip the verification request
#   MODELSAAR_HOME=<dir>         where config/keys/state live (default ~/.modelsaar)
#   MODELSAAR_RUNTIME_DIR=<dir>  where the installer keeps the environment and its helper
#                                (default ${XDG_DATA_HOME:-~/.local/share}/modelsaar; separate from MODELSAAR_HOME)
#   MODELSAAR_METHOD=uv|pipx|venv|bootstrap   force one installation method (testing / troubleshooting)
# Exit codes: 0 = package installed, configuration ready and the routing check passed (or skipped);
#             1 = the package or the configuration could not be set up (the message says what to do);
#             2 = package and configuration are in place but the routing check failed (backend unavailable, …).
set -eu

REPO="https://github.com/gopalasubramanium/modelsaar"
REF="${MODELSAAR_REF:-__PINNED_SHA__}"
PORT="${MODELSAAR_PORT:-8484}"
HOME_DIR="${MODELSAAR_HOME:-$HOME/.modelsaar}"
RUNTIME="${MODELSAAR_RUNTIME_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/modelsaar}"
LAUNCHER_DIR="$HOME/.local/bin"

# Package source: the immutable source archive of the pinned commit (no git needed). Testing hook:
# MODELSAAR_SOURCE=git+file:///path/to/checkout (a git URL, @REF is appended) or a path/URL of an archive.
case "${MODELSAAR_SOURCE:-}" in
  "")      SPEC="modelsaar @ ${REPO}/archive/${REF}.tar.gz" ;;
  git+*)   SPEC="${MODELSAAR_SOURCE}@${REF}" ;;
  *)       SPEC="modelsaar @ ${MODELSAAR_SOURCE}" ;;
esac

# Pinned helper for path d (official release assets of https://github.com/astral-sh/uv; the checksum of the
# downloaded archive must equal the value listed here for the machine's target, or nothing is installed).
UV_VERSION="0.12.24"
uv_sha256() {
  case "$1" in
    x86_64-unknown-linux-gnu)   echo b4dfaef47d491a7296981f8374a4595f55dbf84e8937c8ecd2983574d8bb3da6 ;;
    aarch64-unknown-linux-gnu)  echo 5231be65f496304623895dacdbf1de8504fec90303684bdf05805aa34414dd21 ;;
    x86_64-unknown-linux-musl)  echo 48170bd200a5430298c18f3b264485a1f3a8605f01088277daf6e37633edf0f5 ;;
    aarch64-unknown-linux-musl) echo 7f9ab4726d743b6a92e310477a7840c8a8a7b3938cb3c4657d541342fca75011 ;;
    aarch64-apple-darwin)       echo 0c4346de7abdb49495b393b9ec809fe387aa43e586be20fecb972216c1e71732 ;;
    x86_64-apple-darwin)        echo 4fa82e37cb94767661f532b001e470b67a186c7260e305bd84ddb78fd545c0b6 ;;
    *) echo "" ;;
  esac
}

say() { printf '%s\n' "$*"; }
die() { printf 'modelsaar install: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- 1. platform -----------------------------------------------------------------------------------
OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then PLATFORM="WSL2 (Linux)"; else PLATFORM="Linux"; fi ;;
  *) die "unsupported platform '$OS'. Supported: macOS, Linux, Windows via WSL2 (run this inside WSL)." ;;
esac
say "ModelSaar installer — $PLATFORM $ARCH, commit ${REF}"

py_ok() {  # $1 = python executable; true if >= 3.10
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# ---- helpers for paths c and d ----------------------------------------------------------------------
ENVS="$RUNTIME/envs"
ENV_NAME="$REF"                            # one directory per commit; never renamed (entry points keep absolute paths)
ENV_DIR="$ENVS/$ENV_NAME"
MARKER="$ENV_DIR/.modelsaar-installed"   # written only after a successful install; names the source it came from

fetch() {  # url dest — bounded attempts, no partial file left behind
  rm -f "$2"
  if have curl; then
    curl -fsSL --retry 2 --retry-delay 3 --connect-timeout 20 -m 600 -o "$2" "$1" && return 0
  elif have wget; then
    wget -q --tries=3 --timeout=60 -O "$2" "$1" && return 0
  else
    die "neither curl nor wget is available to download $1"
  fi
  rm -f "$2"; return 1
}

sha256_of() {  # file -> hex
  if have sha256sum; then sha256sum "$1" | cut -d' ' -f1
  elif have shasum; then shasum -a 256 "$1" | cut -d' ' -f1
  elif have python3; then python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  else die "no sha256sum, shasum or python3 to verify a download"; fi
}

uv_target() {
  case "$ARCH" in
    x86_64|amd64) a="x86_64" ;;
    aarch64|arm64) a="aarch64" ;;
    *) echo ""; return 0 ;;
  esac
  case "$OS" in
    Darwin) echo "$a-apple-darwin" ;;
    Linux)
      if [ -n "$(ls /lib/ld-musl-* 2>/dev/null)" ] || (ldd --version 2>&1 | grep -qi musl); then echo "$a-unknown-linux-musl"; else echo "$a-unknown-linux-gnu"; fi ;;
  esac
}

bootstrap_uv() {  # installs the pinned uv into $RUNTIME/uv (user-local) and sets UV
  UV="$RUNTIME/uv/uv"
  if [ -x "$UV" ] && [ "$("$UV" --version 2>/dev/null | awk '{print $2}')" = "$UV_VERSION" ]; then
    say "using the installer's own uv $UV_VERSION at $UV"; return 0
  fi
  target="$(uv_target)"
  [ -n "$target" ] || die "no pinned uv build for $OS/$ARCH. Install uv yourself (https://docs.astral.sh/uv/getting-started/installation/) or pipx, then run this script again."
  want="$(uv_sha256 "$target")"
  [ -n "$want" ] || die "no pinned checksum for uv target $target; this script does not install unverified binaries."
  url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${target}.tar.gz"
  say "downloading uv $UV_VERSION for $target (official release archive, sha256 pinned in this script)"
  say "  from: $url"
  say "  to:   $RUNTIME/uv/   (user-local helper owned by this installer; no sudo, no OS package is changed)"
  tmp="$RUNTIME/uv/.download.$$"
  mkdir -p "$RUNTIME/uv" && rm -rf "$tmp" && mkdir -p "$tmp"
  fetch "$url" "$tmp/uv.tar.gz" || { rm -rf "$tmp"; die "download of uv $UV_VERSION failed (network?). Nothing was installed; run this script again when the network is available, or install uv/pipx yourself."; }
  got="$(sha256_of "$tmp/uv.tar.gz")"
  [ "$got" = "$want" ] || { rm -rf "$tmp"; die "checksum mismatch for uv-${target}.tar.gz: got $got, expected $want. The download was discarded."; }
  (cd "$tmp" && tar -xzf uv.tar.gz) || { rm -rf "$tmp"; die "could not extract uv archive"; }
  [ -f "$tmp/uv-$target/uv" ] || { rm -rf "$tmp"; die "unexpected archive layout for uv-${target}.tar.gz"; }
  chmod 755 "$tmp/uv-$target/uv"
  mv -f "$tmp/uv-$target/uv" "$UV.new" && mv -f "$UV.new" "$UV"
  rm -rf "$tmp"
  "$UV" --version >/dev/null 2>&1 || die "the downloaded uv does not run on this machine ($OS/$ARCH; $("$UV" --version 2>&1 | head -1))"
  say "  verified: sha256 $got; $("$UV" --version)"
}

env_complete() {  # true when $ENV_DIR holds a complete, working install of $SPEC
  [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$SPEC" ] && [ -x "$ENV_DIR/bin/modelsaar" ] && "$ENV_DIR/bin/modelsaar" --version >/dev/null 2>&1
}

ours_link() {  # true when $1 is a symlink into this installer's runtime directory
  [ -L "$1" ] || return 1
  case "$(readlink "$1")" in "$RUNTIME"/*) return 0 ;; *) return 1 ;; esac
}

replace_link() {  # target link — atomically replace the symlink `link` itself (never descend into what it points to)
  # `mv -f tmp link` is NOT suitable: on GNU/Linux and macOS, when `link` is a symlink to a directory the
  # temporary link is moved INSIDE that directory. os.replace renames over the symlink atomically.
  tmp="$2.tmp.$$"
  rm -f "$tmp"
  ln -s "$1" "$tmp" || return 1
  "$ENV_DIR/bin/python" -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$tmp" "$2" || { rm -f "$tmp"; return 1; }
  [ "$(readlink "$2")" = "$1" ]
}

activate_env() {  # point envs/current at $ENV_DIR atomically; keep the previous environment; drop older ones
  prev="$(readlink "$ENVS/current" 2>/dev/null || true)"
  replace_link "$ENV_NAME" "$ENVS/current" || die "could not switch $ENVS/current to $ENV_NAME (the new environment is complete at $ENV_DIR; the previous one is untouched)"
  # The previous complete environment stays (a running service still uses it until restarted, and it is the
  # rollback target); only environments older than that are removed, never config, keys or state.
  for d in "$ENVS"/*; do
    case "$(basename "$d")" in "$ENV_NAME"|"$prev"|current|current.tmp.*) ;; *) [ -d "$d" ] && [ -f "$d/.modelsaar-installed" ] && rm -rf "$d" ;; esac
  done
  [ -n "$prev" ] && [ "$prev" != "$ENV_NAME" ] && [ -d "$ENVS/$prev" ] && say "previous environment kept for the running service and rollback: $ENVS/$prev"
  MS="$ENVS/current/bin/modelsaar"
  # Stable user-level command, never over an unrelated executable.
  mkdir -p "$LAUNCHER_DIR"
  L="$LAUNCHER_DIR/modelsaar"
  if [ ! -e "$L" ] && [ ! -L "$L" ]; then
    ln -s "$MS" "$L" && LAUNCHER_STATE="linked"
  elif [ -L "$L" ] && [ "$(readlink "$L")" = "$MS" ]; then
    LAUNCHER_STATE="linked"
  elif ours_link "$L"; then
    replace_link "$MS" "$L" && LAUNCHER_STATE="linked"
  else
    LAUNCHER_STATE="kept"; say "note: $L already exists and is not ModelSaar's launcher; it was left alone."
  fi
}

install_into_env() {  # $1 = how ("venv" | "bootstrap"); builds $ENV_DIR, does NOT activate it
  if env_complete; then
    say "existing installation of this commit reused: $ENV_DIR"
    ENV_REUSED=1; return 0
  fi
  if [ -d "$ENV_DIR" ]; then
    if [ -f "$MARKER" ]; then say "replacing the environment at $ENV_DIR (it was installed from a different source: $(cat "$MARKER"))"
    else say "removing an incomplete earlier attempt at $ENV_DIR"; fi
    rm -rf "$ENV_DIR"
  fi
  mkdir -p "$ENVS"
  if [ "$1" = "venv" ]; then
    say "creating a virtual environment with $PY at $ENV_DIR"
    "$PY" -m venv "$ENV_DIR" || { rm -rf "$ENV_DIR"; return 1; }
    [ -x "$ENV_DIR/bin/python" ] || { rm -rf "$ENV_DIR"; return 1; }
    "$ENV_DIR/bin/python" -m pip --version >/dev/null 2>&1 || { rm -rf "$ENV_DIR"; return 1; }
    say "installing $SPEC"
    "$ENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check "$SPEC" || { rm -rf "$ENV_DIR"; die "pip install into $ENV_DIR failed (see the message above; usually the network or the package index). Nothing else was changed."; }
  else
    say "creating a virtual environment with uv at $ENV_DIR (uv downloads a Python of its own, 3.10–3.13, into $RUNTIME/python only if no Python 3.10+ is found)"
    UV_PYTHON_INSTALL_DIR="$RUNTIME/python" UV_CACHE_DIR="$RUNTIME/cache" "$UV" venv -q --python ">=3.10,<3.14" "$ENV_DIR" \
      || { rm -rf "$ENV_DIR"; die "uv could not create a virtual environment (see the message above). Nothing else was changed."; }
    say "installing $SPEC"
    UV_PYTHON_INSTALL_DIR="$RUNTIME/python" UV_CACHE_DIR="$RUNTIME/cache" "$UV" pip install -q --python "$ENV_DIR/bin/python" "$SPEC" \
      || { rm -rf "$ENV_DIR"; die "uv pip install into $ENV_DIR failed (see the message above; usually the network or the package index). Nothing else was changed."; }
    rm -rf "$RUNTIME/cache"
  fi
  [ -x "$ENV_DIR/bin/modelsaar" ] && "$ENV_DIR/bin/modelsaar" --version >/dev/null 2>&1 || { rm -rf "$ENV_DIR"; die "the installed environment has no working 'modelsaar' command; it was removed."; }
  printf '%s\n' "$SPEC" > "$MARKER"
}

# ---- 2. install ------------------------------------------------------------------------------------
# Fresh installation or upgrade? An existing configuration means upgrade: init is never run again, the
# configuration, keys, state, backend, listening address and port stay exactly as they are.
if [ -f "$HOME_DIR/config.yaml" ]; then MODE="upgrade"; else MODE="fresh"; fi
CFG_HASH_BEFORE="$(cat "$HOME_DIR/config.yaml" "$HOME_DIR/keys/api_keys" "$HOME_DIR/keys/admin_key" 2>/dev/null | sha256_of /dev/stdin 2>/dev/null || true)"
# One installer at a time per runtime directory: two concurrent upgrades must not race on envs/current.
mkdir -p "$(dirname "$RUNTIME")"
LOCK="$RUNTIME.lock"   # sibling of the runtime directory; removed on exit, so nothing is left behind
if ! mkdir "$LOCK" 2>/dev/null; then
  other="$(cat "$LOCK/pid" 2>/dev/null)"
  if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then die "another installer run (pid $other) is in progress for $RUNTIME; wait for it to finish"; fi
  rm -rf "$LOCK"; mkdir "$LOCK" || die "cannot create $LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
say "mode: $MODE ($([ "$MODE" = upgrade ] && echo "existing configuration at $HOME_DIR/config.yaml is kept; init is not run" || echo "no configuration yet; init will run"))"
METHOD="${MODELSAAR_METHOD:-}"
if [ -z "$METHOD" ]; then
  if have uv; then METHOD="uv"; elif have pipx; then METHOD="pipx"; else METHOD="venv"; fi
fi
LAUNCHER_STATE=""; ENV_REUSED=""; PREV_ENV=""; CFG_YAML=""
case "$METHOD" in
  uv)
    say "installing with your uv (isolated tool environment; Python 3.12 is fetched by uv if needed)"
    uv tool install --force --python 3.12 "$SPEC" || die "uv tool install failed"
    BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
    MS="$BIN_DIR/modelsaar" ;;
  pipx)
    say "installing with your pipx (isolated environment)"
    pipx install --force "$SPEC" || die "pipx install failed"
    BIN_DIR="$HOME/.local/bin"
    MS="$BIN_DIR/modelsaar" ;;
  venv|bootstrap)
    PY=""
    if [ "$METHOD" = "venv" ]; then
      for cand in python3.13 python3.12 python3.11 python3.10 python3; do
        if have "$cand" && py_ok "$cand"; then PY="$(command -v "$cand")"; break; fi
      done
    fi
    if [ -n "$PY" ] && install_into_env venv; then
      METHOD="venv"
    else
      if [ "$METHOD" = "venv" ]; then
        if [ -z "$PY" ]; then
          say "no Python 3.10+ found (python3 is $(python3 --version 2>&1 || echo 'absent')); a pinned uv will provide one"
        else
          say "$PY cannot create a usable virtual environment here (its venv/ensurepip support is missing — on Debian/Ubuntu that is the python3-venv package); a pinned uv will create it instead"
        fi
      fi
      METHOD="bootstrap"
      bootstrap_uv
      install_into_env bootstrap
    fi
    # Validate the replacement BEFORE it becomes current and before any service is touched: it must run and
    # must accept the effective configuration (upgrade) — a replacement that cannot read the config is never activated.
    "$ENV_DIR/bin/modelsaar" --version >/dev/null 2>&1 || die "the new environment's modelsaar does not run; nothing was activated"
    if [ "$MODE" = upgrade ]; then
      for sub in "config validate" "keys ensure"; do
        # shellcheck disable=SC2086
        MODELSAAR_HOME="$HOME_DIR" "$ENV_DIR/bin/modelsaar" $sub >/dev/null 2>"$ENV_DIR/.validate.err" \
          || die "the new revision cannot work with the existing configuration ('modelsaar $sub' failed: $(head -c 300 "$ENV_DIR/.validate.err")); nothing was activated, the current installation is untouched"
      done
      CFG_YAML="$(MODELSAAR_HOME="$HOME_DIR" "$ENV_DIR/bin/modelsaar" config show 2>"$ENV_DIR/.validate.err" || true)"
      printf '%s\n' "$CFG_YAML" | grep -q '^server:' || die "the new revision cannot read the existing configuration ('modelsaar config show' gave no server section: $(head -c 300 "$ENV_DIR/.validate.err")); nothing was activated, the current installation is untouched"
      rm -f "$ENV_DIR/.validate.err"
    fi
    PREV_ENV="$(readlink "$ENVS/current" 2>/dev/null || true)"
    activate_env
    BIN_DIR="$LAUNCHER_DIR" ;;
  *) die "MODELSAAR_METHOD must be uv, pipx, venv or bootstrap" ;;
esac
[ -x "$MS" ] || die "the installed 'modelsaar' command was not found at $MS"
"$MS" --version >/dev/null 2>&1 || die "the installed 'modelsaar' command at $MS does not run"
say "installed: $("$MS" --version) via $METHOD ($MS)"
# Does the caller's shell resolve `modelsaar` to THIS installation? (This script cannot change the parent
# shell's PATH; it only reports.)
RESOLVED="$(command -v modelsaar 2>/dev/null || true)"
if [ -n "$RESOLVED" ] && [ "$(cd "$(dirname "$RESOLVED")" && pwd -P)/$(basename "$RESOLVED")" = "$(cd "$(dirname "$MS")" && pwd -P)/$(basename "$MS")" ]; then
  CMD="modelsaar"; PATH_NOTE=""
elif [ -n "$RESOLVED" ] && [ -L "$RESOLVED" ] && [ "$(readlink "$RESOLVED")" = "$MS" ]; then
  CMD="modelsaar"; PATH_NOTE=""
else
  # Not resolvable as plain `modelsaar` from the caller's shell: print a pasteable command instead.
  if [ "${LAUNCHER_STATE:-}" = "linked" ] && [ "$LAUNCHER_DIR" = "$HOME/.local/bin" ]; then CMD="~/.local/bin/modelsaar"; else CMD="$MS"; fi
  if [ -n "$RESOLVED" ]; then PATH_NOTE="'modelsaar' in your current shell is $RESOLVED, not this installation; use the command shown above ($CMD) or put $BIN_DIR first on your PATH"
  else PATH_NOTE="'modelsaar' is not on your PATH yet; use the command shown above ($CMD), or add $BIN_DIR to your PATH (this script does not edit shell profiles)"; fi
fi

# ---- 3. configure ------------------------------------------------------------------------------------
export MODELSAAR_HOME="$HOME_DIR"
if [ "$MODE" = upgrade ]; then
  say "existing configuration kept: $HOME_DIR/config.yaml (keys and state untouched)"
  "$MS" keys ensure >/dev/null
else
  if [ -n "${MODELSAAR_ENDPOINT:-}" ]; then
    "$MS" init --endpoint "$MODELSAAR_ENDPOINT" --type "${MODELSAAR_TYPE:-ollama}" --port "$PORT" \
      || die "init failed for endpoint $MODELSAAR_ENDPOINT (package installed at $MS; configuration not written)"
  else
    if ! "$MS" init --port "$PORT"; then
      die "no inference server found on the documented loopback ports (Ollama 11434, LM Studio 1234, llama.cpp 8080, vLLM 8000).
The package is installed ($MS); the configuration was not written.
Start your backend (e.g. 'ollama serve' and 'ollama pull <model>') and run this script again, or point it at a server:
  MODELSAAR_ENDPOINT=http://host:port MODELSAAR_TYPE=ollama|openai_compatible sh install.sh"
    fi
  fi
fi
# Effective listening address, read from the configuration through the application itself (never guessed).
[ -n "${CFG_YAML:-}" ] || CFG_YAML="$("$MS" config show 2>/dev/null || true)"
GW_HOST="$(printf '%s\n' "$CFG_YAML" | awk '/^server:/{s=1} s && /^  host:/{print $2; exit}' | tr -d "'\"")"
GW_PORT="$(printf '%s\n' "$CFG_YAML" | awk '/^server:/{s=1} s && /^  port:/{print $2; exit}')"
GW_HOST="${GW_HOST:-127.0.0.1}"; GW_PORT="${GW_PORT:-$PORT}"
case "$GW_HOST" in
  0.0.0.0|"::"|"[::]") CHECK_HOST="127.0.0.1"; GW_URL="http://$GW_HOST:$GW_PORT"; EXPOSURE="all interfaces (server.host=$GW_HOST); reachable from your network as configured" ;;
  127.0.0.1|localhost|"::1") CHECK_HOST="$GW_HOST"; GW_URL="http://$GW_HOST:$GW_PORT"; EXPOSURE="loopback only; see modelsaar.com/privacy to expose it deliberately" ;;
  *) CHECK_HOST="$GW_HOST"; GW_URL="http://$GW_HOST:$GW_PORT"; EXPOSURE="bound to $GW_HOST as configured" ;;
esac
CHECK_URL="http://$CHECK_HOST:$GW_PORT"
CFG_HASH_AFTER="$(cat "$HOME_DIR/config.yaml" "$HOME_DIR/keys/api_keys" "$HOME_DIR/keys/admin_key" 2>/dev/null | sha256_of /dev/stdin 2>/dev/null || true)"
if [ "$MODE" = upgrade ]; then
  [ "$CFG_HASH_BEFORE" = "$CFG_HASH_AFTER" ] && CFG_STATE="preserved (config.yaml and keys byte-identical)" || CFG_STATE="CHANGED — unexpected; inspect $HOME_DIR"
else
  CFG_STATE="created by init ($HOME_DIR/config.yaml, keys mode 600)"
fi

# ---- 4. service -----------------------------------------------------------------------------------------
# A Linux user unit named modelsaar.service is controlled ONLY when it demonstrably belongs to this installation
# (its ExecStart resolves into this installer's runtime directory or to the installed executable) AND it uses this
# configuration (MODELSAAR_HOME / --config, or the default home). Anything else is reported, never restarted.
SVC="modelsaar.service"; SVC_STATE="unsupported"; SVC_REASON=""; SVC_PID=""; RUNNING_ENV=""
svc_prop() { systemctl --user show "$SVC" -p "$1" --value 2>/dev/null; }
is_ours_path() {  # does $1 (an executable path) run THIS installation?
  [ -n "$1" ] || return 1
  rp="$(cd "$(dirname "$1")" 2>/dev/null && pwd -P)/$(basename "$1")"
  case "$1" in "$RUNTIME"/*) return 0 ;; esac
  case "$rp" in "$RUNTIME"/*|"$(cd "$(dirname "$MS")" && pwd -P)/modelsaar") return 0 ;; esac
  [ -L "$1" ] && case "$(readlink "$1")" in "$RUNTIME"/*|"$MS") return 0 ;; esac
  return 1
}
svc_detect() {
  [ "$OS" = Linux ] || { SVC_REASON="service management is only implemented for Linux user units (systemd); on $PLATFORM restart your gateway yourself"; return 0; }
  have systemctl || { SVC_REASON="systemctl not found"; return 0; }
  systemctl --user show-environment >/dev/null 2>&1 || { SVC_REASON="no systemd user manager reachable for this user (systemctl --user)"; return 0; }
  if [ "$(svc_prop LoadState)" != "loaded" ]; then SVC_STATE="none"; return 0; fi
  frag="$(svc_prop FragmentPath)"; execs="$(svc_prop ExecStart)"
  exe="$(printf '%s' "$execs" | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -1)"
  argv="$(printf '%s' "$execs" | sed -n 's/.*argv\[\]=\([^;]*\);.*/\1/p' | head -1)"
  envs_="$(svc_prop Environment)"
  svc_home="$(printf '%s' "$envs_" | tr ' ' '\n' | sed -n 's/^MODELSAAR_HOME=//p' | head -1)"
  cfgarg="$(printf '%s' "$argv" | sed -n 's/.*--config[= ]\([^ ]*\).*/\1/p')"
  [ -n "$cfgarg" ] && svc_home="$(dirname "$cfgarg")"
  svc_home="${svc_home:-$HOME/.modelsaar}"
  if ! is_ours_path "$exe"; then SVC_STATE="foreign"; SVC_REASON="$SVC ($frag) starts '$exe', which is not this installation; not touched"; return 0; fi
  if [ "$(cd "$svc_home" 2>/dev/null && pwd -P)" != "$(cd "$HOME_DIR" && pwd -P)" ]; then SVC_STATE="foreign"; SVC_REASON="$SVC uses configuration $svc_home, not $HOME_DIR; not touched"; return 0; fi
  case "$(svc_prop ActiveState)" in
    active|activating|reloading) SVC_STATE="active" ;;
    failed) SVC_STATE="failed" ;;
    *) SVC_STATE="inactive" ;;
  esac
  SVC_PID="$(svc_prop MainPID)"
}
running_env() {  # which environment does the service's main process execute from? (Linux: mapped files)
  [ -n "$1" ] && [ "$1" != 0 ] && [ -r "/proc/$1/maps" ] || { echo ""; return 0; }
  grep -o "$RUNTIME/envs/[0-9a-f]\{40\}" "/proc/$1/maps" 2>/dev/null | sort -u | head -1
}
healthy() { curl -fsS -m 3 -H 'Accept: application/json' "$1/healthz" 2>/dev/null | grep -q '"service"[[:space:]]*:[[:space:]]*"modelsaar"'; }
wait_ready() {  # url seconds [service]  — bounded; a service that has already failed is not waited for
  i=0
  until healthy "$1"; do
    i=$((i+1)); [ "$i" -gt "$(( $2 * 2 ))" ] && return 1
    if [ -n "${3:-}" ] && [ $(( i % 4 )) -eq 0 ] && [ "$(svc_prop ActiveState)" = failed ]; then return 1; fi
    if [ $(( i % 10 )) -eq 0 ]; then say "Waiting for service… ($(( i / 2 ))s)"; fi
    sleep 0.5
  done
  return 0
}
svc_detect
SERVICE_RESULT=""; ROLLED_BACK=""
case "$SVC_STATE" in
  active)
    if [ -n "$ENV_REUSED" ] && [ "$(running_env "$SVC_PID")" = "$ENV_DIR" ]; then
      RUNNING_ENV="$ENV_DIR"; SERVICE_RESULT="ok"
      say "managed service: $SVC is active (pid $SVC_PID) and already runs this revision; not restarted"
    else
    say "managed service: $SVC is active (pid $SVC_PID) and belongs to this installation; restarting it on the new environment"
    if ! systemctl --user restart "$SVC" 2>"$RUNTIME/.restart.err"; then
      SERVICE_RESULT="restart command failed: $(head -c 200 "$RUNTIME/.restart.err")"
    fi
    rm -f "$RUNTIME/.restart.err"
    if [ -z "$SERVICE_RESULT" ] && ! wait_ready "$CHECK_URL" 60 svc; then
      SERVICE_RESULT="did not become ready after restart ($(svc_prop ActiveState)/$(svc_prop SubState) within 60s)"
    fi
    if [ -z "$SERVICE_RESULT" ]; then
      SVC_PID="$(svc_prop MainPID)"; RUNNING_ENV="$(running_env "$SVC_PID")"
      case "$METHOD" in
        venv|bootstrap)
          if [ "$RUNNING_ENV" = "$ENV_DIR" ]; then SERVICE_RESULT="ok"
          elif [ -z "$RUNNING_ENV" ]; then SERVICE_RESULT="restarted and ready, but its revision could not be read from /proc/$SVC_PID/maps"
          else SERVICE_RESULT="restarted, but it runs $(basename "$RUNNING_ENV") — its ExecStart points at a fixed environment path; point it at $LAUNCHER_DIR/modelsaar or $ENVS/current/bin/modelsaar and restart"; fi ;;
        *) SERVICE_RESULT="ok" ;;
      esac
    fi
    if [ "$SERVICE_RESULT" != "ok" ] && [ -n "$PREV_ENV" ] && [ "$PREV_ENV" != "$ENV_NAME" ] && [ -d "$ENVS/$PREV_ENV" ] && [ "$RUNNING_ENV" != "$ENV_DIR" ]; then
      # The replacement did not come up: restore the previous environment and the running service.
      say "replacement did not start cleanly ($SERVICE_RESULT); restoring the previous environment $PREV_ENV"
      journalctl --user -u "$SVC" -n 20 --no-pager 2>/dev/null | sed 's/^/    journal: /' | tail -n 20
      mv -f "$MARKER" "$ENV_DIR/.modelsaar-failed" 2>/dev/null
      ENV_NAME_SAVE="$ENV_NAME"; ENV_NAME="$PREV_ENV"; ENV_DIR_SAVE="$ENV_DIR"; ENV_DIR="$ENVS/$PREV_ENV"
      replace_link "$PREV_ENV" "$ENVS/current" || true
      ENV_NAME="$ENV_NAME_SAVE"; ENV_DIR="$ENV_DIR_SAVE"
      systemctl --user restart "$SVC" 2>/dev/null || true
      if wait_ready "$CHECK_URL" 60 svc; then ROLLED_BACK="restored $PREV_ENV; $SVC is active again on the previous revision"
      else ROLLED_BACK="restored $PREV_ENV but $SVC is still not ready; see: journalctl --user -u $SVC"; fi
    fi
    fi ;;
  inactive|failed)
    say "managed service: $SVC belongs to this installation but is $SVC_STATE; left as it is (not started)"
    SERVICE_RESULT="$SVC_STATE (not started; start it with: systemctl --user start $SVC)" ;;
  foreign) say "note: $SVC_REASON"; SERVICE_RESULT="not managed by this installer: $SVC_REASON" ;;
  none) SERVICE_RESULT="none (no modelsaar.service user unit)" ;;
  unsupported) SERVICE_RESULT="$SVC_REASON" ;;
esac

# ---- 5. verify ---------------------------------------------------------------------------------------
CHECK_RC=0; ROUTING="not run"
if [ "${MODELSAAR_NO_CHECK:-0}" = "1" ]; then
  ROUTING="skipped (MODELSAAR_NO_CHECK=1)"
elif [ -n "$ROLLED_BACK" ]; then
  ROUTING="skipped (replacement rolled back)"
else
  # Identify what listens at the effective address BEFORE anything is sent to it. Only the ModelSaar health
  # contract (unauthenticated GET /healthz returning JSON with "service":"modelsaar") counts as a gateway;
  # any other listener is a port collision. This is collision detection, not authentication.
  HEALTH="$(curl -sS -m 3 -o - -w '\n%{http_code}' -H 'Accept: application/json' "$CHECK_URL/healthz" 2>/dev/null || true)"
  HEALTH_CODE="$(printf '%s' "$HEALTH" | tail -n 1)"
  HEALTH_BODY="$(printf '%s' "$HEALTH" | sed '$d')"
  STARTED=""
  if [ "$HEALTH_CODE" = "200" ] && printf '%s' "$HEALTH_BODY" | grep -q '"service"[[:space:]]*:[[:space:]]*"modelsaar"'; then
    if [ "$SVC_STATE" = active ] && [ "$SERVICE_RESULT" = ok ]; then
      say "checking the restarted service at $CHECK_URL"
    elif [ "$SVC_STATE" = foreign ] || { [ "$SVC_STATE" = active ] && [ "$SERVICE_RESULT" != ok ]; }; then
      say "a ModelSaar gateway is listening at $CHECK_URL but it was NOT restarted by this run; checking it anyway (it runs the previous code until you restart it)"
    else
      say "a ModelSaar gateway is already listening at $CHECK_URL (identified by its health contract); using it for the check"
    fi
  elif [ -n "$HEALTH_CODE" ] && [ "$HEALTH_CODE" != "000" ]; then
    die "port $GW_PORT is in use by something that is not a ModelSaar gateway (GET $CHECK_URL/healthz answered HTTP $HEALTH_CODE without the ModelSaar health contract). Nothing was sent to it. Choose another port: MODELSAAR_PORT=8585 sh install.sh (new config), or edit server.port in $HOME_DIR/config.yaml"
  elif (command -v nc >/dev/null 2>&1 && nc -z "$CHECK_HOST" "$GW_PORT" 2>/dev/null); then
    die "port $GW_PORT is in use by something that is not a ModelSaar gateway. Choose another port: MODELSAAR_PORT=8585 sh install.sh (new config), or edit server.port in $HOME_DIR/config.yaml"
  else
    say "starting a temporary gateway at $GW_URL for the check …"
    "$MS" serve >"$HOME_DIR/install-check.log" 2>&1 &
    STARTED=$!
    if ! wait_ready "$CHECK_URL" 20; then kill "$STARTED" 2>/dev/null; die "gateway did not start; see $HOME_DIR/install-check.log"; fi
  fi
  say ""
  # `modelsaar test` re-identifies the gateway at the configured address, sends the key only to it, and succeeds
  # only when the response carries ModelSaar routing attribution (request id + deployment) for the `auto` request.
  if "$MS" test --model auto; then
    ROUTING="passed — 'auto' was routed to the deployment shown above (request id printed)"
    say ""; say "verification: OK — 'auto' was routed by ModelSaar to the deployment shown above (request id printed)"
  else
    # The gateway answered its health contract; a failed routed request means the backend/model side is unavailable
    # or no deployment qualified — that is not a broken gateway upgrade and nothing is rolled back.
    ROUTING="FAILED — gateway is up but the routed request did not pass (backend/model unavailable or no eligible deployment; '$CMD doctor' explains); exit code 2"
    CHECK_RC=2
    say ""; say "verification: FAILED — the gateway answered its health contract but the routed request did not pass; this is a backend/model problem, not a broken gateway (nothing is rolled back)"
  fi
  if [ -n "${STARTED:-}" ]; then kill "$STARTED" 2>/dev/null || true; wait "$STARTED" 2>/dev/null || true; say "temporary gateway stopped"; fi
fi
[ -n "$ROLLED_BACK" ] && CHECK_RC=3
case "$SVC_STATE:$SERVICE_RESULT" in active:ok|none:*|unsupported:*|inactive:*|failed:*|foreign:*) ;; *) [ "$CHECK_RC" -eq 0 ] && CHECK_RC=3 ;; esac

# ---- 6. result ---------------------------------------------------------------------------------------
say ""
say "ModelSaar — $MODE $([ "$CHECK_RC" -eq 0 ] && echo complete || echo "finished with issues (exit $CHECK_RC)")"
if [ -n "$ROLLED_BACK" ]; then say "Installed revision:  $REF could not start and is NOT active; $ENVS/current -> $(readlink "$ENVS/current" 2>/dev/null) (previous revision)"
else case "$METHOD" in venv|bootstrap) say "Installed revision:  $REF ($ENVS/current -> $(readlink "$ENVS/current" 2>/dev/null))" ;; *) say "Installed revision:  $REF via $METHOD ($MS)" ;; esac; fi
if [ -n "$RUNNING_ENV" ]; then say "Running revision:    $(basename "$RUNNING_ENV") (service pid $SVC_PID, read from its mapped files)"
elif [ "$SVC_STATE" = active ] && [ "$SERVICE_RESULT" = ok ]; then say "Running revision:    restarted on the freshly installed $METHOD environment (pid $(svc_prop MainPID))"; fi
say "Service:             $SERVICE_RESULT"
[ -n "$ROLLED_BACK" ] && say "Rollback:            $ROLLED_BACK"
say "Endpoint:            $GW_URL/v1   ($EXPOSURE)"
say "Configuration/keys:  $CFG_STATE"
say "Routing check:       $ROUTING"
say ""
say "API key:   head -1 $HOME_DIR/keys/api_keys    (paste the printed msk_… line into your app; model 'auto')"
NEED=""
if [ "$SVC_STATE" = active ] && [ "$SERVICE_RESULT" = ok ]; then
  say "Next:      the gateway is running under $SVC; connect an app: $CMD client-config open-webui | opencode | opencode-v2 | openclaw | hermes"
elif [ "$SVC_STATE" = inactive ] || [ "$SVC_STATE" = failed ]; then
  NEED="start the service when you want it: systemctl --user start $SVC"
elif [ -n "$ROLLED_BACK" ]; then
  NEED="the new revision did not start, so it was not kept active; look at: journalctl --user -u $SVC -n 50, then run this installer again (the previous revision keeps serving meanwhile)"
elif [ "$SVC_STATE" = foreign ] || { [ "$SVC_STATE" = active ] && [ "$SERVICE_RESULT" != ok ]; }; then
  NEED="restart your gateway yourself so it runs the new revision ($SERVICE_RESULT)"
else
  say "Next:      run the gateway:  $CMD serve   (keep it running; examples/ has launchd and systemd units)"
  say "           check it:        $CMD test     (in another terminal)"
  say "           connect an app:  $CMD client-config open-webui | opencode | opencode-v2 | openclaw | hermes"
fi
[ "$CHECK_RC" -eq 2 ] && NEED="${NEED:+$NEED; }fix the backend/model side, then: $CMD test"
[ -n "$NEED" ] && say "Still required:      $NEED"
case "$METHOD" in
  uv)   say "Uninstall: $CMD uninstall; then: uv tool uninstall modelsaar" ;;
  pipx) say "Uninstall: $CMD uninstall; then: pipx uninstall modelsaar" ;;
  *)    say "Uninstall: $CMD uninstall; then rm -rf $RUNTIME$([ "$LAUNCHER_STATE" = linked ] && echo " and rm $LAUNCHER_DIR/modelsaar")" ;;
esac
[ -n "${PATH_NOTE:-}" ] && say "note: $PATH_NOTE"
exit "$CHECK_RC"
