# Classifier OFF vs ON — manifest (GX10 backend, 2026-10-25, Ollama 0.40.5; Stage B Pass 1 pool; outcome KEEP OFF)

This folder holds **one launcher run of two evaluations** for the optional classifier comparison of
`docs/plans/measured-routing-quality.md` (design item 5; prepared design `../2026-10-14-gx10-stage-a/stage-b-plan.md`
§6): an **OFF twin** (deterministic router, config hash `c58ce04fa1ed9902`) that was **compromised by a backend
health flap** after 11 requests and is preserved under `off-compromised/`, and the **ON run** (live classifier
`qwen3.8:latest`, timeout 2.0 s, only when ambiguous; config hash `58fe0f31907b03ae`) that completed. The rule's
OFF side is **Stage B Pass 1b `auto`** (`../2026-10-15-gx10-stage-b-pass1/`, Ollama 0.40.3), exactly as §6 defines
it; the ON-vs-OFF comparison is therefore **cross-runtime**. Pass 1, Pass 1b, Pass 2 and Stage C evidence is
**unchanged, not combined and not re-run** (hashes verified by the launcher before and after). Outcome: **gain
0.000, median overhead 0.55 ms → KEEP OFF**; the classifier timed out on every one of its 38 calls.

Read `CLASSIFIER-COMPARISON-RESULT.md` first; `acceptance.md` for the targets and the rule; `comparison.json` for the
per-task table; `environment.json`, `deployments.json` for identities; `raw/` for the launcher, configs and probes.
No keys, prompts, completions or application data (the stored decisions are the synthetic tasks' routing records).

## A. Execution baseline

| item | value | evidence |
|---|---|---|
| Date/time, zone | 2026-10-25 **03:28:46–04:08:41 IST** (UTC+05:30). OFF twin 03:28:54–03:30:25 (91 s, exit 0, compromised); ON 03:30:26–04:08:39 (2293 s, exit 0, complete); watchdog (70 min per run) not triggered | `raw/91-classifier-launcher-console.txt` |
| Owner authorisation | 2026-10-25 03:23 IST: the classifier-on vs classifier-off comparison only, per the existing plan and criteria; no production GX10 / Ollama / tag / evaluator / scorer / configuration change; no website publication, no merge | `environment.json` |
| Repository `main` at run | `08d6d3ed465124d0e40f62aef87b7ea9148cf044` | `environment.json` |
| Evaluator / gateway revision | `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean checkout, `modelsaar 0.1.0`, Python 3.12.15) | launcher console |
| Scorer / tasks | `2026.10.12-3`; tasks sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (15 calib + 32 test) | reports `conditions` |
| Budgets / seed | max_tokens 400, temperature 0, seed 7 | reports |
| Routing config | OFF `c58ce04fa1ed9902` (the Stage B/C config, untouched before and after); ON `58fe0f31907b03ae` = OFF + three lines (`enabled: true`, `backend: ollama`, `model: qwen3.8:latest`); classifier `timeout_s 2.0`, `only_when_ambiguous true`, `max_input_chars 1500`, `max_output_tokens 64`, `allow_remote false` | `raw/config-show-off.txt`, `raw/config-show-on.txt`, `raw/config-classifier.yaml` |
| Flags | `eval --mode live --seed 7 --deployments <four> --out … --checkpoint …`; **no `--probe`, no `--save-measurements`** (stored measurements 133 rows before and after, unchanged) | launcher console, `raw/store-measurements-*.json` |
| Sandbox | `sandbox-exec` (`MODELSAAR_MACOS_SANDBOX=verify`); 5 `code_exec` tasks executed in isolation | reports `sandbox` |
| Placement | A — in-process gateway on the Mac (Stage A home, port 50824 verified free), GX10 Ollama over Tailscale; **production `modelsaar.service` not stopped, not touched, not contacted** | launcher console |
| Ollama | **0.40.5** (Pass 1b: 0.40.3; Pass 2, Stage C, this run: 0.40.5) | `raw/ollama-version.json` |
| Deployments (eligible) | qwen3.8, qwen3-coder, gemma4:31b, qwen3.6 — all discovered, healthy; **identities equal the 0.40.5 re-baseline (4/4)**; stored measurements 11 each; probed capabilities present | `raw/identities.json`, `deployments.json` |
| Classifier model | `qwen3.8:latest` (smallest of the eight by weights; thinking model); resident with `size_vram` 18 798 597 897 B in every `/api/ps` snapshot (before OFF, between runs, after ON) | `on/ollama-ps-*.json`, `off-compromised/ollama-ps-*.json` |
| Inventory | 11 tags on the GX10 (unchanged since 2026-10-16) | `raw/ollama-tags.json` |
| Records, ON | 220 (60 calib + 128 test + 32 auto): 218 × 200, 2 × 422 (declared vision exclusions on qwen3-coder: `vis-01` calib, `vis-02` sweep); resumed 0; resume_rejected {} | `on/classifier-on.records.jsonl` |
| Records, OFF twin | 220: **11 × 200 then 209 × 422** `no_eligible_deployment` (every deployment excluded "backend unhealthy: ollama: ConnectTimeout"); resumed 0 | `off-compromised/classifier-off.records.jsonl`, `off-compromised/decisions/` |
| Health, ON | sidecar 453 samples 03:30:31–04:08:32, **0 unhealthy**; gateway classifier counters at the end: calls 38, timeouts 38, failures 0 | `on/gateway-status-timeline.jsonl` |
| Health, OFF twin | sidecar 16 samples 03:28:59–03:30:15; all deployments unhealthy from 03:29:49 (health refresh `ConnectTimeout`) until the run exhausted its requests at 03:30:25 | `off-compromised/gateway-status-timeline.jsonl` |
| Mac | macOS 27.0.1, AC; launcher `caffeinate -i -s -w <pid>` (PreventSystemSleep + PreventUserIdleSystemSleep verified before/after), lid open | `raw/pmset-assertions-*.txt` |
| Verification | `scripts/eval_aggregate.py` → "all aggregates in the report match the records" for ON and for the OFF twin (canonical and public copies; see §E.7 for the twin) | this folder |

## B. Differences from earlier runs (all recorded; none gated)

1. **Runtime** 0.40.5 as Pass 2 / Stage C; the §6 OFF reference (Pass 1b) ran on 0.40.3 → cross-runtime comparison.
2. **No same-runtime OFF**: the twin failed on a health flap and was not rerun (owner rule: one evaluation, preserve partial evidence).
3. **No `--probe` / `--save-measurements`**: the §6 design reuses the stored Stage B evidence; the store is unchanged (133 rows).
4. **Config hash** `58fe0f31907b03ae` is new; the ON run was not resumed from any checkpoint.
5. **Classifier consulted on every ambiguous request of every policy** (38 calls = 8 ambiguous tasks — `dec-01`, `sum-01` in calibration and the six held-out ones — × 4 explicit sweeps + 6 under `auto`), not only under `auto`; all timed out. The fixed-policy latencies of the six ambiguous tasks in the ON run therefore include the classifier path.
6. **Residency at the `auto` phase**: qwen3-coder and qwen3.8 resident (as in Pass 1b/2) → qwen3-coder chosen 31/32; the Stage C mirror image did not recur.

## C. Results in one paragraph

ON: **auto 0.938 (30/32)**, fixed-strong (qwen3.8) 0.938, fixed-fast (qwen3-coder) 0.938 (1 violation), rules 0.844,
random 0.719, oracle 1.000; `auto` chose qwen3-coder 31/32 and qwen3.8 on `vis-02`; p50 418 ms. Against the §6 OFF
reference (Pass 1b auto 30/32, same two failures `math-05`, `long-01`, same selections, same labels): **paired
difference 0.000, no discordant task, interval [0, 0]**. The classifier (`qwen3.8`, resident) **timed out on all 6
consulted `auto` requests and all 38 gateway-wide calls**; `used = 0`. Routing overhead mean 376 ms, **median
0.55 ms**, p95 2003.5 ms. On the six consulted tasks every policy's end-to-end latency was ≈ 22 s higher than in
Pass 1b (non-ambiguous tasks: median +3 ms) — ≈ 20 s of it unattributed by any recorded field (hypothesis for a
follow-up, not a finding). Predeclared targets: 3 PASS, 2 FAIL (overhead p95 2003.5 ms vs < 2000 ms, marginal;
timeouts 100 % vs < 5 %); **decision rule → KEEP OFF**; disposition unchanged.

## D. Derived files

`comparison.json` (ON vs Pass 1b per task, classifier status per task, overhead statistics, fixed-sweep latencies of
the consulted tasks ON vs Pass 1b, the compromised twin's summary, the rule evaluation), `acceptance.json` /
`acceptance.md`, `environment.json`, `deployments.json`. Generated from the reports, checkpoints and stored decisions
only; descriptive; no routing change follows.

## E. Material limits

1. **Cross-runtime**: the rule's OFF side is Pass 1b (0.40.3). With identical outcomes, labels and selections and a
   classifier that produced no label, the runtime cannot have changed the verdict; it does confound all latency
   comparisons between the two.
2. **Classifier never effective** (38/38 timeouts at 2.0 s, model resident): the run measures the cost of consulting
   this configuration, not the value of its labels. §6's non-thinking alternative (`qwen3-coder`) was not run.
3. **≈ 20 s unattributed stall** per consulted request under every policy; `overhead_ms` holds 2.0 s and the upstream
   call ~0.2 s; whether the cancelled classifier generation continued on the backend and blocked the next request
   (gateway admission or Ollama scheduler) is **not established** by the records.
4. **OFF twin compromised**: one `ConnectTimeout` in the gateway's health refresh marked all deployments unhealthy and
   the harness returned 422 for the remaining 209 requests in 36 s without back-off — a harness limitation (backlog
   candidate; no code changed here).
5. **n = 32**, six ambiguous tasks; no equivalence is established; production gateway not observed; DERP-relayed path
   in every latency column equally.
6. **Path redaction**: public copies of the reports, `raw/discover.json`, the decisions and the text logs replace the Mac
   absolute paths by `<EVAL_CHECKOUT>` / `<RUN_ROOT>` / `~`; each public report equals the canonical Mac object once the
   placeholders are restored (verified); checkpoints byte-identical; decisions have `_store_saved_at` removed. Canonical
   Mac hashes: ON report `1b51d8cf7346bb2dbee1c665742f7d9c9f61e0ec3eca1527b47ac445f1d7980e`, ON checkpoint
   `e67d7cb575bcae5081e3d09be50c0c6b24af01c13d73f1c1b8594f7f2a8d8f26`, OFF twin report
   `7fdc1ba4c81df06f8196b3192d2fc8bc84201473efc22ca2e05bd784e4c9c959`, OFF twin checkpoint
   `ddaa12c54872691329fdf42127c0da2c5a9e31a0dd3ffab4f587be3bceb85b08`.
7. **Checker display line**: on the all-422 twin the shipped `scripts/eval_aggregate.py` raises in its *print* loop
   (`p50_ms`/`p95_ms` are `None` when no `auto` request completed) before reaching the comparison; with that one
   display line made `None`-tolerant (comparison logic unchanged) it reports "all aggregates in the report match the
   records". The script was **not** modified in this docs-only branch; this is noted for a follow-up.

## F. Hashes (sha256, public copies in this folder)

| file | bytes | sha256 |
|---|---|---|
| `CLASSIFIER-COMPARISON-RESULT.md` | 9982 | `8ac014dcda20400ff5bffc0bbd2bd8b399478c8bd2925f8a710eb3f366adcc16` |
| `acceptance.json` | 1602 | `945925d366bc4047b2f520520dded27ac0ed7a47980bef448928eea17b523be0` |
| `acceptance.md` | 3300 | `2bea6d94f2a207d6d764732e229e6c3eaefffef783b76a74432fc35ae252d0bc` |
| `comparison.json` | 36052 | `511a1ca23e8555670512a1436d5e1d9e6ddab7c2a14aaedc63e81e30d895ab32` |
| `deployments.json` | 2899 | `6c6eefe75c65ae18e0aaf4a3106c0e71d8e3e116f789d5c60d3d517ca0f0b5c4` |
| `environment.json` | 7052 | `f139122882aa6fa49f0fddaf6486863ed0529a9968d01af123f05d6765d6c32e` |
| `off-compromised/classifier-off.json` | 178764 | `8b2c206c98bb78d78976ea5a1d164a7d6c3a02e93b0275ba761be3eb7cb81ba5` |
| `off-compromised/classifier-off.records.jsonl` | 120324 | `ddaa12c54872691329fdf42127c0da2c5a9e31a0dd3ffab4f587be3bceb85b08` |
| `off-compromised/console-transcript.txt` | 20189 | `4ccd469724758bf9830008d45778283761c516b3b375af37a4b2f330a80f9240` |
| `off-compromised/gateway-status-timeline.jsonl` | 14941 | `9a2d5f1c944b2ebf31d3eecb7eb7408f45d3f9e5f69c52d7ccc2717c203dc313` |
| `off-compromised/ollama-ps-after.json` | 830 | `cadd8adf7ac411299db62acdd50f96c2a460c8dd6008fa05b467e583047c06ca` |
| `off-compromised/ollama-ps-before.json` | 418 | `69ed86830d6f8bfa3d78820b74a9a6c3f61cf5416879bd618a88c6e10d49dac8` |
| `off-compromised/sidecar.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `on/classifier-on.json` | 183142 | `d17e54cd296b297ab4d718a9d12285d9dd61088b04c38db7c8395b0da595d193` |
| `on/classifier-on.records.jsonl` | 122535 | `e67d7cb575bcae5081e3d09be50c0c6b24af01c13d73f1c1b8594f7f2a8d8f26` |
| `on/console-transcript.txt` | 20243 | `36779dcfa872f9370d213a31fc11f7f949f49e0262cbb18d7bfd06ac9826c494` |
| `on/gateway-status-timeline.jsonl` | 421718 | `1b3fc6a6d95cd813dbb02fb258fe00dbc87212cc9af442ad8102acbeb25642c3` |
| `on/ollama-ps-after.json` | 836 | `891dcd61550deaaf064b371ec46445f9add4bc97e0372c63cb6ba1dcf98e83b2` |
| `on/ollama-ps-before.json` | 830 | `cadd8adf7ac411299db62acdd50f96c2a460c8dd6008fa05b467e583047c06ca` |
| `on/sidecar.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `raw/91-classifier-launcher-console.txt` | 44210 | `c7d3e017e58595eac8ebc2dc9967bc81ba4cefad1a3f5f3ed1ca6b3cf66d1da2` |
| `raw/91_classifier_comparison.command.txt` | 17521 | `cc6ee5da8c7edb1f8bb4871b5589142299772993fa08772a5567936ef64accd4` |
| `raw/config-classifier.yaml` | 2931 | `58fe0f31907b03ae2311814dadfb57d1a787c1c14420057d3b39a506251b35c4` |
| `raw/config-show-off.txt` | 2887 | `4793f1a358c1bdb0e3927cc356cb2d7d4ca5c2e358432e357905669c633c5b67` |
| `raw/config-show-on.txt` | 2932 | `6e8180d5fb2255723bf4f0e9b13e9d59642e7af3f3fafbf4f878e3d400e22b2d` |
| `raw/discover.json` | 138537 | `6d54bc9e2b435822ce89cc7f63ed45d900f7b803e2352853dbf5e5220db6c921` |
| `raw/identities.json` | 2788 | `8ed3189e70aca2fd5a15858baadf339181276d17cf5ed3f1ed4050178e56ef65` |
| `raw/ollama-tags.json` | 5281 | `82d0926e7c3218773bfb906914060027a670d3d7fec6aa649bb12b05d7d71570` |
| `raw/ollama-version.json` | 20 | `3e0af2d0f8e0e9855489c55aef07186d33f4bbc39bdf89330bfcbb2ae4ab2250` |
| `raw/pmset-assertions-after.txt` | 1695 | `0435b1fb0e47e2fd28b78c7311f6a1bf9ccd57c55e5044ac78a370e5b7a645d6` |
| `raw/pmset-assertions-before.txt` | 2734 | `360856ef5a14888d86f704c59586ce9793362e4e4945c21f47f2f63e2a6906ed` |
| `raw/store-measurements-after.json` | 32665 | `01ea846473bff64f093a2c39bf6e3ce242568925d1863b441d5730db24c738a8` |
| `raw/store-measurements-before.json` | 32665 | `01ea846473bff64f093a2c39bf6e3ce242568925d1863b441d5730db24c738a8` |
| `on/decisions/*.json` (34 files) | — | sha256 of concatenated per-file sha256 digests `173d84e3b7c1543d7ff95c86aeb6ceabd0e91c50e9123e750a1334c487cc2f77` |
| `off-compromised/decisions/*.json` (209 files) | — | sha256 of concatenated per-file sha256 digests `a4542a85aee7e8c3a591d97a797231a1bfd6ec25259dd2113e2fd85e91e8fd4b` |

## G. Status

Evidence saved: canonical run files on the owner's Mac (`Model_Router/stage-a/classifier/`, launcher
`91_classifier_comparison.command`, log `91-classifier.txt`), this folder on branch `evidence/classifier-comparison`
(from `main` `08d6d3ed…`), review PR left **unmerged** by instruction. Not done in this task: a same-runtime OFF rerun,
the non-thinking-classifier or longer-timeout variants, the reasoning-budget sensitivity run, routing tuning, website
publication, PyPI package or container image.
