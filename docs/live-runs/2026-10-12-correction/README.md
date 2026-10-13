# Correction pass 2026-10-12 — reproduction and verification transcripts

Evidence for the second independent review (pack `ModelSaar_Independent_Review_2026-10-11`, findings
R1–R8 of hardening `80276bb`). Everything here was executed by the author in the cloud container
(Linux x86_64, CPython 3.13.16) unless a file says otherwise; the reviewer's own executions are in the
review pack, not here. Scratch paths are replaced by `<scratch>`/`<archive>`; no credential appears
(the only "Bearer" value is the reviewer's invented fixture sentinel, labelled as such in its name).

## `before/` — reproduced at the exact baseline before any change

| file | what |
|---|---|
| `review-tests-80276bb.txt` | the reviewer's two test files run against an isolated worktree at `80276bbeb9e6cbe3297c6b32bd73df48d389b238` with a fresh venv: **11 failed, 6 passed** — the same ids as the review |
| `launcher_results.json`, `skip_domain.txt`, `build_failure.txt`, `wrong_origin.txt` | `reproduce_launcher.py` (only its path constants adapted; the stub `gh` also placed where `gh_run.command` prepends `~/.local/bin`) against the delivered launcher: positive resume PASS; skip-domain, build-query-failure, origin-prefix DEFECT REPRODUCED |
| `installer_results.json`, `installer_foreign_healthz.txt` | `reproduce_installer.py` against the delivered `install.sh` + the `80276bb` CLI: foreign `/healthz` accepted and the fixture key sent; `init && serve` exit 1 |
| `publication_tree_results.json` | `reproduce_publication_tree.py`: untracked file published with BUILD-INFO claiming the clean commit; rollback control PASS |
| `address-guard-840b068.txt` | `check_site.py` at website `840b068`: 192.168/16 and 172.16/12 accepted (misses), CGNAT and 10/8 rejected |
| `archive-ee4f5f31-vs-1d2e9bc6.txt` | the two archives this session delivered on 2026-10-11 differ only in README/MANIFEST/checksum text and one `gh_lib.sh` wording line (see the handoff report) |

## `final-head/` — executed at the final hardening head (first line of each file names the revision; clean worktree, fresh venv)

| file | result |
|---|---|
| `pytest-no-sandbox.txt` | `pytest -m "not live"`: **190 passed, 6 skipped** (the 6 sandbox tests; skip reasons listed) |
| `pytest-with-bwrap.txt` | same with bubblewrap 0.9 on PATH: **196 passed, 0 skipped** — sandbox tests executed, incl. the synthetic-host-file read test and the forged-marker test |
| `reviewer-tests.txt` | `tests/independent_review_2026_10_11/`: **17 passed** |
| `ruff.txt` | `ruff check src tests`: clean |
| `eval-sim.txt` | `modelsaar eval --mode simulated --limit 12` under scorer `2026.10.12-3`: runs end to end (numbers not quoted) |

## `address-guard-cases.txt` — corrected guard at the website head

CGNAT, 10/8, 172.16/12 (both ends), 192.168/16 and 169.254/16 rejected; 172.32/8, 8.8.8.8 and the
CGNAT boundary addresses 100.63.x / 100.128.x accepted; `msk_…` key literals rejected (separate run).

## Not run

* macOS `sandbox-exec` at this revision (the Mac was not reachable from the session) — the rewritten
  deny-by-default profile is untested on macOS; see the verification report for the owner step.
* Real GX10 inference under the corrected code; real-model embeddings; real client UI.

## Also in the repository

* `docs/live-runs/2026-10-12-installer-scenarios/` — real installer + real CLI, 10/10 scenarios.
* `tests/independent_review_2026_10_11/` — the reviewer's tests, byte-for-byte, now part of the suite.
* Launcher mock outcomes (negative / pending / success / exact-destination) — in the review archive
  (`reports/launcher-mock-outcomes.txt`), because the launcher itself is shipped outside the repository.
