# STAGE B PASS 1: COMPLETE (as Pass 1b, 2026-10-15) — pending owner acceptance

Two runs exist under the frozen Stage A contract. **Pass 1** (11:21–11:48 IST) is preserved and
labelled **compromised**: the Mac idle-slept for 159 s mid-run, the Tailscale relay path was being
rebuilt when the gateway's health poll fired, one `ConnectTimeout` marked backend `ollama` unhealthy
and the harness recorded 103 `HTTP 422 no_eligible_deployment` refusals in 108 ms (all 104 of its 422s
are accounted for by stored decision records; `pass1-compromised/`). **Pass 1b** (22:01:57–22:30:25
IST, 1708 s, owner-approved 21:53 IST, run under `caffeinate -i`, lid open, AC) is the separately
labelled replacement: 220 records, 218 × HTTP 200, 2 × HTTP 422 — both the legitimate vision
exclusions on qwen3-coder (`vis-01` calib, `vis-02` test) — and no health refusal. The two runs are
not combined. **Whether Pass 1b stands as the official Pass 1 result is the owner's decision.**

Stage A evidence: PR #8, merged as `3733972649449d109c573b1be084d01351cd9eb1` (`main` at run time).

## Execution (Pass 1b)
- Placement A: the harness's in-process gateway on the Mac (Stage A home), backend = the GX10's Ollama
  over Tailscale (`100.83.54.124:11434`); production `modelsaar.service` on the GX10 untouched; no
  `--allow-concurrent`.
- Evaluator/gateway revision `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean checkout, `modelsaar 0.1.0`,
  Python 3.12.15); scorer `2026.10.12-3`; tasks sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c`
  (47 tasks: 15 calibration, 32 held-out); max_tokens 400, temperature 0, seed 7; routing config hash
  `c58ce04fa1ed9902`; classifier **disabled** (consulted 0); checkpoint format 2.
- Ollama **0.40.3**; four identities equal to Stage A (digest and fingerprint): qwen3.8:latest
  `aaee06c39dcf` / `06621e3e0e6844f0`, qwen3-coder:latest `06c1097efce0` / `4eacb9bbc87cccbf`,
  gemma4:31b `6316f0629137` / `c2a3b30b88068a13`, qwen3.6:latest `096fdbd02fe6` / `7495ed65fbf1dbd5`.
- Sandbox backend `sandbox-exec` (macOS, `MODELSAAR_MACOS_SANDBOX=verify`); 5 `code_exec` tasks
  executed in isolation (0 skipped). Gate v4 at PR #9 head `810917d` passed before the run.
- Duration 1708 s; 220 scored requests (+ 28 probe requests); **resumed 0, resume_rejected {}**.
- Residency: `/api/ps` empty before; after: qwen3-coder (32.1 GB) and qwen3.8 (18.5 GB) resident. Every
  `auto` decision chose a deployment that was resident at decision time (residency cost 0.0 in all 32
  stored decisions).

## Calibration (15 tasks per deployment; frozen rule: fixed-strong = highest success, fixed-fast = lowest p50)
| deployment | success | 95 % CI | completion | violations | p50 |
|---|---|---|---|---|---|
| qwen3.8:latest | **1.000** (15/15) | [0.796, 1.0] | 1.000 | 0 | 3160 ms |
| qwen3-coder:latest | 0.933 (14/15) | [0.702, 0.988] | 0.933 | 1 (`vis-01`, vision) | **487 ms** |
| gemma4:31b | 0.800 (12/15) | [0.548, 0.930] | 1.000 | 0 | 20767 ms |
| qwen3.6:latest | 0.400 (6/15) | [0.198, 0.643] | 1.000 | 0 | 4011 ms |

fixed-strong → **qwen3.8:latest**; fixed-fast → **qwen3-coder:latest**. The test split was not consulted.

