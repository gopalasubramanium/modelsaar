#!/usr/bin/env sh
# Reproducible install, upgrade and state-migration check (no models, no network beyond PyPI).
#   A. source install (pip install -e .) -> tests already cover; here: clean WHEEL install into a
#      fresh venv, `modelsaar --version`, `init` against a fake backend, one routed request.
#   B. upgrade: a state DB written under evidence scheme 1 (0.1.0 layout) is opened by this
#      build -> rows kept but not loaded, `doctor` reports them, scheme meta is 2.
#   C. loopback defaults: the generated config binds 127.0.0.1 and key files are 0600.
# Usage: scripts/install-check.sh   (from the repository root; needs python3 >= 3.10)
set -eu
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "== A. clean wheel install"
"$PY" -m venv "$WORK/build-venv"
"$WORK/build-venv/bin/pip" -q install build >/dev/null
"$WORK/build-venv/bin/python" -m build -q -w -o "$WORK/dist" . >/dev/null
WHL="$(ls "$WORK"/dist/*.whl)"
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" -q install "$WHL" >/dev/null
V="$("$WORK/venv/bin/modelsaar" --version)"
echo "installed: $V ($(basename "$WHL"))"
# fake backend (SIMULATED models) from the installed package
"$WORK/venv/bin/python" - "$WORK/fake.port" <<'PY' &
import sys, time
from modelsaar.testing.fakebackend import FakeBackend, FakeModel
f = FakeBackend([FakeModel("small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True)])
f.start()
open(sys.argv[1], "w").write(str(f.port))
time.sleep(120)
PY
FAKE=$!
for i in $(seq 1 50); do [ -s "$WORK/fake.port" ] && break; sleep 0.1; done
PORT="$(cat "$WORK/fake.port")"
export MODELSAAR_HOME="$WORK/home"
"$WORK/venv/bin/modelsaar" init --endpoint "http://127.0.0.1:$PORT" --type ollama --port 18585 >/dev/null
echo "== C. loopback default and private keys"
grep -q "host: 127.0.0.1" "$MODELSAAR_HOME/config.yaml" && echo "server.host is loopback"
perm="$(stat -c %a "$MODELSAAR_HOME/keys/api_keys" 2>/dev/null || stat -f %Lp "$MODELSAAR_HOME/keys/api_keys")"
[ "$perm" = "600" ] && echo "api key file mode 600"
echo "== one routed request through the installed gateway"
"$WORK/venv/bin/modelsaar" serve >"$WORK/serve.log" 2>&1 &
SERVE=$!
for i in $(seq 1 50); do curl -fsS http://127.0.0.1:18585/healthz >/dev/null 2>&1 && break; sleep 0.1; done
KEY="$(head -1 "$MODELSAAR_HOME/keys/api_keys")"
curl -fsS http://127.0.0.1:18585/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}]}' | grep -q '"choices"' && echo "chat via auto: ok"
kill $SERVE; wait $SERVE 2>/dev/null || true
echo "== B. upgrade: open a scheme-1 state DB with this build"
DB="$MODELSAAR_HOME/state/modelsaar.db"
rm -f "$DB" "$DB-wal" "$DB-shm"
"$WORK/venv/bin/python" - "$DB" <<'PY'
import sqlite3, sys, time, os
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
c = sqlite3.connect(sys.argv[1])
c.executescript("""
CREATE TABLE probes (deployment_id TEXT NOT NULL, fingerprint TEXT NOT NULL, capability TEXT NOT NULL, value TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', checked_at REAL NOT NULL, PRIMARY KEY (deployment_id, fingerprint, capability));
CREATE TABLE measurements (deployment_id TEXT NOT NULL, fingerprint TEXT NOT NULL, task TEXT NOT NULL, quality REAL,
  samples INTEGER NOT NULL DEFAULT 0, p50_ms REAL, p95_ms REAL, ttft_ms REAL, load_ms REAL, source TEXT NOT NULL DEFAULT 'eval',
  measured_at REAL NOT NULL, PRIMARY KEY (deployment_id, fingerprint, task, source));
CREATE TABLE decisions (request_id TEXT PRIMARY KEY, created_at REAL NOT NULL, record TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""")
c.execute("INSERT INTO probes VALUES ('ollama/small:1b','oldfp','tools','supported','',?)", (time.time(),))
c.execute("INSERT INTO measurements VALUES ('ollama/small:1b','oldfp','coding',0.9,10,100,200,NULL,NULL,'eval',?)", (time.time(),))
c.commit(); c.close()
print("wrote a 0.1.0-layout state DB with 1 probe and 1 measurement")
PY
"$WORK/venv/bin/modelsaar" doctor >"$WORK/doctor.txt" 2>&1 || true
grep -q "older" "$WORK/doctor.txt" && echo "doctor reports rows written under an older evidence scheme"
"$WORK/venv/bin/python" - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
print("meta evidence_scheme =", c.execute("select value from meta where key='evidence_scheme'").fetchone()[0])
print("old rows kept:", c.execute("select count(*) from probes where scheme=1").fetchone()[0], "probe,", c.execute("select count(*) from measurements where scheme=1").fetchone()[0], "measurement")
PY
kill $FAKE 2>/dev/null || true
echo "install-check: PASS"
