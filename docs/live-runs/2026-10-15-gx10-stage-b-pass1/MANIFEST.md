# Measured Routing Quality — Stage B Pass 1 manifest (GX10, 2026-10-15)

Deterministic routing measurement under the frozen Stage A contract (`../2026-10-14-gx10-stage-a/evaluation-contract.md`).
This folder holds **two runs that are never combined**: the replacement run **Pass 1b** (top level; the
candidate analysis dataset) and the original **Pass 1** (`pass1-compromised/`; preserved, labelled compromised).
**Owner decision 2026-10-16 11:40 IST: Pass 1b is accepted as the official Stage B Pass 1 result** (`acceptance.md`); Pass 1 stays preserved as compromised; runs are not combined. Nothing in
routing, classifier, models, Ollama, configuration or the GX10 service was changed; the GX10's production
`modelsaar.service` was not touched; the website is unchanged.

Headline: `STAGE-B-PASS1-RESULT.md`. Derived analysis: `aggregate.json` (Phase 4), `reasoning-budget-analysis.json`
(Phase 5), `routing-analysis.json` (Phase 6), `acceptance.md` / `acceptance.json` (Phase 7). Machine-readable
baseline: `environment.json`, `deployments.json`, `capabilities.json`. Raw run outputs: `raw/` and the two
byte-identical harness files `stage-b-pass1b.json` / `stage-b-pass1b.records.jsonl` (named for the run that
produced them; the brief's generic names `stage-b-pass1.*` are used for the compromised run under `pass1-compromised/`).

## A. Execution baseline (Pass 1b)

| item | value | evidence |
|---|---|---|
| Window | 2026-10-15 22:01:57 – 22:30:25 IST, 1708 s, exit 0; owner approval 21:53 IST | `raw/51-pass1b-launcher-console.txt` |
| Placement | A: in-process gateway on the Mac (Stage A home), backend GX10 Ollama over Tailscale; no `--allow-concurrent` | launcher |
| `main` at run | `3733972649449d109c573b1be084d01351cd9eb1` | `git ls-remote` |
| Evaluator / gateway | `cf56cdd3416d8c853b64111b9b40211e5b126031`, clean checkout, `modelsaar 0.1.0`, Python 3.12.15 (`src/` identical to `main`) | launcher, report `conditions.git_commit` |
| Scorer / tasks | `2026.10.12-3`; `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (47 tasks, 15 calib / 32 test) | report |
| Budgets | max_tokens 400, temperature 0, seed 7; routing config hash `c58ce04fa1ed9902`; classifier disabled | report, launcher |
| Ollama | 0.40.3 at `http://100.83.54.124:11434`; `/api/ps` empty before, qwen3-coder + qwen3.8 resident after | `raw/ollama-*.json` |
| Sandbox | `sandbox-exec` (verify mode); 5 code_exec tasks executed, 0 skipped; gate v4 passed at PR #9 head `810917d` | report `sandbox` |
| Requests | 220 scored (+28 probes); 218 × 200; 2 × 422 (vision exclusions `vis-01`, `vis-02` on qwen3-coder); resumed 0 | checkpoint |
| Mac | macOS 27.0.1; AC power asserted; `caffeinate -i`; lid open (owner) | launcher |
| GX10 host | NOT EXPOSED over the Ollama API (as in Stage A) | — |

## B. Identities (`deployments.json`)

All four selected deployments match Stage A by Ollama digest and ModelSaar fingerprint: qwen3.8:latest
`aaee06c39dcf`/`06621e3e0e6844f0` (ctx 131072 observed), qwen3-coder:latest `06c1097efce0`/`4eacb9bbc87cccbf`,
gemma4:31b `6316f0629137`/`c2a3b30b88068a13`, qwen3.6:latest `096fdbd02fe6`/`7495ed65fbf1dbd5`.
Capabilities as probed in-run: `capabilities.json` (vision unsupported on qwen3-coder; all else supported).

## C. Results (Phase 4 — reproduced from the records by `scripts/eval_aggregate.py`, "all aggregates in the report match the records")

See `STAGE-B-PASS1-RESULT.md`. Summary: auto 30/32 (0.938 [0.799, 0.983]), fixed-strong qwen3.8 29/32
(0.906), fixed-fast qwen3-coder 30/32 (0.938, 1 violation), rules 27/32, random 22/32, oracle 32/32.
auto − fixed-strong = +0.031, 95 % CI [−0.105, +0.168]; completion 1.000 vs 1.000; violations 0 vs 0;
p50 377 ms vs 3443 ms. Routing overhead p95 0.5 ms. auto selected qwen3-coder 31×, qwen3.8 1× (`vis-02`).

## D. Pass 1 (compromised) — `pass1-compromised/`

11:21:11–11:47:54 IST; 220 records, 116 × 200, 104 × 422. Cause chain (established from Mac power log,
Mac Tailscale daemon log, GX10 journal, stored decisions): idle sleep 11:44:55–11:47:34 → post-wake
Tailscale relay re-establishment → the gateway's `/api/version` health-poll connect timed out ≈11:47:45 →
all four deployments `healthy=False` → 103 refusals in 108 ms; GX10 services healthy throughout; the
exact hop that dropped the SYN is not recorded. All 104 of its 422 decisions are stored and audited
(`decisions-422-audit.md`, `diag/flap-findings.md`). Its auto/fixed-strong/fixed-fast rows measured a
refusal, not routing; its calibration split (complete) and the qwen3.6 sweep remain valid measurements.

## E. Limits (material; also in `STAGE-B-PASS1-RESULT.md`)

1. Pass 1's calibration measurements were already in the Stage A store when Pass 1b started (48 rows
   before/after, `raw/store-measurements-*.json`); no pre-Pass-1 snapshot exists; Pass 1b re-measured
   the same keys in its own calibration before the `auto` phase.
