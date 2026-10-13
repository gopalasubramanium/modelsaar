# Alpha closure pass 2026-10-12 — transcripts

Author-executed in the cloud container (Linux x86_64, CPython 3.13.16). The reviewer's own executions
are in `ModelSaar_Correction_Review_2026-10-12`, not here. Scratch paths are replaced by `<scratch>`.

| file | result |
|---|---|
| `closure-tests-before-5cb7443.txt` | the review's 12 closure cases at exactly `5cb7443` (fresh venv): **6 failed, 6 passed** — the same ids as the review |
| `pytest-no-sandbox.txt` | final hardening head (first line), `pytest -m "not live"`: **202 passed, 6 skipped** (the 6 sandbox tests) |
| `pytest-with-bwrap.txt` | same with bubblewrap 0.9 on PATH: **208 passed, 0 skipped** |
| `reviewer-tests.txt` | `tests/independent_review_2026_10_11` + `_12`: **29 passed** (17 + 12) |
| `ruff.txt` | `ruff check src tests`: clean |
| `eval-sim.txt` | `modelsaar eval --mode simulated --limit 12` under scorer `2026.10.12-3`: runs end to end |
| `real-install-routed-request.txt` | **real `pip install git+…@<pinned commit>` into a fresh venv** (local clone as the source; the repository is not public yet), `modelsaar init` against the fixture backend, `modelsaar serve`, `modelsaar test --model auto` → `routed: 'auto' -> ollama/small:1b` with a request id, exit 0. The intended-environment run (Mac → GX10 Ollama) is an owner step. |

Not run: macOS `sandbox-exec` (disabled in the alpha pending verification; `launcher/run_mac_tests.command`);
real GX10 inference under the corrected code; real client UI; live publication, DNS, TLS.
