# Baseline reproduction — regression tests run against `1122e1f` (2026-10-11)

`reproduce-1122e1f.txt` is the output of `scripts/reproduce_review_baseline.sh` (cloud container, CPython
3.13.16): the 28 tests of `tests/test_hardening_2026_10_11.py` as of `80276bb` run against a worktree of
`1122e1f2b5006003f8832598c81f658b8945c112`, with only the branch's `tests/conftest.py` and
`src/modelsaar/testing/fakebackend.py` copied in (test hooks; no gateway code). Result: **26 failed,
2 passed**. Every line carries the test id and the message of the assertion or exception that ended it.

| class | count | tests | meaning |
|---|---|---|---|
| behavioural assertion failure (the reviewed defect) | 22 | all FAILED lines whose message is `AssertionError`/`assert …` — e.g. `remote backend received message text under local_only`, `assert 200 == 422`, `mode weakened`, `assert 'quality' == 'fast'`, `Not Found` (no `/admin/probe`) | the baseline exhibits the defect the test guards against |
| fails on a config field or API the fix introduced | 4 | `test_pool_memory_budget_counts_distinct_reservations_and_unknown_policy`, `test_unknown_memory_estimate_policy` (pydantic rejects `memory_margin_gb` / `unknown_memory_policy`), `test_unknown_identity_is_not_a_verified_replica` (rejects `identity`), `test_evidence_scheme_versioning_invalidates_old_rows` (`EVIDENCE_SCHEME` does not exist) | the test cannot be expressed at the baseline; its behavioural counterpart is the sibling test that fails on the assertion (`…is_enforced_before_dispatch`, `…alias_never_interchanges…`, `…endpoint_change_invalidates_stored_probe`) |
| positive control (expected behaviour already present) | 2 | `test_known_identical_replicas_share_an_alias`, `test_load_unload_keeps_evidence` | behaviour the fixes had to preserve |

No collection, import-of-test-module, missing-dependency or environment errors occurred (pytest reported
`26 failed, 2 passed`, no `ERROR`). The same 28 tests pass on the hardening branch (cloud: part of 157
passed; Mac: see `../2026-10-11-mac-tests/`).
