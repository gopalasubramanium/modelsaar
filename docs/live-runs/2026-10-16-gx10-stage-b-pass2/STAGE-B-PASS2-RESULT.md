# STAGE B PASS 2: COMPLETE (2026-10-16, Ollama 0.40.5) — qwen3-coder-next added; cross-runtime vs Pass 1b

**Read the runtime label first.** Pass 2 ran against the GX10's **Ollama 0.40.5**; the accepted Pass 1
result (Pass 1b, `docs/live-runs/2026-10-15-gx10-stage-b-pass1/`) ran against **Ollama 0.40.3**. Every
comparison between the two runs is therefore **cross-runtime**: the runtime changed *and* a fifth
deployment was added at the same time, so **the effect of adding `qwen3-coder-next` cannot be isolated**
from the runtime change (nor from the re-created `qwen3.6:latest` tag or ordinary run-to-run variation).
Pass 2's own numbers are internally consistent (every table below is reproduced from its records by
`scripts/eval_aggregate.py`), and Pass 1 / Pass 1b are preserved unchanged; the runs are not combined.

## Execution
- Owner authorisation: 2026-10-16 13:47 IST (run Pass 2 once) → 13:58 the launcher stopped because Ollama
  was 0.40.5, not the frozen 0.40.3 → 14:14 the owner authorised one Stage A-style identity + probe
  re-baseline under 0.40.5 followed by Pass 2 → 14:30 the owner accepted two further identity deviations
  found by the re-baseline (below). Run **14:49:16–15:19:29 IST (1813 s, exit 0)**; probes 14:49–14:53.
- Placement A as in Pass 1/1b: the harness's in-process gateway on the Mac (Stage A home), backend the
  GX10's Ollama over Tailscale (`100.83.54.124:11434`); production `modelsaar.service` untouched; no
  `--allow-concurrent`; `caffeinate -i` alongside; Mac on AC (the 13:56 attempt stopped on battery).
- Frozen elements unchanged: evaluator checkout `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean;
  `modelsaar 0.1.0`, Python 3.12.15); scorer `2026.10.12-3`; tasks sha256
  `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (15 calibration + 32 held-out);
  max_tokens 400, temperature 0, seed 7; routing config hash `c58ce04fa1ed9902`; classifier **disabled**
  (consulted 0); sandbox `sandbox-exec` (5 `code_exec` tasks executed in isolation); `--probe`,
  `--save-measurements`; **resumed 0, resume_rejected {}**; 267 records = 263 × HTTP 200 + 4 × HTTP 422
  (the legitimate vision exclusions `vis-01`/`vis-02` on the two coder models). No health refusal: the
  read-only sidecar recorded **358 `/admin/status` samples, 0 unhealthy, no `last_refresh_error`**.