2. `raw/console-transcript.txt` is empty (harness stderr did not reach the file under `caffeinate`); the
   health sidecar recorded 0 samples and is **not** evidence of health. Health is evidenced by the
   checkpoint (no health-refused record; every policy row complete) and the report.
3. Budget-limited events are SUSPECTED (19, all on qwen3.6/gemma4 sweeps), never proven: no finish
   reason or token usage is recorded.
4. **Path redaction (2026-10-16).** The public copies of `stage-b-pass1b.json`, `pass1-compromised/stage-b-pass1.json`
   and `raw/discover.json` have the Mac absolute paths in `conditions.tasks_file`, `checkpoint` and the per-deployment
   `tasks_file` fields replaced by the placeholders `<EVAL_CHECKOUT>` (the cf56cdd checkout) and `<RUN_ROOT>` (the
   Mac run folder); nothing else in those files changed (verified by comparing the parsed objects after restoring
   the placeholders), and `scripts/eval_aggregate.py` still reports "all aggregates in the report match the records".
   The canonical Mac run files are unchanged and keep their original hashes (Pass 1b report `0f50675d9de15dfa…`,
   Pass 1 report `d72ddc6695a0a856…`); both checkpoints are byte-identical to the Mac originals. The GX10 journal
   extract lost its interactive shell header (ssh alias, GX10 home path) and has the prompt user/host neutralised;
   the journal lines themselves are unchanged. Other text outputs write the Mac home as `~`. No keys, prompts or
   application data are included; the 34 stored decisions are the synthetic tasks' routing records only.
5. Two Pass 1 reports exist. `site/facts.py` and the website still quote the 2026-10-11 result.

## F. Hashes (sha256 of the files in this folder — the public copies; canonical Mac hashes in §E item 4 and `environment.json`; `raw/decisions/` 34 files omitted from the table)

