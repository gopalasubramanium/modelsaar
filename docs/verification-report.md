# Verification report — ModelSaar 0.1.0 (build of 2026-10-11)

This report lists what was actually executed, where, with what outcome. Anything not executed is
marked **NOT RUN** with the exact procedure to run it. Nothing below is a mocked result presented as
real; simulated runs are labelled as such.

## Environments used

| environment | details |
|---|---|
| Build/test container (cloud) | Linux x86_64, CPython 3.13.16, starlette 1.7.0, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.14.0, PyYAML 6.0.3, pytest 9.1.1. No GPU. Network: PyPI reachable; Hugging Face, Ollama registry and Docker daemon **not** available. |
| Independent review venv | CPython 3.10.20 (uv), same dependency versions — full test suite passed (reviewer's run). |
| Owner's Linux VM bridge | aarch64, CPython 3.10.12: `pytest` → **61 passed** at that commit (64 at HEAD); `modelsaar eval --mode simulated --limit 10` ran (Python 3.10/aarch64 compatibility). |
| **Owner's MacBook Air M5 (macOS, Darwin 27.0.0 arm64) → ASUS GX10 (NVIDIA GB10) over Tailscale** | Real run on 2026-10-11 14:17–16:25 IST: uv-managed CPython 3.12.15, ModelSaar 0.1.0, **Ollama 0.32.13** at `http://100.83.54.124:11434` serving 8 models. Outputs: `live-check-20261011-141721/` (committed next to the report). Driven from this session by double-clicking `run_live_check.command`, `run_live_eval.command`, `run_reprobe.command` in Finder. |

## Executed

| check | command | outcome |
|---|---|---|
| Lint | `ruff check src tests` | pass |
| Unit + contract + fault-injection tests | `python -m pytest -q` | **64 passed** (36 acceptance cases over real HTTP against the controlled fake backend, 12 unit/CLI tests, 16 regression tests for the adversarial-review and live-run findings) |
| Python 3.10 compatibility | full suite in a 3.10.20 venv (independent reviewer) | pass |
| Simulated evaluation | `modelsaar eval --mode simulated` | runs end-to-end; see docs/evaluation.md for the numbers (SIMULATED — scripted fake backends) |
| CLI end-to-end | `init`, `discover`, `doctor`, `explain`, `config validate`, `client-config --dry-run`, `uninstall` against the fake backend (tests/test_units.py) | pass |
| Probes | streaming/tools/parallel_tools/json_object/json_schema/vision/latency against the fake backend; fingerprint invalidation | pass |
| Independent adversarial review | separate agent, read + executed ad-hoc attacks (see docs/research/adversarial-review-2026-10-11.md) | 28 findings; 3 high, 8 medium and 9 low fixed with regression tests; remaining INFO items documented |
| GitHub Actions CI on the public repository | https://github.com/gopalasubramanium/modelsaar/actions, run #2 (commit 7e2948c) | **green**: tests on 3.10/3.12/3.13, ruff, pip-audit (runtime deps, no known vulnerabilities), gitleaks, Docker image built and `modelsaar --version` smoked inside it. Run #1 failed only because pip-audit tried to resolve the local package on PyPI (fixed). |

### Acceptance cases (spec §15) → tests

| case | test | result |
|---|---|---|
| One healthy model → minimal overhead | `test_single_eligible_model_minimal_overhead` (overhead < 50 ms, measured ~0.4 ms) | pass |
| No eligible model → structured error, no hidden fallback | `test_no_eligible_model_structured_error`, `test_unknown_model_is_404` | pass |
| Tool-enabled code task → tool-capable only | `test_tool_task_only_routes_to_tool_capable`, `test_tool_choice_required_rejected_on_ollama_path`, `test_auto_code_alias_requires_code_tag` | pass |
| Image input → preserved / compatible / clear rejection | `test_image_preserved_and_routed_to_vision`, `test_remote_image_url_rejected_not_fetched`, `test_any_non_data_image_url_is_external` | pass |
| Strict schema → enforced contract, no downgrade | `test_strict_schema_routes_only_to_verified` | pass |
| Large conversation + tools → full accounting, no truncation | `test_large_context_counts_everything_no_truncation`, `test_unknown_context_length_is_a_hard_exclusion`, `test_cjk_token_estimate_is_conservative`, `test_negative_or_zero_max_tokens_rejected` | pass |
| Ambiguous / multilingual → evidence-aware, conservative | `test_ambiguous_and_multilingual_classification` | pass |
| Classifier unavailable / malformed / injected → deterministic continues | `test_classifier_failures_fall_back_deterministically` | pass |
| Outstanding tool results → ids, state, affinity | `test_tool_round_trip_affinity_without_session_id`, `test_tool_round_trip_refuses_cross_model_handover_when_pinned_unhealthy`, `test_tool_round_trip_pins_to_latest_issuer` | pass |
| No session id → documented stateless/fixed policy | `test_session_affinity_header_and_stateless_default` | pass |
| Backend fails before commitment → bounded same-constraint failover | `test_failover_before_commit_same_constraints`, `test_streaming_failover_before_first_byte`, `test_failover_pins_session_to_answering_deployment` | pass |
| Backend fails during streaming → terminate, no duplicate | `test_stream_failure_after_commit_terminates_without_switch`, `test_stream_tool_call_failure_no_duplicate_tool_call`, `test_truncated_stream_is_reported_not_completed` | pass |
| Concurrent requests sharing one pool → limits, cancellation | `test_admission_limits_and_queue_rejection`, `test_client_disconnect_marks_uncertain_occupancy` | pass |
| Model/template/config change → evidence invalidated | `test_fingerprint_change_invalidates_probe_evidence` | pass |
| Embedding fallback → contract preserved or fail | `test_embeddings_contract_no_incompatible_fallback` | pass |
| Offline/local-only → no unauthorized external inference | `test_local_only_blocks_cloud_even_when_explicit`, `test_allow_remote_is_explicit_opt_in` (fixture-scoped claim) | pass |
| Malicious destination/media → not a proxy | `test_backend_host_allowlist_enforced`, `test_prompt_injection_cannot_change_routing`, `test_any_non_data_image_url_is_external` | pass |
| Two clients, similar prompts → no mixing | `test_two_callers_same_session_key_do_not_mix`, `test_decision_log_has_no_prompt_content` | pass |
| Fresh installation and uninstall preserve unrelated files | `test_cli_init_discover_explain_doctor`, `test_cli_uninstall_removes_only_own_files`, `test_uninstall_refuses_foreign_files` | pass |

Streaming contract: partial frames, CRLF, UTF-8 split mid-character, indexed interleaved tool-call
deltas, usage events, terminal `[DONE]`, model-field rewrite — `test_streaming_relay_contract`,
`test_streaming_interleaved_tool_deltas`, `test_sse_parser_partial_frames_crlf_and_unicode_boundary`.


## Live results on real hardware (GX10 / Ollama 0.32.13, 2026-10-11)

Deployments discovered (all Q4_K_M GGUF, declared locality `local` = owner's private tailnet host):
`muse-glimmer:latest` 27.9B, `qwen3.6:latest` 35.5B MoE, `gemma4:31b` 31.3B, `qwen3.8:latest` 27.3B,
`qwen3-coder-next:latest` 79.7B MoE, `qwen3-coder:latest` 30.5B MoE, `qwen3.6-accurate:latest` and
`qwen3.6-fast:latest` (custom Modelfiles, num_ctx 131072 / 65536).

| check | result |
|---|---|
| `init --endpoint http://100.83.54.124:11434` | wrote config + keys; discovered 8 deployments |
| `discover` | capabilities from `/api/show` (tools/vision/thinking), residency + served context from `/api/ps` (131072 while loaded), locality evidence recorded; cloud-alias detection exercised negatively (none present) |
| `doctor` | 0 failures; warnings only for assumed served context (4096) on unloaded models without Modelfile `num_ctx` |
| `probe --all` (first pass, probe budgets 40/200 tokens) | **exposed bug**: thinking models (muse-glimmer, qwen3.6*, gemma4) exhausted the budget on reasoning → streaming/JSON/vision recorded `unsupported` (false negatives). Fixed in commit `dadd377` (larger budgets, reasoning deltas counted, exhausted budget → `unknown`). |
| `probe --all` (re-run with fix, `40-reprobe-all.txt`) | all 8: streaming ✔, tools ✔ (tool call with id + JSON args), parallel tools ✔, json_object ✔, json_schema ✔ (schema-conformant); vision ✔ on 6, `unsupported` for the two text-only coders (metadata) and for muse-glimmer (answered "white" to the 1-px red probe — probe limitation noted). TTFT cold 6–13 s, warm p50 0.25–7.6 s. |
| `discover`/`doctor` after probing | **exposed bug**: they ignored the state DB (showed `json_schema=unknown`). Fixed in `dadd377`; `41-discover-after-reprobe.txt` shows the probed values. |
| `GET /v1/models`, `modelsaar test` | 200; aliases `auto`, `auto-quality`, `auto-balanced`, `auto-fast`, `auto-code` (3 members), `auto-vision` (6 members) advertised |
| `auto` chat ("Reply with one word: ready") | → `ollama/qwen3.6:latest`, 200 |
| `auto` code request | → `ollama/qwen3-coder:latest`; returned a correct `is_palindrome` implementation |
| `auto-fast` streaming | SSE relayed, `model` field rewritten to `auto-fast`, `[DONE]` terminal |
| `auto` + tool definition | → `ollama/qwen3-coder:latest`; real tool call `get_current_time({"city":"Paris"})` with id `call_stec6jyt` |
| `explain` (code+tools / strict schema / image) | after evidence: → resident `qwen3.8:latest` (ranked on catalogue prior + residency); image request excluded 5 deployments by hard filters, 3 eligible |
| **Routing between real deployments** | demonstrated: the same `auto` alias sent chat to `qwen3.6`, code/tools to `qwen3-coder`, vision to `qwen3.6`, agent tool round trips to `gemma4:31b` (`27-decisions.txt`, `eval-live.json`) |
| `eval --mode live --save-measurements --deployments qwen3.6 gemma4:31b qwen3-coder` | completed (`eval-live.json`); see table below. A first full 8-model run was killed when its Terminal window was closed; the subset run executes detached. |
| **exposed design bug** | the deployment fingerprint included the served context, which flips between 4096 (assumed, unloaded) and 131072 (observed, loaded) on every Ollama load/unload — invalidating probe evidence mid-run (gemma4 extraction tasks hit 422 despite a passed `json_schema` probe). Fixed in commit after `dadd377` (fingerprint = intrinsic identity only); measurements saved during this eval were therefore stored under the old fingerprints and must be regenerated with another `eval --save-measurements`. |

### Live evaluation (3-deployment subset; 15 calib / 32 test tasks; temperature 0; max_tokens 400)

| policy | success | 95 % CI | completion | violations | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| auto (live routing) | 0.875 | [0.72, 0.95] | **1.000** | **0** | 693 | 27 136 |
| fixed-strong (calibrated: qwen3-coder) | **0.906** | [0.76, 0.97] | 0.969 | 1 | 646 | 4 849 |
| fixed-fast (calibrated: qwen3-coder) | 0.906 | [0.76, 0.97] | 0.969 | 1 | 646 | 4 849 |
| rules (gold label + specialist tags) | 0.812 | [0.65, 0.91] | 1.000 | 0 | 959 | 4 868 |
| random | 0.688 | [0.51, 0.82] | 0.938 | 2 | 4 189 | 9 826 |
| oracle (offline upper bound) | 0.969 | [0.84, 0.99] | 1.000 | 0 | 552 | 4 585 |

Per deployment on the test split: qwen3-coder 0.906 (p50 0.65 s), gemma4:31b 0.875 (p50 17.5 s —
thinking), qwen3.6 0.500 (thinking budget exhausted by `max_tokens 400` on many tasks; its probes
were also wrongly `unsupported` at eval time, see above). Routing overhead mean 0.53 ms, p95 0.72 ms;
deterministic task-label accuracy 0.84; evidence levels used by `auto`: measured 27/32, uncalibrated 5/32.
Routing mistakes (auto failed, oracle succeeded): `code-03` (sent to gemma4 under an uncalibrated
prior), `math-05`, `long-01`.

**Honest reading.** On this task set and hardware, `auto` did **not** outperform the best single
model: `qwen3-coder:latest` was both the strongest and the fastest deployment, and `auto` chose it
25/32 times anyway. The measurable benefits of routing here are capability coverage (0 violations and
100 % completion — the fixed model cannot take images) and transparency; the cost is a higher p95
latency whenever a task is sent to a slow thinking model. Acceptance targets from docs/evaluation.md:
violations 0 ✔; completion ≥ fixed-strong ✔; success ≥ fixed-strong − 0.05 ✔ (0.875 vs 0.906);
overhead p95 < 5 ms ✔. The simple mode (request a concrete deployment id) remains available.

Caveats: small n (CIs overlap everywhere); `max_tokens 400` penalises thinking models; served context
for unloaded models was assumed 4096 during the run; only 3 of 8 deployments were swept.

## Hardening pass (branch `hardening/review-2026-10-11`, commit `0f8af84` + docs)

The numbers above are the **historical 2026-10-11 results of the 0.1.0 evaluator** and are left as they
were reported (that evaluator had lenient scorers; see docs/progress.md finding 6). Everything in this
section was produced by the repaired code.

### Executed (deterministic)

| check | command | outcome |
|---|---|---|
| Lint | `ruff check src tests` | pass |
| Full test suite (cloud container) | `python -m pytest` — CPython 3.13.16, Linux x86_64, no isolation backend; revision `0172760`…`91f9e6c` (same test files) | **156 passed, 4 skipped** in 70 s. The 4 skips are `tests/test_evaluation.py::test_sandbox_blocks_writes_outside_work`, `::test_sandbox_blocks_network`, `::test_sandbox_reference_solution_passes`, `::test_sandbox_timeout_fails_cleanly` — skip reason "no isolation backend (bwrap not installed; docker present but daemon not reachable)". |
| Full test suite (owner's Mac) | `python -m pytest -rs -v --durations=5` — macOS Darwin 27.0.0 arm64, CPython 3.12.15, isolation backend **`sandbox-exec`** (`/usr/bin/sandbox-exec`; bwrap and docker absent); revision `01727604726077fe70e7acef398427149e45c4c1`; run 2026-10-11 19:55 IST via `run_mac_tests.command` | **160 passed, 0 skipped** in 48 s, exit 0 — the four isolation tests executed under `sandbox-exec` (`test_sandbox_timeout_fails_cleanly` 2.01 s). Log: `docs/live-runs/mac-tests-0172760.txt`. |
| Regression tests for the review findings | `python -m pytest tests/test_hardening_2026_10_11.py` | 27 passed; each one reproduced its defect against `1122e1f` before the fix (finding → fix → test table in docs/progress.md) |
| Evaluator tests | `python -m pytest tests/test_evaluation.py tests/test_classifier_schema.py` | 65 passed, 4 skipped (sandbox) of 69 |
| Clean wheel install, loopback default, private keys, one routed request, scheme-1 state DB migration | `scripts/install-check.sh` | **PASS** (`modelsaar 0.1.0` wheel into a fresh venv; `server.host: 127.0.0.1`; `keys/api_keys` mode 600; chat via `auto` ok; `doctor` reports the 1 probe + 1 measurement written under evidence scheme 1; `meta.evidence_scheme = 2`; old rows kept) |
| Fresh-volume container start (Compose-equivalent: empty volume, read-only config mount, non-root, keys created once, unchanged after restart) | `scripts/compose-smoke.sh` | **NOT RUN here** (no Docker daemon in the build container); the script is a CI step (`container` job) and runs on the next push |
| Live verification script, dry run against the fake backend (SIMULATED models) | `scripts/live_verify.sh http://127.0.0.1:23111 small:1b big:27b`, then the same command again | all steps exit 0; second run skipped every finished step and resumed the evaluation from its checkpoint (`resumed_records: 126`); no key material in any output file |

### Executed live — owner's Mac → GX10, 2026-10-11 18:32–19:02 IST (`docs/live-runs/2026-10-11-gx10-hardening/`)

Driven by double-clicking `run_live_verify.command` in Finder from this session; the script ran
detached (`nohup caffeinate`) and copied its folder back. Environment (`00-env.txt`): macOS Darwin
27.0.0 arm64, CPython 3.12.15, ModelSaar 0.1.0 at commit `0f8af84b66df`, **Ollama 0.32.13** at
`http://100.83.54.124:11434`; `sandbox-exec` available, so `code_exec` tasks were scored in isolation.
Config is in `10b-config-redacted.txt`; model digests in `02-backend-tags.txt` (qwen3.6 `096fdbd02fe6…`,
gemma4:31b `6316f0629137…`, qwen3-coder `06c1097efce0…`, all Q4_K_M); these digests are the deployments'
identities and part of their fingerprints.

| step | outcome |
|---|---|
| `init` (fresh home), `discover`, `doctor` | 8 deployments; `doctor` 0 failures, warnings: assumed served context 4096 for unloaded models, `json_schema` unknown until probed |
| `probe --all` (offline path: no gateway listening yet) | all 8 probed with evidence (`13-probe-all.txt`): streaming/tools/parallel_tools/json_object/json_schema **supported on all 8**; vision supported on 6, `unsupported` on muse-glimmer (answered but did not identify the colour) and on the two coder models (backend metadata) |
| `explain` dry runs (chat / code+tools / vision / strict schema) | code+tools → qwen3-coder (catalogue prior 0.77, blend shown), vision → a vision-capable model, schema → json_schema-verified model (`15-18-*.txt`) |
| gateway started; `/v1/models`, `modelsaar test` | ok |
| **`POST /admin/probe`** (streaming probe of qwen3.6 through the running gateway's admission) | 200 in 11.0 s; evidence visible without restart (`23-admin-probe-via-gateway.txt`) |
| **Wire-level client checks** (`scripts/live_client_checks.py`, `client-checks.json`) | chat 200 → qwen3.8, `model` field = `auto` (attribution ok); stream 200 → qwen3-coder, 12 frames, `finish=stop`, `[DONE]`, every frame's `model` = `auto-fast`, `content-type: text/event-stream`; **tool emission** 200 → qwen3-coder, 1 tool call, `finish=tool_calls`; **tool-result continuation** 200 on the same deployment, decision `affinity.tool_round_trip = ollama/qwen3-coder:latest`, `failover_allowed = false`; **session header** (`X-ModelSaar-Session`) pinned the second request to the first's deployment, decision `affinity.status = found`, `session_source = header:X-ModelSaar-Session`; `video_url` part → **400 `unsupported_content_type`** with no backend dispatch |
| `decisions`, `status` | `27-decisions.txt`: the same `auto` alias sent conversation to qwen3.8 and agent/tool traffic to qwen3-coder; overhead 0.2–0.8 ms |
| Real clients | **NOT RUN** — none installed on the Mac (`50-real-clients.txt` lists the exact commands per client) |

### Live evaluation with the repaired evaluator (3 deployments; 15 calib / 32 test; `max_tokens 400`, temperature 0, seed 7, scorer `2026.10.11-2`, tasks sha256 `84c34596cb64…`, sandbox `sandbox-exec`)

Deployments: qwen3.6:latest (35.5B, ctx assumed 4096), gemma4:31b (31.3B, ctx assumed 4096),
qwen3-coder:latest (30.5B, ctx 131072). Calibration picked qwen3-coder as both fixed-strong and
fixed-fast (calib success 0.933 / p50 0.68 s; gemma4 0.80 / 17.8 s; qwen3.6 0.467 / 4.3 s).

| policy | success | 95 % CI | completion | violations | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| **auto (live routing)** | **0.938** | [0.80, 0.98] | **1.000** | **0** | 598 | 7 958 |
| fixed-strong (calibrated: qwen3-coder) | 0.938 | [0.80, 0.98] | 0.969 | 1 | 639 | 4 760 |
| fixed-fast (calibrated: qwen3-coder) | 0.938 | [0.80, 0.98] | 0.969 | 1 | 639 | 4 760 |
| rules (gold label + specialist tags) | 0.812 | [0.65, 0.91] | 1.000 | 0 | 963 | 4 859 |
| random (diagnostic) | 0.719 | [0.55, 0.84] | 1.000 | 0 | 4 320 | 24 356 |
| oracle (offline upper bound, not available at runtime) | 1.000 | [0.89, 1.00] | 1.000 | 0 | 639 | 4 671 |

Per deployment on the test split: qwen3-coder 0.938 (p50 0.64 s, 1 violation = the vision task it
cannot take), gemma4:31b 0.938 (p50 20.3 s, thinking), qwen3.6 0.500 (p50 4.3 s; 0/5 coding, 0/3
summarization, 0/2 translation under the 400-token budget — its reasoning consumes the budget).
Routing overhead mean 0.67 ms, p95 0.98 ms; task-label accuracy 0.844; evidence levels used by `auto`:
measured for all 32 requests (`measured:2` 25, `measured:1` 7); classifier not enabled. `auto` sent 30/32
tasks to qwen3-coder and the vision task plus the tool round trip (`cont-01`) to gemma4. Routing
mistakes (auto failed, oracle succeeded): `math-05` (qwen3-coder answered 100 for 50), `long-01`
(qwen3-coder dropped a required line). The rules baseline scored 0/5 on coding because it follows the
catalogue's `code` tag to qwen3.6 in deployment order, which fails coding under this budget — a
reminder that tags are hypotheses and measured evidence is what `auto` uses.

**Reading.** On this task set and hardware, `auto` matched the best single model on success (0.938 =
0.938, identical CI) and beat it on completion (1.000 vs 0.969) and capability violations (0 vs 1)
because the fixed model cannot take images; its p95 is higher because the two tasks it sent to
gemma4 are slow (16.6 s and 21.6 s). Acceptance targets (docs/evaluation.md): violations 0 ✔;
completion ≥ fixed-strong ✔; success ≥ fixed-strong − 0.05 ✔; overhead p95 < 5 ms ✔. The explicit
option (request a concrete deployment id, or `auto-fast`) remains the right choice when one model is
known to be best for a workload.

Caveats: n = 32 (CIs overlap everywhere); `max_tokens 400` systematically penalises thinking
models (qwen3.6, gemma4) — a matched larger budget was not run in this pass; served context for
unloaded models was assumed 4096; 3 of 8 deployments swept; one hardware/runtime; synthetic tasks.
Complete sanitised per-request records: `eval-live.json.records.jsonl` (173 records: ids, status,
latency, scorer detail; no prompts); machine-readable aggregates: `eval-live.json`.

### Still NOT RUN after this pass

| item | how to run |
|---|---|
| Real clients (Open WebUI, OpenClaw, OpenCode, Hermes) | see `50-real-clients.txt` in the run folder: install/start the client, `modelsaar client-config <client> --apply`, chat, `modelsaar decisions --limit 10` |
| Fresh-volume container start | `scripts/compose-smoke.sh` on a host with Docker (also runs in CI) |
| Evaluation with a thinking-matched budget / all 8 deployments | `run_live_verify.command` with `DEPS` widened; raise `MAX_TOKENS` in `evaluation/harness.py` for a separately labelled run |
| Embeddings contract against a real embedding model (identity binding, output validation) | `ollama pull qwen3-embedding:0.6b`, declare `embeddings:`, `curl /v1/embeddings` |
| Generic OpenAI-compatible backend (vLLM / llama.cpp) incl. `/tokenize` and `identity` declarations | `modelsaar init --endpoint http://127.0.0.1:8000/v1 --type openai_compatible`, declare models, `scripts/live_verify.sh` |

## NOT RUN (needs hardware, a daemon, or a real client) — status at 0.1.0 / 1122e1f

| item | why not here | how to run |
|---|---|---|
| Embeddings against a real Ollama | no embedding model is pulled on the GX10 | `ollama pull qwen3-embedding:0.6b`, declare an `embeddings:` contract, `curl /v1/embeddings` |
| Live evaluation over all 8 deployments (full sweep) | the full run (~2 h) was interrupted; the 3-deployment subset completed | `modelsaar eval --mode live --save-measurements --out eval.json` detached (`run_live_eval.command` without `--deployments`) |
| Generic OpenAI-compatible adapter against vLLM / llama.cpp server / LM Studio, incl. `/tokenize` | no such server available | `modelsaar init --endpoint http://127.0.0.1:8000/v1 --type openai_compatible`, declare models, `probe --all`, `live_check.sh` |
| Open WebUI, OpenClaw, OpenCode, Hermes Agent: real client tool round trip | no client installed in the build environment | Apply `modelsaar client-config <client>`; in the client ask for something that needs a tool; confirm with `modelsaar decisions` that the follow-up (tool result) stayed on the same deployment |
| Docker Compose against a real backend | not exercised | `docker compose up --build` with `examples/config.docker.yaml` pointing at the GX10 |
| Offline operation with host-level network block | requires the owner's firewall | Block outbound traffic, run `modelsaar serve` + a client, confirm chat completes |
| Classifier benefit on real models | no real classifier model | enable `routing.classifier` with a small local model and compare `modelsaar eval --mode live` with/without |
| Memory/residency measurements on specific hardware | no GPU/unified memory host here | `live_check.sh` records `/api/ps` sizes; eval records latency; add observations to docs/catalogue.md |

## Known limitations observed during verification

* Served Ollama context is assumed 4096 unless Modelfile/`/api/ps`/override says otherwise (doctor warns).
* Token estimate is conservative by design; borderline cases use `/tokenize` only on runtimes that have it.
* With no measurements, `auto` prefers the cheaper of effectively tied candidates; after `eval --save-measurements`
  quality evidence dominates (shown in the simulated run: evidence levels `measured:*` for all test requests).
* (0.1.0) The evaluation code sandbox was basic (subprocess + rlimits); since the hardening pass code
  tasks run only under bubblewrap / `sandbox-exec` / Docker or are skipped.
* Admin key is also valid for inference (one-way separation).

## Publication actions requiring separate authorization

Creating a public repository, publishing to PyPI, pushing a container image, and adding the project
to any registry were **not** performed. The repository is complete for a source install.
