# Progress and decision log

Compact state so another session can continue without repeating finished work.

## State (2026-10-11, hardening pass)

* Branch `hardening/review-2026-10-11` (base `main` = `1122e1f`, the reviewed commit). Eleven commits;
  **156 passed, 4 skipped** (`python -m pytest`, CPython 3.13.16, Linux; the 4 skips are `code_exec`
  sandbox tests: no bubblewrap/`sandbox-exec`/Docker daemon in that container — they run on macOS and on
  CI's Ubuntu once bubblewrap is present); `ruff check src tests` clean.
* Not done in this pass (per the task's authorization): no push, no tag, no PyPI/GHCR publication, no change
  to any live service. The branch is synced to the owner's Mac (`Model_Router/modelsaar`, checkout at
  `0f8af84`) and a live verification (`run_live_verify.command`) was started there; see
  docs/verification-report.md for what it produced.

### Finding → fix → regression (review of commit 1122e1f)

The reviewer's 18 grouped findings (F01–F18) are reconciled with the eight workstreams below in
[docs/review-2026-10-11-findings.md](review-2026-10-11-findings.md) (disposition, implementation, regression
test, execution evidence; `scripts/reproduce_review_baseline.sh` shows 26/28 regression tests failing at `1122e1f`: 22 on the behavioural assertion, 4 on a field or symbol the fix introduced; 2 positive controls pass — `docs/live-runs/2026-10-11-baseline/`).

Each regression test fails against 1122e1f (22 for the observed defect, 4 on a field/symbol the fix introduced) except the two positive controls, and all 28 pass on the branch
(`tests/test_hardening_2026_10_11.py` unless noted; run `python -m pytest tests/test_hardening_2026_10_11.py -q`).

| # | finding (confirmed at 1122e1f) | fix (files) | regression test |
|---|---|---|---|
| 1a | `_exact_counts` ran before policy filtering and POSTed the whole prompt to every deployment with `/tokenize`, incl. remote ones under `local_only` | two-pass eligibility: estimates first; tokenizer counts only for deployments that passed every non-context filter, under one deadline (`token_estimate.exact_count_deadline_s`), labelled `tokenize:<backend>+template-estimate`; `reasoning_content`/`response_format` included in the counted text (`routing/router.py`, `routing/eligibility.py`) | `test_local_only_sends_no_message_text_to_remote_tokenizer`, `test_exact_counts_only_for_policy_allowed_and_labelled_as_estimate` |
| 1b | classifier could be remote under `allow_remote` without a separate opt-in | local required unless `routing.classifier.allow_remote` **and** `security.locality_mode=allow_remote`; decision names the reason (`config.py`, `routing/router.py`) | `test_classifier_requires_local_deployment_under_local_only` |
| 1c | `audio_url`/`video_url`/`file` parts flattened and forwarded | typed content parts; unknown types/keys → `400 unsupported_content_type` before any dispatch (`protocol/openai.py`) | `test_unsupported_content_part_types_rejected_before_any_dispatch` |
| 2a | tool-result turn / pinned session replayed on another candidate after a 500 | `Decision.failover_allowed`/`failover_note`; no pre-commit failover for tool round trips, reasoning continuation or pinned sessions (`routing/router.py`, `server.py`) | `test_no_failover_for_tool_result_turn`, `test_no_failover_for_pinned_session` |
| 2b | timeout released the slot while the backend kept computing (classifier too) | `AdapterError(kind="timeout")` → `reservation.mark_uncertain()`; streaming read timeouts typed as timeout; classifier timeout holds its slot (`server.py`, `adapters/base.py`, `routing/classifier.py`, `routing/router.py`) | `test_timeout_holds_slot_uncertain_then_recovers` |
| 2c | HTTP 200 headers reset the circuit; 4 truncated streams left failures=1 | success recorded only after a validated non-stream envelope or a completed stream (`server.py`) | `test_circuit_opens_on_truncated_streams` |
| 2d | `response_model_field=deployment` named the failed deployment after failover | attribution computed per attempt (`server.py`) | `test_response_model_follows_failover_target` |
| 2e | upstream 200 HTML → downstream 200 with error body, `outcome=ok`, session pinned | envelope validation (`choices[0].message`) and `text/event-stream` check pre-commit → `502 upstream_bad_response`, no pin, no circuit success (`server.py`) | `test_html_200_is_a_typed_502_and_never_pins` |
| 3a | `memory_gb=1` dispatched a 20.7 GB deployment | pool memory budget as a hard admission check: resident weights + distinct reserved deployments + candidate (+ classifier) + `memory_margin_gb` ≤ `memory_gb`; weights-only estimates with provenance; `unknown_memory_policy allow/reject` labelled in the decision; check runs atomically with the pool slot; `/admin/status` shows reserved GB (`routing/admission.py`, `config.py`, `routing/router.py`) | `test_pool_memory_budget_is_enforced_before_dispatch`, `test_pool_memory_budget_counts_distinct_reservations_and_unknown_policy`, `test_unknown_memory_estimate_policy` |
| 3b | `modelsaar probe` ran inference through a separate Router next to a busy gateway | `POST /admin/probe` runs probes under the gateway's admission; the CLI uses it while a gateway listens, refuses direct probing next to a listener unless `--allow-concurrent`, and offline probes reserve through their own admission; live eval refuses to start next to a listener unless `--allow-concurrent` (`server.py`, `cli.py`, `evaluation/harness.py`) | `test_admin_probe_runs_under_gateway_admission`, `test_cli_probe_coordinates_through_running_gateway` |
| 4 | one alias interchanged two different models of equal dimensions; 4-d output accepted under an 8-d contract; prefix/normalized unenforced | deployment identity (Ollama digest or declared `backends[].models[].identity`); alias members must share the effective identity (declared → recorded on first use → first member); unknown identity is never a replica; changed identity needs `embeddings[].identity` after re-indexing; request `dimensions`/`encoding_format` that change the space → `400 unsupported_contract_option`; output count/indices/dims/finite/unit-norm validated → `502 embedding_contract_violation`; non-empty prefixes rejected at load (`registry.py`, adapters, `routing/router.py`, `server.py`, `config.py`) | `test_alias_never_interchanges_distinct_models_with_equal_dimensions`, `test_known_identical_replicas_share_an_alias`, `test_unknown_identity_is_not_a_verified_replica`, `test_wrong_output_shape_is_a_contract_error`, `test_request_level_contract_changes_rejected` |
| 5 | endpoint URL not in the fingerprint: a replacement server inherited a stored tools probe | fingerprint = backend, **endpoint**, model, digest, **identity**, runtime(+version), template, quant, pool; unknown inputs visible (`fingerprint_inputs`); load/unload still not an identity change; state DB evidence scheme 2 (scheme-1 rows kept, never loaded, reported by `doctor`); measurements carry `conditions` (`registry.py`, adapters, `store.py`, `probes.py`, `evaluation/harness.py`, `doctor.py`) | `test_endpoint_change_invalidates_stored_probe`, `test_load_unload_keeps_evidence`, `test_evidence_scheme_versioning_invalidates_old_rows` |
| 6 | evaluator: lenient scorers, host code execution, unvalidated classifier output, no resume | sandbox-or-skip `code_exec` (bubblewrap / sandbox-exec / Docker, limits; no unsandboxed path), strict `number`/`tool_call`/`code_exec` scorers, schema-validated classifier output, per-task checkpoint + `--checkpoint/--resume`, dataset/scorer revision in conditions (`evaluation/*`, `routing/classifier.py`) | `tests/test_evaluation.py`, `tests/test_classifier_schema.py` (69 tests) |
| 7 | `client-config --apply` turned a 0600 file into 0644; uninstall deleted arbitrary files under `keys/`/`state/`; container exited for missing keys; `init --profile fast` left `auto` on quality | mode-preserving apply with private temp files and unique backups; uninstall removes only owned files, refuses symlinked boundaries, leaves the rest; `modelsaar keys ensure` (idempotent) + container `CMD`; `scripts/compose-smoke.sh` in CI; `init --profile` sets `aliases.auto.profile` (`clientconfig/__init__.py`, `cli.py`, `Dockerfile`, `.github/workflows/ci.yml`) | `test_apply_patch_preserves_mode_private_tmp_unique_backups`, `test_uninstall_removes_only_owned_files_and_refuses_symlinks`, `test_keys_ensure_is_idempotent_and_serve_points_to_it`, `test_init_profile_applies_to_auto_alias`; `tests/test_review_regressions.py::test_uninstall_preserves_foreign_files` (updated to the refined behaviour) |
| 8 | `eval-live.json` absent from the tree (`.gitignore` matched `eval-*.json` at any depth); `30-eval-live.txt` is an interrupted run | `/eval-*.json`; both artefacts tracked; README of the run labels the interrupted log; `scripts/live_verify.sh` (resumable, redacting) + `scripts/live_client_checks.py` (wire-level client checks) + `run_live_verify.command` on the Mac | n/a (artefacts); dry run of the script against the fake backend documented in the verification report |

Deliberate non-changes: no catalogue expansion, no new API families beyond `POST /admin/probe` and
`modelsaar keys ensure`, no refactors outside the findings.

### Exact commands used

```
python -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/ruff check src tests
.venv/bin/python -m pytest                       # 156 passed, 4 skipped (sandbox), 70 s
scripts/install-check.sh                        # wheel install, loopback default, 0600 keys, scheme-1 DB migration: PASS
scripts/compose-smoke.sh                        # NOT RUN here (no Docker daemon); runs in CI job `container`
scripts/live_verify.sh http://127.0.0.1:23111 small:1b big:27b   # dry run against the fake backend: all steps exit 0, resume works
```

## Next actions

1. Read `Model_Router/live-verify-0f8af84/` on the Mac when `live-verify-DONE` appears; fold the numbers into
   docs/verification-report.md (do not touch the 2026-10-11 subset numbers; they stay labelled historical).
2. If the owner wants it on GitHub: push the branch, open a PR, let CI (incl. the new compose smoke) run,
   then merge. Tagging/PyPI/GHCR remain separate decisions.
3. Real clients (Open WebUI, OpenClaw, OpenCode, Hermes) are still NOT RUN unless installed on the Mac
   (`50-real-clients.txt` in the run folder says which); commands are in docs/verification-report.md.

## Decision log

| date | decision | why |
|---|---|---|
| 2026-10-11 | Names: ModelSaar / `modelsaar` (replacing `local-model-router` / `lmr`) | owner's context.md |
| 2026-10-11 | Build small purpose-built gateway; do not extend LiteLLM / vLLM-SR / RouteLLM | ADR-001; footprint, local operation, capability-aware routing, licence boundaries |
| 2026-10-11 | Python, Starlette+uvicorn+httpx+pydantic+PyYAML only; SQLite via stdlib | five deps; direct control of streaming/disconnects; contributor accessibility |
| 2026-10-11 | Forward Ollama inference through its OpenAI-compatible layer; discover via native API | preserves Ollama's own tool semantics; native API has the truthful metadata (`/api/show` capabilities, `/api/ps`, `remote_model`) |
| 2026-10-11 | `tool_choice=required/named`, `logit_bias`, `n`, `logprobs`, remote image URLs → ineligible/rejected on Ollama path | documented Ollama limits (docs.ollama.com, 2026-10-11); never silently altered |
| 2026-10-11 | Unknown capability or unknown context length ⇒ not eligible | spec: treat unknown conservatively; review finding 1 |
| 2026-10-11 | Served Ollama context assumed 4096 unless Modelfile/ps/override | Ollama exposes no served value for unloaded models; doctor warns |
| 2026-10-11 | Response `model` field = requested alias by default; deployment in `X-ModelSaar-Deployment` | clients that validate ids; diagnostics stay out of content |
| 2026-10-11 | Failover only pre-commit, max 1 attempt, same candidate list; stream truncation without finish_reason reported as error | spec §10; review finding 4 |
| 2026-10-11 | Session affinity pinned after successful dispatch; tool round trips keyed by the last assistant turn's ids only | review findings 3 and 21 |
| 2026-10-11 | Uncalibrated prior = 0.5 + 0.05·log10(1+params_B), capped 0.75, labelled; ties (±0.03 priors / ±unc/2 measured) resolve to lower overhead | spec: prefer lower overhead when effectively tied; size is a labelled hypothesis only |
| 2026-10-11 | Catalogue supplies priors/tags/roles/notes only; never served context or verified capabilities | separate claims from probes and measurements |
| 2026-10-11 | Decision models (clef, nimble, tev1, laya), guardian, OCR → roles that never receive chat | spec §11 |
| 2026-10-11 | Mistral Large 4 = announced weights; tev1 licence unresolved → disabled in catalogue | primary sources 2026-10-11 |
| 2026-10-11 | Tokenizer counts only after policy filtering, only for policy-allowed deployments, one deadline, labelled as partly estimated | hardening finding 1; privacy before payload operations |
| 2026-10-11 | No failover inside a tool round trip, with reasoning continuation, or on a pinned session | hardening finding 2a; continuity beats availability, the client decides |
| 2026-10-11 | Timeouts hold capacity as uncertain; success = validated completion only | hardening finding 2b/2c |
| 2026-10-12 | Uncertainty carried through streams, probes and embeddings; assumed residency counted until observed; embedding identity anchored before dispatch; SSE completion requires valid chunks; evaluator completion evidence from a nonce-keyed record; checkpoint identity; sandbox input allowlists; listener identification before any key is sent | second independent review R1–R8 (`tests/independent_review_2026_10_11/`) |
| 2026-10-11 | Pool `memory_gb` is a hard admission constraint on weights-only estimates + margin; unknown estimates follow an explicit policy; no OOM-prevention claim | hardening finding 3a |
| 2026-10-11 | Online probes go through `POST /admin/probe`; direct probing/eval next to a listening gateway needs `--allow-concurrent` | hardening finding 3b |
| 2026-10-11 | Embedding alias = one verified identity; name match is not identity; changed identity needs an explicit re-index decision | hardening finding 4 |
| 2026-10-11 | Fingerprint includes endpoint + identity; evidence scheme versioned (2); old rows kept but unused | hardening finding 5 |
| 2026-10-11 | Evaluation code execution is sandbox-or-skip, never host execution | hardening finding 6; owner constraint |
| 2026-10-11 | Uninstall removes only owned files; container bootstraps keys with `keys ensure` | hardening finding 7 |
| 2026-10-11 | No hot config reload in 0.1 (restart) | simplicity; docs corrected |
| 2026-10-11 | Evaluation: no LLM judge; executable/exact scoring; rules baseline is given the gold label (disclosed) | spec §14 |

## Research artefacts

docs/research/: foundations (build-vs-adapt), clients (four client configs), catalogue parts 1–2,
adversarial review — all dated 2026-10-11 with URLs.
