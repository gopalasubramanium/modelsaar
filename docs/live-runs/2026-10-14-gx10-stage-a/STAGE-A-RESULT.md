# STAGE A: COMPLETE (2026-10-14) — baseline, inventory and evaluation freeze

Evidence package: this folder (`MANIFEST.md`, `environment.json`, `deployments.json`, `capabilities.json`,
`smoke-metrics.json`, `evaluation-contract.md`, `model-subset.md`, `stage-b-plan.md`,
`release-readiness.md`, `raw/`). Nothing on the GX10 was changed; Stage B was not started.

**Environment.** Repository `main` `f18b2f1`; gateway package on the GX10 `cf56cdd` (owner-reported, not
re-verified: port 8484 unreachable from the Mac); measurements made with the same `cf56cdd` revision as a
Mac-local gateway against the GX10's Ollama **0.40.3** over Tailscale (the published 2026-10-11 run was on
0.32.13); 8 deployments discovered, all identities verified by Ollama digest; GX10 hardware/OS/memory
NOT EXPOSED over the API.

**Capabilities (probed, admission-coordinated, 382 s, no timeouts).** streaming, tools, parallel tools,
json_object and json_schema supported on all eight except: `qwen3.6-fast` tools **unsupported**
(measured; declared supported) and `muse-glimmer` vision **unsupported** (measured; declared supported);
the two coder models have no vision (declared, not probed). Before probing, `json_schema` and
`parallel_tools` were `unknown` everywhere. Not probed: continuation, tool_choice_required, audio, thinking.
Context: assumed 4096 for six models until observed loaded; Ollama serves 131072 for qwen3.8 (observed)
and 65536 for qwen3.6-fast (Modelfile).

**Smoke (40 requests).** Warm chat 0.1 s (coder models) · 1.0 s (qwen3.8) · 1.3–1.6 s (qwen3.6 family) ·
4.6 s (gemma4) · 7.1 s (muse-glimmer); cold loads ~6.6–8.1 s, qwen3-coder-next ~12.8 s; every model stayed
resident afterwards; two models resident at once (up to 55 GB + 18 GB). Thinking models exhausted the
128/200-token smoke budgets in reasoning and returned no content on the JSON/counting prompts — the
reasoning-budget hazard for Stage B (`max_tokens 400`), documented, not altered.

**Stage B subset.** Included: qwen3.8, qwen3-coder, gemma4:31b, qwen3.6 (+ qwen3-coder-next in a second
pass within budget). Deferred: qwen3.6-accurate (near-duplicate of qwen3.6), qwen3.6-fast (slower
duplicate; tools unsupported), muse-glimmer (slowest; vision not reproduced).

**Baseline candidates.** fixed-strong: qwen3-coder (historical 2026-10-11 winner, 0.933 calib), qwen3.8,
gemma4; fixed-fast: qwen3-coder, qwen3-coder-next. The calibration split decides in Stage B.

**Evaluation freeze.** scorer `2026.10.12-3`; `tasks.jsonl` sha256 `84c34596…`, 47 tasks, calib 15 /
test 32; `temperature 0`, `max_tokens 400`, seed 7; checkpoint format 2; code_exec only under
bubblewrap / sandbox-exec (alpha: disabled pending owner verification) / Docker, else skipped; no
held-out task was sent to any model in Stage A.

**Stage B cost.** ≈ 250 requests / ≈ 35–45 min (pass 1, 4 models), ≈ 300 / 45–55 min with pass 2;
≤ ~165 k tokens; < 1 MB of reports; recommended 90-minute idle window; production service untouched in
placement A (Mac-run), stopped for the window in placement B (GX10-run); `--allow-concurrent` not used.

**Classifier.** Disabled (default) on the Stage A home; GX10 value unknown; not enabled, not changed;
Stage C design prepared.

**Real client.** Odysseus chat on the GX10: owner-reported working as of 2026-10-14 (no tool/vision/
streaming/agent claims). Proposed next client: Open WebUI (not installed in Stage A).

**Release readiness.** READY: CI, installer pin. OWNER ACTION: version bump + changelog, client doc dates,
PyPI Trusted Publisher + `pypi` environment. NOT READY: current-revision evaluation report, tag.
NOT REQUIRED FOR STAGE B: all release steps.

**Stopped here.** Stage B not started; classifier not enabled; routing not tuned; no models downloaded;
no long evaluation; no further review loop.