| file | bytes | sha256 |
|---|---|---|
| `STAGE-B-PASS1-RESULT.md` | 10474 | `6460af0f9c874d0c8f511c17a71e4502342b3c4e1e9bc111e7f3734506e7c9ab` |
| `acceptance.json` | 1402 | `cf165cf7dbba0ee2e82de88cbefecc2cd4ae312f29fefd35222a968a6d701f25` |
| `acceptance.md` | 3696 | `05a86d0dabf332069c0a68cec26618ef427454a265a337d496fb2d8118920038` |
| `aggregate.json` | 29572 | `585aaac6230bfc2713858a285c79c5293ba3b7f260d8c4e9166e2710ff1a40ed` |
| `capabilities.json` | 9270 | `e04d8a5dc70af4b2ffe0a53afb995670e62c4cdd0c381c3576d45069750b51c4` |
| `deployments.json` | 2723 | `166caae9e24d3094ed06529e60cbc5ae1d3498b34f5f6d8f659e066dfb25f735` |
| `environment.json` | 4121 | `438e124e4474f4bfb16c31c7b99209eb2e1f958840a6a14710d96b6402c66b57` |
| `pass1-compromised/50-pass1-launcher-console.txt` | 23128 | `4916910efc05b1457ecbad011fdab7fd1a2dd3fbecf316b1a576f65bca4e996a` |
| `pass1-compromised/console-transcript.txt` | 20541 | `08f6e0d5a4bb262d55e31075b59ed65aa3eb5c424fac639c12932eb82f68198f` |
| `pass1-compromised/decisions-422-audit.md` | 4028 | `de54814dc70db9596fe1620f6f404ad7c8378151d8ac00c20f41afe16eab7402` |
| `pass1-compromised/diag/decision-timeline.tsv` | 27417 | `c692ad3bedbe4f7bacad047e92dec55a6c9bf77c1ace5d669ef49be339a316f8` |
| `pass1-compromised/diag/flap-findings.md` | 9406 | `9803dc44bf51e11c6034dafaf4607ed47d761d0129f8838ff586f1516d7c0c66` |
| `pass1-compromised/diag/gx10-journal-2026-10-15-0614-0618utc.txt` | 31293 | `c19652e069c556f0864e6d5e50a81c8595ca9b9e9edf8de802022b84fec6a6cb` |
| `pass1-compromised/diag/mac-pmset-sleepwake.txt` | 5326 | `a32ea65a4366e0d986acfc52e5131fb219266ed5ef32215d3a8d602b75084cf1` |
| `pass1-compromised/diag/mac-tailscale-extension-log-114730-114800.txt` | 3908 | `5b5586663d36c62e1567796714ee309517f4cae70b10dca57999e239c544facc` |
| `pass1-compromised/pass1-identities.json` | 698 | `55610fac48e96fed6ea94ee7dc6df6291889091cf4f499457d27e7dd16b8fcd3` |
| `pass1-compromised/stage-b-pass1.json` | 190797 | `dd611fa83e8e533c437cbdcbd2c14dca8107e2311a69f47cea12917f2071a189` |
| `pass1-compromised/stage-b-pass1.records.jsonl` | 119919 | `6d1ca65c10c46cca5ead006c3e976c0f3c8ec3d1f4e12353f40790fc46e8803e` |
| `raw/51-pass1b-launcher-console.txt` | 2598 | `39f27fb9ee4ae3c3f9378bdd6ea75d4012d9d5233927cb9a7f106759f8806646` |
| `raw/51_stage_b_pass1b.command.txt` | 12140 | `99c18cc13f11ef671ecd7a111cb28ee7f2d0a03aa7bd9564169fac9c929413a5` |
| `raw/console-transcript.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `raw/discover.json` | 84326 | `373e18ce456344eb0b2dc9e49358ace189cfdf545488bea15233def8912cf711` |
| `raw/ollama-ps-after.json` | 836 | `27caa2264da5ae423d555e0eab7aae705b88820b3389d6eac199b56ca7b4c13b` |
| `raw/ollama-ps-before.json` | 13 | `a6fe9ec6e26a38d99fca418b69826e0238b7a2bb319ff05eb153a6fcfd1fa28d` |
| `raw/ollama-tags.json` | 3871 | `961e9c6da5f8daeadec455da9ff053eb96c68f62d557e09c08442570e94a9bc8` |
| `raw/ollama-version.json` | 20 | `390eeacbb33026a8ac714dd132b267c54afe570bef37e0cc313e0de45a779945` |
| `raw/pass1b-identities.json` | 698 | `55610fac48e96fed6ea94ee7dc6df6291889091cf4f499457d27e7dd16b8fcd3` |
| `raw/store-measurements-after.json` | 11805 | `d44b85b1429a67e43c1d2a70a3605bcccf22ca692dd17e9377e343a1c3c573b9` |
| `raw/store-measurements-before.json` | 11803 | `a35b6686ff2d11e9736a7ca06ae7df6b5b44a006c2f4ddcfb0995c0c75dc850d` |
| `reasoning-budget-analysis.json` | 16913 | `1099b75b2a2455c1e61b4dce7300d9a97f900f63a529a8fcd935d66763d79458` |
| `routing-analysis.json` | 44785 | `f1cd32ca044ef6b8b93e0ea92197aa945d9c683513f5e4f6eb6de1624aa9c0ef` |
| `stage-b-pass1b.json` | 190763 | `76285802cfeb4f9f454be2b3e98e741b8cb5c54b3d88e0f00a6f4dcf9f74d20e` |
| `stage-b-pass1b.records.jsonl` | 119526 | `482e44e7e4250acdd8a17b47f9d3030d11823abe97c508c6f2632a4cad7c9cfd` |

Evaluator/gateway source revision `cf56cdd3416d8c853b64111b9b40211e5b126031` (identical `src/` on `main`
`3733972649449d109c573b1be084d01351cd9eb1`); dataset `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c`;
scorer `2026.10.12-3`.

## G. Evidence commit / PR

Branch `evidence/stage-b-pass1` from `main` `3733972`; this folder plus one-line status pointers in
`docs/plans/measured-routing-quality.md` and `docs/evaluation.md`; no runtime code, configuration,
installer or website change. The PR is opened READY and is **not merged automatically** — the owner
reviews the Pass 1 conclusion first.
