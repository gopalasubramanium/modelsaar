# Verification report — ModelSaar 0.1.0 (build of 2026-10-11)

This report lists what was actually executed, where, with what outcome. Anything not executed is
marked **NOT RUN** with the exact procedure to run it. Nothing below is a mocked result presented as
real; simulated runs are labelled as such.

## Environments used

| environment | details |
|---|---|
| Build/test container (cloud) | Linux x86_64, CPython 3.13.16, starlette 1.7.0, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.14.0, PyYAML 6.0.3, pytest 9.1.1. No GPU. Network: PyPI reachable; Hugging Face, Ollama registry and Docker daemon **not** available. |
| Independent review venv | CPython 3.10.20 (uv), same dependency versions — full test suite passed (reviewer's run). |
| Owner's machine (MacBook Air M5) | Reachable only through a Linux VM bridge (aarch64, CPython 3.10.12, no route to the macOS host's Ollama). Repository copied there; see "Owner-side checks". |

## Executed

| check | command | outcome |
|---|---|---|
| Lint | `ruff check src tests` | pass |
| Unit + contract + fault-injection tests | `python -m pytest -q` | **61 passed** (36 acceptance cases over real HTTP against the controlled fake backend, 12 unit/CLI tests, 13 regression tests for the adversarial review findings) |
| Python 3.10 compatibility | full suite in a 3.10.20 venv (independent reviewer) | pass |
| Simulated evaluation | `modelsaar eval --mode simulated` | runs end-to-end; see docs/evaluation.md for the numbers (SIMULATED — scripted fake backends) |
| CLI end-to-end | `init`, `discover`, `doctor`, `explain`, `config validate`, `client-config --dry-run`, `uninstall` against the fake backend (tests/test_units.py) | pass |
| Probes | streaming/tools/parallel_tools/json_object/json_schema/vision/latency against the fake backend; fingerprint invalidation | pass |
| Independent adversarial review | separate agent, read + executed ad-hoc attacks (see docs/research/adversarial-review-2026-10-11.md) | 28 findings; 3 high, 8 medium and 9 low fixed with regression tests; remaining INFO items documented |

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

## NOT RUN (needs hardware, a daemon, or a real client)

| item | why not here | how to run |
|---|---|---|
| Discovery, probes, chat, streaming, embeddings against a **real Ollama** | The session's bridge to the owner's Mac has no route to the macOS host's Ollama; the cloud container cannot download weights | On the Mac: `pip install -e . && scripts/live_check.sh` (writes `live-check-<date>/` with every output). Then attach the folder or paste `summary.txt`. |
| **Routing between two real local deployments by `auto`** | same | `scripts/live_check.sh` runs text, code+tools, vision and streaming requests through `auto` and lists the distinct deployments chosen (`27-decisions.txt`). With a single model installed this degrades to single-model forwarding and must be reported as such. |
| Live evaluation with baselines on real models | same | `modelsaar eval --mode live --probe --save-measurements --out eval.json` (also run by `live_check.sh`) |
| Generic OpenAI-compatible adapter against vLLM / llama.cpp server / LM Studio, incl. `/tokenize` | no such server available | `modelsaar init --endpoint http://127.0.0.1:8000/v1 --type openai_compatible`, declare models, `probe --all`, `live_check.sh` |
| Open WebUI, OpenClaw, OpenCode, Hermes Agent: real client tool round trip | no client installed in the build environment | Apply `modelsaar client-config <client>`; in the client ask for something that needs a tool; confirm with `modelsaar decisions` that the follow-up (tool result) stayed on the same deployment |
| Docker image build / compose | no Docker daemon in the build container | `docker build -t modelsaar:local . && docker run --rm modelsaar:local modelsaar --version`; `docker compose up --build` |
| Offline operation with host-level network block | requires the owner's firewall | Block outbound traffic, run `modelsaar serve` + a client, confirm chat completes |
| Classifier benefit on real models | no real classifier model | enable `routing.classifier` with a small local model and compare `modelsaar eval --mode live` with/without |
| Memory/residency measurements on specific hardware | no GPU/unified memory host here | `live_check.sh` records `/api/ps` sizes; eval records latency; add observations to docs/catalogue.md |

## Known limitations observed during verification

* Served Ollama context is assumed 4096 unless Modelfile/`/api/ps`/override says otherwise (doctor warns).
* Token estimate is conservative by design; borderline cases use `/tokenize` only on runtimes that have it.
* With no measurements, `auto` prefers the cheaper of effectively tied candidates; after `eval --save-measurements`
  quality evidence dominates (shown in the simulated run: evidence levels `measured:*` for all test requests).
* The evaluation code sandbox is basic (subprocess + rlimits), not a security boundary.
* Admin key is also valid for inference (one-way separation).

## Publication actions requiring separate authorization

Creating a public repository, publishing to PyPI, pushing a container image, and adding the project
to any registry were **not** performed. The repository is complete for a source install.