## Held-out results (32 tasks; Wilson 95 % intervals; reproduced from the records by `scripts/eval_aggregate.py`)
| policy | success | 95 % CI | completion | violations | p50 | p95 |
|---|---|---|---|---|---|---|
| **auto** (deterministic router) | **0.938** (30/32) | [0.799, 0.983] | 1.000 | 0 | 377 ms | 1829 ms |
| fixed-strong (qwen3.8) | 0.906 (29/32) | [0.758, 0.968] | 1.000 | 0 | 3443 ms | 10189 ms |
| fixed-fast (qwen3-coder) | 0.938 (30/32) | [0.799, 0.983] | 0.969 | 1 | 459 ms | 4638 ms |
| rules (gold-category diagnostic, not deployable) | 0.844 (27/32) | [0.682, 0.931] | 1.000 | 0 | 1720 ms | 4990 ms |
| random (seeded diagnostic) | 0.688 (22/32) | [0.514, 0.820] | 1.000 | 0 | 4288 ms | 23270 ms |
| oracle (offline upper bound, not available at runtime) | 1.000 (32/32) | [0.893, 1.0] | 1.000 | 0 | 454 ms | 4520 ms |

Per-deployment test sweeps: gemma4 0.938, qwen3-coder 0.938 (1 violation), qwen3.8 0.906, qwen3.6 0.531.
Time-to-first-token is not recorded by the frozen harness (non-streaming requests).

Failures by category — auto: math 1 (`math-05`), summarization 1 (`long-01`); fixed-strong: agent 2
(`agent-03`, `cont-01`), coding 1 (`code-05`); fixed-fast: math 1 (`math-05`), document_vision 1 (`vis-02`, 422).

**auto vs fixed-strong (paired on the 32 tasks):** +1 success (30 vs 29), difference **+0.031**,
95 % CI **[−0.105, +0.168]** — 3 tasks passed only under auto (`agent-03`, `code-05`, `cont-01`), 2
only under fixed-strong (`long-01`, `math-05`); completion difference 0; violation difference 0;
latency p50 −3066 ms, p95 −8360 ms. No "X % better" claim is supported: the success interval includes zero.

## Routing
- Selection distribution: qwen3-coder **31**, qwen3.8 **1** (`vis-02`, the only vision task; qwen3-coder
  excluded `vision unsupported`). gemma4 and qwen3.6 never selected.
- Why: on 31 tasks the router scored qwen3-coder 0.9555 vs qwen3.8 0.938 — both carried measured quality
  1.00 for the inferred task (calibration evidence, `measured:2` on 25 tasks, `measured:1` on 7) — and the
  latency term (0.02 vs 0.15) decided. Affinity: stateless on all 32 (no session), never affected a choice.
- Routing overhead: mean 0.37 ms, p50 0.30 ms, p95 0.50 ms, max 3.18 ms. Task-label accuracy 0.844
  (27/32 inferred primary task = gold category; 6 tasks flagged ambiguous).
- Capability violations under auto: 0. Against fixed-fast, auto avoided the one violation (`vis-02`).
- Routing-result categories (`routing-analysis.json`): improved 3 (`agent-03`, `code-05`, `cont-01`);
  worsened 2 (`long-01` — qwen3-coder missed the required line, qwen3.8 passed; `math-05` — qwen3-coder
  answered 100 for 50, qwen3.8 passed); same model & both passed 1 (`vis-02`); irrelevant to the outcome
  (same result on either model) 26. None of auto's failures is a SUSPECTED budget-limited event.
- Probes: streaming, tools, json_object, json_schema supported on all four; vision supported on qwen3.8,
  qwen3.6, gemma4; **unsupported** on qwen3-coder (`capabilities.json`).

