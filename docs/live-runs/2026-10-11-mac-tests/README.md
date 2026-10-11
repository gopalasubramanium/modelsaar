# Full test suite on the owner's Mac (sandbox-exec isolation backend)

| file | revision | result | notes |
|---|---|---|---|
| `mac-tests-80276bb.txt` | `80276bbeb9e6cbe3297c6b32bd73df48d389b238` = the hardening branch head and the commit the public installer pins | **161 passed, 0 skipped**, exit 0, 48 s | `python -m pytest -rs -v --durations=5` (pyproject adds `-q`, so the log shows dots; the four isolation tests are among the 42 in `tests/test_evaluation.py` and `test_sandbox_timeout_fails_cleanly` appears in the slowest-5 list at 2.0 s, which only happens when it executes). Backend line: `isolation backends: sandbox-exec=/usr/bin/sandbox-exec bwrap=missing docker=missing`. macOS Darwin 27.0 arm64, CPython 3.12.15. |
| `mac-tests-0172760.txt` | `01727604726077fe70e7acef398427149e45c4c1` (earlier head) | 160 passed, 0 skipped | superseded; kept for the record |

Commits between `0172760` and `80276bb`: `0881e20`, `86a6393` (docs, scripts), `47b485d` (CI workflow),
**`91f9e6c` (executable: `modelsaar test` first-run message + one new test)**, `c963914`, `80276bb` (docs).
Because `91f9e6c` changed executable behaviour, the suite was rerun on `80276bb`; the count rose from 160
to 161 by that one test.

Named isolation tests that executed under `sandbox-exec` (skipped in the cloud container):
`tests/test_evaluation.py::test_sandbox_blocks_writes_outside_work`, `::test_sandbox_blocks_network`,
`::test_sandbox_reference_solution_passes`, `::test_sandbox_timeout_fails_cleanly`.
