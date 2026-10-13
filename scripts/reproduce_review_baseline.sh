#!/usr/bin/env bash
# DIAGNOSTIC (not a regression test): runs the hardening regression tests against the reviewed
# baseline commit to show which ones fail there, i.e. which defects they reproduce.
#
# The regression tests assert the CORRECTED behaviour. To run them against 1122e1f they need two
# adaptations that do not change their behavioural assertions:
#   * the fake backend gained test hooks (tokenize_requests recorder, `stall`/streaming `bad_json`
#     behaviours, `normalize_embeddings` switch) -> the branch's fakebackend.py is copied in;
#   * conftest is shared -> the branch's conftest.py is copied in.
# Everything else (router, server, admission, store, cli, ...) is the baseline's own code.
#
# Usage: scripts/reproduce_review_baseline.sh [BASELINE_COMMIT]   (default 1122e1f)
# Output: a per-test PASS/FAIL table for the baseline; exits 0 regardless.
set -u
BASE="${1:-1122e1f}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
W="$(mktemp -d)/baseline"
git -C "$ROOT" worktree add -q "$W" "$BASE" || { echo "cannot create worktree at $BASE"; exit 2; }
trap 'git -C "$ROOT" worktree remove --force "$W" >/dev/null 2>&1' EXIT
cp "$ROOT/tests/test_hardening_2026_10_11.py" "$W/tests/"
cp "$ROOT/tests/conftest.py" "$W/tests/"
cp "$ROOT/src/modelsaar/testing/fakebackend.py" "$W/src/modelsaar/testing/"
echo "baseline: $(git -C "$W" rev-parse HEAD)"
echo "tests:    tests/test_hardening_2026_10_11.py from $(git -C "$ROOT" rev-parse --short HEAD)"
cd "$W" && PYTHONPATH="$W/src" "$PY" -m pytest -p no:cacheprovider -o addopts="" -v --tb=line tests/test_hardening_2026_10_11.py 2>/dev/null > "$W/run.txt"
# One line per test: outcome, test id, and the failing assertion message (from --tb=line, in run order),
# so a behavioural FAILED can be told apart from a collection/import/environment ERROR.
"$PY" - "$W/run.txt" <<'PY'
import re, sys
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
outcomes = [(m.group(1), m.group(2)) for m in (re.match(r"^(tests/\S+::\w+) (PASSED|FAILED|ERROR)", l) for l in lines) if m]
reasons = [re.sub(r"^.*?test_hardening_2026_10_11\.py:(\d+): ", r"line \1: ", l) for l in lines if re.match(r"^/.*test_hardening_2026_10_11\.py:\d+: ", l)]
it = iter(reasons)
for test, out in outcomes:
    why = next(it, "?") if out != "PASSED" else "expected behaviour already present at the baseline (positive control)"
    print(f"{out:6s} {test.split('::')[1]:70s} | {why[:120]}")
print()
print([l for l in lines if re.search(r"\d+ (passed|failed)", l)][-1])
PY
echo "(FAILED/ERROR at the baseline = the defect the test guards against was present; PASSED = the test's"
echo " scenario already behaved correctly at the baseline or depends on a new test hook only)"