## Reasoning budget (Phase 5; `reasoning-budget-analysis.json`)
The harness records scorer detail and latency only — no finish reason, no token usage — so no event is
**proven** budget-limited; the primary scores are unchanged and nothing was rerun at a higher budget.
Of 37 failed records, **19 are SUSPECTED budget-limited under the frozen contract**: 5 "empty" content
(qwen3.6 `conv-01/02/03`, gemma4 `conv-01/02`), 8 code answers whose function was never defined (empty
harness output; qwen3.6 ×6, gemma4 ×2), 6 answers with no usable number/JSON (qwen3.6). All 19 are on
**qwen3.6 (14)** and **gemma4 (5)** sweeps; **0 in `auto`, 0 on the calibrated fixed-strong model
(qwen3.8)**. 15 failures are plain wrong answers with content present, 2 capability exclusions, 1 syntax
error. Recommendation: a separately authorised reasoning-budget sensitivity run would mainly change the
qwen3.6/gemma4 sweep rows, not the deployable auto-vs-fixed comparison; it is an owner option, not a
prerequisite for interpreting Pass 1b.

## Acceptance (Phase 7; `acceptance.md`)
capability target **PASS** (0) · completion target **PASS** (1.000 ≥ 1.000) · success target **PASS**
(0.938 ≥ 0.856) · overhead target **PASS** (p95 0.5 ms < 5 ms) · classifier-timeout target not applicable.
**Disposition: 1 — DETERMINISTIC ROUTING BASELINE ACCEPTED on Pass 1b**, conditional on the owner
accepting Pass 1b as the Pass 1 result (Pass 1 alone would be disposition 3, INVALID / MUST BE RERUN —
which Pass 1b is).

## Material limits (read before quoting)
1. **Stored measurements at start.** Pass 1's calibration measurements (and Stage A probe evidence) were
   already in the Stage A home's state DB when Pass 1b started (48 rows before and after,
   `raw/store-measurements-*.json`); no pre-Pass-1 snapshot exists. Pass 1b's own calibration re-measured
   the same keys before the `auto` phase, so `auto` routed on fresh values, but Pass 1b's starting state
   was not Pass 1's.
2. **Empty console transcript and empty health sidecar.** The harness's stderr did not reach
   `console-transcript.txt` under `caffeinate`, and the read-only `/admin/status` sidecar recorded 0
   samples. The sidecar is **not** health evidence. Health during the run is evidenced by the checkpoint
   (every policy row complete; no health-refused record; the only 422s are the two vision exclusions)
   and by the report; the console table is reproduced by `scripts/eval_aggregate.py`.
3. **Budget events are SUSPECTED, not proven** (no finish reason/usage recorded).
4. **Two Pass 1 reports exist**; they are not merged, and the website still quotes the 2026-10-11 result
   until the owner reviews this package (`site/facts.py` unchanged).
5. The Mac→GX10 path is DERP-relayed (no direct LAN/UDP path); every latency column includes it equally.

## Evidence
Folder `docs/live-runs/2026-10-15-gx10-stage-b-pass1/` (`MANIFEST.md` lists every file and hash).
Report `stage-b-pass1b.json` sha256 `0f50675d9de15dfa5cb5bf2d418ce35ab8244673e238e3cdf882a0b5197bf02c`;
checkpoint `stage-b-pass1b.records.jsonl` sha256 `482e44e7e4250acdd8a17b47f9d3030d11823abe97c508c6f2632a4cad7c9cfd`.
Pass 1 (compromised): report `d72ddc6695a0a8561392f32be32d83853ef56adbb46e1e902f7eba17fd8bd726`,
checkpoint `6d1ca65c10c46cca5ead006c3e976c0f3c8ec3d1f4e12353f40790fc46e8803e`. Ready PR: see MANIFEST §G.

## STOP — confirmed
Pass 2 (qwen3-coder-next) was **not** run; no model added; the classifier remained **OFF**; routing was
not tuned; max_tokens unchanged; the production GX10 ModelSaar service, Ollama and model tags were
untouched; no publication to PyPI/GHCR, no tag, no website change.