- **Five deployments** (`--deployments`): qwen3.8:latest, qwen3-coder:latest, gemma4:31b, qwen3.6:latest
  and **qwen3-coder-next:latest** (79.7B MoE, Q4_K_M, 51.7 GB weights; the "residency/loading cost case"
  named in Stage A's `model-subset.md`).

### Deviations from the frozen Stage B contract (all owner-decided; `environment.json`)
1. **Runtime**: Ollama **0.40.5** (upgraded on the GX10 before this task, not by it). `runtime_version` is a
   fingerprint input, so every deployment fingerprint differs from Stage A/Pass 1b; identities were
   re-baselined 14:18–14:22 IST (`baseline-ollama-0.40.5/`: tags, `/api/show`, discover, probes of the five).
2. **`qwen3.6:latest` identity**: manifest digest `096fdbd02fe6…` → `a7eb95c53bcf…` (tag re-created on the
   GX10 at 13:35 IST; identical weight blobs, template, parameters and capabilities; `details.runner:
   llamacpp` added). The other four digests equal Stage A.
3. **Inventory**: 11 tags on the GX10 (8 in Pass 1b): `d1:latest` (lfm2 2.7B, generative), `nimble-v3:latest`
   (decision), `embeddinggemma-2:latest` (embedding) were added 13:17–13:33 IST. The harness's `--probe`
   step probed **9** generative deployments (8 + d1); sweeps and `auto` were restricted to the five.
4. **Launcher**: harness in the foreground through `tee` with `caffeinate -i -w` alongside; diagnostic
   sidecar. `pass2/console-transcript.txt` is nevertheless empty on the Mac (cause not established); the
   same stream is in `raw/55-pass2-launcher-console.txt` (267 `[eval]` lines + the report table).

Identities (digest / fingerprint under 0.40.5): qwen3.8 `aaee06c39dcf` / `1f657c93815106c4`; qwen3-coder
`06c1097efce0` / `3acc2cdc4e4a963c`; gemma4 `6316f0629137` / `d9c2d9116eefdbe8`; qwen3.6 `a7eb95c53bcf` /
`1c2c6fd22bf8cb30`; qwen3-coder-next `ca06e9e4087c` / `76cc87b6d1648f9f` (`deployments.json`).

## Calibration (15 tasks per deployment; frozen rule: fixed-strong = highest success, fixed-fast = lowest p50)
| deployment | success | 95 % CI | completion | violations | p50 |
|---|---|---|---|---|---|
| qwen3.8:latest | **1.000** (15/15) | [0.796, 1.0] | 1.000 | 0 | 3170 ms |
| qwen3-coder:latest | 0.933 (14/15) | [0.702, 0.988] | 0.933 | 1 (`vis-01`) | **504 ms** |
| qwen3-coder-next:latest | 0.933 (14/15) | [0.702, 0.988] | 0.933 | 1 (`vis-01`) | 755 ms |
| gemma4:31b | 0.800 (12/15) | [0.548, 0.930] | 1.000 | 0 | 21330 ms |
| qwen3.6:latest | 0.400 (6/15) | [0.198, 0.643] | 1.000 | 0 | 4171 ms |

fixed-strong → **qwen3.8:latest**; fixed-fast → **qwen3-coder:latest** (the same two as Pass 1b; qwen3-coder-next
tied qwen3-coder on calibration success but is slower, so it became neither baseline). The test split was
not consulted.

## Held-out results (32 tasks; Wilson 95 % intervals; reproduced from the records by `scripts/eval_aggregate.py`)
| policy | success | 95 % CI | completion | violations | p50 | p95 |
|---|---|---|---|---|---|---|
| **auto** (deterministic router) | **0.938** (30/32) | [0.799, 0.983] | 1.000 | 0 | 407 ms | 1958 ms |
| fixed-strong (qwen3.8) | 0.938 (30/32) | [0.799, 0.983] | 1.000 | 0 | 2986 ms | 10538 ms |
| fixed-fast (qwen3-coder) | 0.938 (30/32) | [0.799, 0.983] | 0.969 | 1 | 489 ms | 4812 ms |
| rules (gold-category diagnostic, not deployable) | 0.844 (27/32) | [0.682, 0.931] | 1.000 | 0 | 1626 ms | 6067 ms |
| random (seeded diagnostic) | 0.781 (25/32) | [0.612, 0.890] | 0.969 | 1 | 2790 ms | 6477 ms |
| oracle (offline upper bound, not available at runtime) | 1.000 (32/32) | [0.893, 1.0] | 1.000 | 0 | 423 ms | 1938 ms |

Per-deployment test sweeps: qwen3.8 0.938, gemma4 0.938, qwen3-coder 0.938 (1 violation), **qwen3-coder-next
0.938 (1 violation, `vis-02`; p50 700 ms, p95 4815 ms; its one scored failure is `long-01`)**, qwen3.6 0.594.
Time-to-first-token is not recorded by the frozen harness.

Failures — auto: `math-05` (math), `long-01` (summarization); fixed-strong: `code-05` (SyntaxError in model
code), `cont-01` (agent); fixed-fast: `math-05`, `vis-02` (422).

**auto vs fixed-strong (paired on the 32 tasks): 30 vs 30, difference 0.000, 95 % CI [−0.122, +0.122]** —
2 tasks passed only under auto (`code-05`, `cont-01`), 2 only under fixed-strong (`long-01`, `math-05`);
completion difference 0; violation difference 0; latency p50 −2579 ms, p95 −8580 ms. **No success
advantage is claimed in either direction**; the deployable difference is latency.

## Routing
- Selection: qwen3-coder **31**, qwen3.8 **1** (`vis-02`, the only vision task; both coder models excluded
  `vision unsupported`). **qwen3-coder-next was never selected (0 of 32)**, gemma4 and qwen3.6 never.
- Why qwen3-coder-next lost every decision (stored decision records, `routing-analysis.json`): on all 31
  non-vision tasks the three top candidates carried measured quality 1.00 for the inferred task; scores
  were qwen3-coder **0.9785** (latency cost 0.024, residency 0.0, load/overhead 0.359), qwen3.8 **0.9606**
  (0.149 / 0.0 / 0.343) and qwen3-coder-next **0.8447** (0.035 / **1.0** / **1.0**). With the frozen
  `quality` profile (latency 0.15, residency 0.1, overhead 0.05) the not-resident penalty (−0.10) and the
  largest-weights load heuristic (−0.05) outweighed its small latency edge over qwen3.8. qwen3-coder-next
  was never resident when an `auto` decision was made (the sweeps left qwen3-coder and qwen3.8 resident).
  This is the behaviour the residency weight exists for; it is **described, not evaluated as good or bad**,
  and no routing change follows (Stage B rule).
- Routing overhead: mean 0.40 ms, p50 0.30 ms, p95 0.60 ms, max 3.14 ms (report p95 0.57 ms). Task-label
  accuracy 0.844 (27/32; 6 tasks flagged ambiguous). Every `auto` choice was resident at decision time
  (residency cost 0.0 in all 32 decisions). Affinity never affected a choice (stateless requests).
- Routing-result categories: improved 2 (`code-05`, `cont-01`), worsened 2 (`long-01`, `math-05`), same model &
  both passed 1 (`vis-02`), irrelevant to the outcome 27. Capability violations under auto: 0.
- Probes (`capabilities.json`): streaming/tools/json_object/json_schema supported on the five; vision
  supported on qwen3.8, qwen3.6, gemma4; unsupported on both coder models. `d1:latest` (probed as the 9th
  generative model, not in the eligible set) reported every probed capability unsupported.

## Reasoning budget (`reasoning-budget-analysis.json`)
No finish reason or token usage is recorded, so no event is **proven** budget-limited; primary scores are
unchanged and nothing was rerun at a higher budget. Of 37 failed records, **17 are SUSPECTED budget-limited**
(5 empty content, 8 code with no function defined, 4 no usable number/JSON) — all on the **qwen3.6 (12)** and
**gemma4 (5)** sweeps; **0 in `auto`, 0 on fixed-strong, 0 on qwen3-coder-next**. 15 are plain wrong answers,
4 capability exclusions, 1 syntax error. The optional sensitivity run was **not** performed (owner instruction).

## Acceptance against the predeclared targets (`acceptance.md`)
capability violations 0 **PASS** · completion 1.000 ≥ 1.000 **PASS** · success 0.938 ≥ 0.888 **PASS** ·
overhead p95 0.6 ms < 5 ms **PASS** · classifier target not applicable. The targets are met on Pass 2's own
evidence; auto's success equals fixed-strong's (paired difference 0, interval includes zero).

## Cross-runtime reading (Pass 1b → Pass 2) — descriptive only
auto 0.938 → 0.938; fixed-strong (qwen3.8) 0.906 → 0.938; fixed-fast 0.938 → 0.938; qwen3.6 sweep 0.531 →
0.594; auto's selection pattern identical (31 coder / 1 qwen3.8). These movements are within the intervals
and confounded by the runtime change, the re-created qwen3.6 tag and run-to-run variation; **none of them is
attributable to the added model**, which `auto` never selected.

## Material limits (read before quoting)
1. Cross-runtime, as stated at the top; Pass 1b remains the accepted Pass 1 result and is not superseded.
2. Stored measurements: 53 rows before, 103 after (`raw/store-measurements-*.json`); the 0.40.5 fingerprints
   are new keys, so `auto` routed on this run's own calibration measurements.
3. `raw/console-transcript.txt` empty (see deviation 4); the launcher log carries the stream; the checkpoint
   is the record of truth. The sidecar **is** health evidence this time (358 samples, 0 unhealthy).
4. Budget events SUSPECTED, not proven. 5. DERP-relayed Mac→GX10 path in every latency column equally.

## Evidence
Folder `docs/live-runs/2026-10-16-gx10-stage-b-pass2/` (`MANIFEST.md`). Canonical Mac run files: report
`stage-b-pass2.json` sha256 `4358acf888a52774c98f4dc3c705f0789bb31a43c9cd1e36933a577ef85806eb`; checkpoint
`stage-b-pass2.records.jsonl` sha256 `81fa792ed321b01fc2f06e7d331e9ad921d80651f682cc3980363e36e1479e87`
(public copy byte-identical). The public report copy is path-redacted (`<EVAL_CHECKOUT>`, `<RUN_ROOT>`; sha256
`164333d7f9fec121462bf6eba0f7b2c701c1d492d31479e51dedbbf21eb5f081`; equal to the canonical object once the
placeholders are restored).

## STOP — confirmed
No Ollama, GX10 service, model-tag, registry, evaluator, scorer or configuration change was made by this
task; the classifier stayed **OFF**; routing was not tuned; Pass 1/1b unchanged; no sensitivity run, no Stage
C, no tag, no registry release, no website change (`site/facts.py` still quotes the 2026-10-11 result).
