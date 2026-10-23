# Stage B Pass 2 — manifest (GX10, 2026-10-16, Ollama 0.40.5; qwen3-coder-next added)

This folder holds **one run**: Stage B **Pass 2** = the Pass 1 four deployments + `ollama/qwen3-coder-next:latest`,
executed under the frozen Stage B contract except for the owner-decided deviations in §B. It is labelled
**Ollama 0.40.5**. The accepted Pass 1 result (Pass 1b, Ollama 0.40.3, `../2026-10-15-gx10-stage-b-pass1/`) is
**not superseded, not combined and not re-run**; comparisons between the two are **cross-runtime and cannot
isolate the effect of the added model**. Pass 1 (compromised) and Pass 1b stay preserved unchanged; their
hashes were verified before and after this run by the launcher.

Read `STAGE-B-PASS2-RESULT.md` first; `acceptance.md` for the predeclared targets; `environment.json`,
`deployments.json`, `capabilities.json` for the machine-readable identities; `raw/` and `baseline-ollama-0.40.5/`
for the command outputs. No keys, prompts, completions or application data are included (the 36 stored
decisions are the synthetic tasks' routing records only; `/api/show` copies have licence and modelfile text
stripped as in Stage A).

## A. Execution baseline (Pass 2)

| item | value | evidence |
|---|---|---|
| Date/time, zone | 2026-10-16 **14:49:16–15:19:29 IST** (UTC+05:30), 1813 s, exit 0; probes 14:49–14:53 | `raw/55-pass2-launcher-console.txt` |
| Owner authorisation | 13:47 IST run Pass 2 once; 14:14 IST re-baseline once under Ollama 0.40.5 then Pass 2; 14:30 IST accept the re-created `qwen3.6:latest` tag and the grown inventory | `environment.json` |
| Repository `main` at run | `906bde0ede6e74166fd1bf81cf1289703fbf011a` | `environment.json` |
| Evaluator / gateway revision | `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean checkout, `modelsaar 0.1.0`, Python 3.12.15); `src/` identical to `main` | launcher console |
| Scorer / tasks | `2026.10.12-3`; tasks sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (15 calib + 32 test) | `stage-b-pass2.json` `conditions` |
| Budgets / seed / config | max_tokens 400, temperature 0, seed 7; routing config hash `c58ce04fa1ed9902`; classifier disabled (consulted 0) | report; launcher console |
| Sandbox | `sandbox-exec` (`MODELSAAR_MACOS_SANDBOX=verify`); 5 `code_exec` tasks executed in isolation | report `sandbox` |
| Placement | A — in-process gateway on the Mac (Stage A home), GX10 Ollama over Tailscale; production `modelsaar.service` untouched; no `--allow-concurrent` | launcher |
| Ollama | **0.40.5** at `http://100.83.54.124:11434` (Pass 1b: 0.40.3) | `raw/ollama-version.json` |
| Deployments (eligible set) | qwen3.8, qwen3-coder, gemma4:31b, qwen3.6, **qwen3-coder-next** — identities equal the 0.40.5 re-baseline (5/5) | `raw/pass2-identities.json`, `deployments.json` |
| Records | 267 (75 calib + 160 test + 32 auto; probes are in the report, not the checkpoint): 263 × 200, 4 × 422 (vision exclusions); resumed 0; resume_rejected {} | `stage-b-pass2.records.jsonl` |
| Health | sidecar 358 samples 14:49:21–15:19:20, **0 unhealthy**, no `last_refresh_error`; requests_total 265, requests_failed 4 (the 422s) | `raw/gateway-status-timeline.jsonl`, `raw/sidecar.log` |
| Residency | `/api/ps` before: qwen3-coder, qwen3.8 (left by the re-baseline probes); after: qwen3-coder (32.1 GB), qwen3.8 (18.8 GB) | `raw/ollama-ps-*.json` |
| Mac | macOS 27.0.1, AC power asserted, `caffeinate -i -w <launcher>`, lid open | launcher console |
| Verification | `scripts/eval_aggregate.py stage-b-pass2.records.jsonl stage-b-pass2.json` → "all aggregates in the report match the records" (run on the canonical and on the public copy) | this folder |

## B. Deviations from the frozen Stage B contract (owner-decided)

1. **Runtime 0.40.5.** Found by the 13:58 launcher gate (`stage-b-plan.md` §2 item 4). `runtime_version` is a
   fingerprint input, so all fingerprints differ from Stage A; the owner authorised a Stage A-style identity +
   probe re-baseline (`baseline-ollama-0.40.5/`, 14:18–14:22 IST, read-only, local gateway on the Stage A home,
   probes of the five Pass 2 deployments; `54-rebaseline-console.txt`) and Pass 2 against it.
2. **`qwen3.6:latest` re-created on the GX10 (13:35 IST).** Manifest digest `096fdbd02fe6…` → `a7eb95c53bcf…`; the
   weight blobs (`FROM` lines), template, parameters and capabilities are identical to Stage A; `details.runner:
   llamacpp` was added. By the frozen rule the identity differs; the owner accepted it as Pass 2's qwen3.6
   identity (`baseline-ollama-0.40.5/BASELINE-OK`, written on the owner's instruction after the script's stricter
   rule reported `baseline_ok=false`).
3. **Inventory 8 → 11.** `d1:latest`, `nimble-v3:latest`, `embeddinggemma-2:latest` were added on the GX10
   13:17–13:33 IST. The harness's `--probe` step probes every healthy generative local deployment, so **9** were
   probed (8 + d1); `--deployments` kept sweeps and `auto` to the five. Who performed the GX10 upgrade and tag
   changes is not known from this session; nothing on the GX10 was changed by this task.
4. **Launcher form.** Harness in the foreground piped through `tee` (Pass 1 form) with `caffeinate -i -w`
   alongside; diagnostic read-only sidecar (matched the harness by venv python path; 358 samples). Despite the
   `tee`, `pass2/console-transcript.txt` is empty on the Mac (cause not established); the identical stream is in
   the launcher log (`raw/55-pass2-launcher-console.txt`: 267 `[eval]` lines + report table).

## C. Results in one paragraph

Calibration chose fixed-strong **qwen3.8** (1.000) and fixed-fast **qwen3-coder** (p50 504 ms); qwen3-coder-next
tied qwen3-coder on calibration success (0.933, one vision exclusion) at p50 755 ms. Held-out: **auto 0.938
(30/32)**, fixed-strong 0.938, fixed-fast 0.938 (1 violation), rules 0.844, random 0.781, oracle 1.000;
qwen3-coder-next sweep 0.938 (1 violation, p50 700 ms). auto vs fixed-strong paired difference **0.000, 95 % CI
[−0.122, +0.122]**; auto p50 407 ms vs 2986 ms. `auto` selected qwen3-coder 31×, qwen3.8 1× (`vis-02`) and
**never qwen3-coder-next** (score 0.8447 vs 0.9785/0.9606: not resident → residency cost 1.0, largest load
heuristic 1.0, with equal measured quality). Overhead p95 0.6 ms. 17 SUSPECTED budget-limited events, all on the
qwen3.6/gemma4 sweeps, none proven. Predeclared targets: 4 PASS, 1 N/A. Disposition unchanged (Pass 1b's).

## D. Derived files

`aggregate.json` (policies, calibration, per-deployment test, paired auto-vs-fixed-strong, residency, probes),
`routing-analysis.json` (per-task decision diagnostics incl. candidate scores), `reasoning-budget-analysis.json`
(SUSPECTED events), `acceptance.json` / `acceptance.md`, `environment.json`, `deployments.json` (identity vs
re-baseline and vs Stage A, with changed fingerprint inputs), `capabilities.json` (9 probed deployments).
Generated from the report, checkpoint and stored decisions only; descriptive; no routing change follows.

## E. Material limits

1. **Cross-runtime.** Pass 1b (0.40.3) and Pass 2 (0.40.5) differ in runtime, in the qwen3.6 tag and in the
   deployment pool at once; no difference between them is attributable to the added model, which `auto` never
   selected. Pass 1b stays the accepted Pass 1 result.
2. **Stored measurements.** 53 rows before (Stage A probes, Pass 1/1b calibration under 0.40.3 fingerprints, 5
   latency rows from the re-baseline probes), 103 after; the 0.40.5 fingerprints are new keys, so `auto` routed on
   this run's own calibration (`raw/store-measurements-*.json`).
3. **Console transcript empty** (§B 4); the launcher log carries the stream; the checkpoint is the record of truth.
4. **Budget events SUSPECTED, not proven** (no finish reason / usage recorded); the sensitivity run was not done.
5. **Path redaction.** The public copies of `stage-b-pass2.json`, `aggregate.json`, `raw/discover.json`,
   `baseline-ollama-0.40.5/discover.json` and the text logs have the Mac absolute paths replaced by
   `<EVAL_CHECKOUT>` / `<RUN_ROOT>` / `~` (Pass 1 convention). The public report equals the canonical Mac object
   once the placeholders are restored (verified); `eval_aggregate.py` passes on it; the checkpoint is byte-identical
   to the Mac original. Canonical Mac hashes: report `4358acf888a52774c98f4dc3c705f0789bb31a43c9cd1e36933a577ef85806eb`,
   checkpoint `81fa792ed321b01fc2f06e7d331e9ad921d80651f682cc3980363e36e1479e87`.
6. Two aborted launcher attempts (13:56 battery, 13:58 Ollama 0.40.3 gate) made no model request; their files are
   kept on the Mac (`pass2-aborted-*`) and are not part of this package.

## F. Hashes (sha256, public copies in this folder)

| file | bytes | sha256 |
|---|---|---|
| `STAGE-B-PASS2-RESULT.md` | 11706 | `2a1602f7aa88aca01caf50038fd8aeb8fd6d8b2915d490fe084bccf123563876` |
| `acceptance.json` | 861 | `d8e5f9fe3b6ec6a3a13abdb961dee30c77197d33a82e08dcf35c839a741c17b3` |
| `acceptance.md` | 2879 | `8c809bccb2d12ba142fa7f3acd3e85dc5c8f35795dbcb4cb608b0a43809025c7` |
| `aggregate.json` | 31757 | `90ab5c9ce198064c794f238cc84d1b681266ac5a599ef95ab2f0e25fb981d7bc` |
| `baseline-ollama-0.40.5/54-rebaseline-console.txt` | 4997 | `84d9ab21de16fe16c04b605d148e50c9999c390ee5a439db9bb905dee3302b54` |
| `baseline-ollama-0.40.5/54_rebaseline_ollama0405.command.txt` | 12433 | `82423b565b652de49d177261e87d062a0bbb832f0a9a51d58808b458fc129623` |
| `baseline-ollama-0.40.5/BASELINE-OK` | 722 | `94f6e1b535cd8f0a6c1b2aae369e9f545a2798f588a2b4dd91c601a1c8f00573` |
| `baseline-ollama-0.40.5/deployments-0.40.5.json` | 32144 | `17b3cfe31afabc2535f727e36e3a4bbd6137202d4db10cae383ef43ea0555bc9` |
| `baseline-ollama-0.40.5/discover.json` | 45420 | `58aa61adb39dd5ed37c57928ddf45610cd369936c994e3f641684895b76430e6` |
| `baseline-ollama-0.40.5/ollama-ps-after-probes.json` | 835 | `5c99c61f682bf98eef179e86aeb352b914c5a6b502593b3760fdc1624cdf671d` |
| `baseline-ollama-0.40.5/ollama-ps-before.json` | 13 | `a6fe9ec6e26a38d99fca418b69826e0238b7a2bb319ff05eb153a6fcfd1fa28d` |
| `baseline-ollama-0.40.5/ollama-tags.json` | 5281 | `82d0926e7c3218773bfb906914060027a670d3d7fec6aa649bb12b05d7d71570` |
| `baseline-ollama-0.40.5/ollama-version.json` | 20 | `3e0af2d0f8e0e9855489c55aef07186d33f4bbc39bdf89330bfcbb2ae4ab2250` |
| `baseline-ollama-0.40.5/probe.json` | 9415 | `38e2aa15d62cba03b34d25b6f1ab4fc0fb49b702e63f8ffd2866fb2564c87c7a` |
| `capabilities.json` | 10576 | `a9250a87ad92d909e3de32871a2bd1db347d5eeebeae297b3e84792a5459b3c2` |
| `deployments.json` | 5226 | `6ee2fa6ee08bd44af078c5e9777ee15524637dbb021f408cea95e3ab51b555b9` |
| `environment.json` | 5695 | `28f4f7cabcc1ea6bbdcc679c90fa38fcfba9e7205dc27e5fce22924f5dd76516` |
| `raw/55-pass2-launcher-console.txt` | 28234 | `9e47fe5471f13a26837957df08216b8291cbcec5f74deb6b15a54ddff7ec1e06` |
| `raw/55_stage_b_pass2_ollama0405.command.txt` | 15251 | `bf8933abbd229308f79b93fccd64061e0689f3b750f72a04c03954fd793f4098` |
| `raw/console-transcript.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `raw/discover.json` | 49160 | `efadb09eed38a5e57e299790004870534722bea41bdd63f5738352ca2045a6bc` |
| `raw/gateway-status-timeline.jsonl` | 314279 | `f68f353ab47ade00209b91b2568afb293238856eecfffea7340958cf8979e849` |
| `raw/ollama-ps-after.json` | 836 | `1b0c9f8f040926138879e4467fceaea123def2f5c4fcd4a41f99a45e7ad1a816` |
| `raw/ollama-ps-before.json` | 835 | `5c99c61f682bf98eef179e86aeb352b914c5a6b502593b3760fdc1624cdf671d` |
| `raw/ollama-tags.json` | 5281 | `82d0926e7c3218773bfb906914060027a670d3d7fec6aa649bb12b05d7d71570` |
| `raw/ollama-version.json` | 20 | `3e0af2d0f8e0e9855489c55aef07186d33f4bbc39bdf89330bfcbb2ae4ab2250` |
| `raw/pass2-identities.json` | 885 | `f26870f7b9c3ca458cf4644764d3217871e72e323aed25513306edb14f49f42e` |
| `raw/sidecar.log` | 1594 | `3a8a76dbe1f027cb4328434f629bd51f2ec6472c59d299394b275bacfda5e2b0` |
| `raw/store-measurements-after.json` | 25252 | `1b89b50e378b9a507ebf758745065d69b89cd823bb3f4ce67aef26c4ed93d0c2` |
| `raw/store-measurements-before.json` | 13162 | `ca022ac8ae3811aa4c9e23f26db4c36036c750236986b063138a2a52e69d414d` |
| `reasoning-budget-analysis.json` | 16881 | `bb160e9ee15e02ba7db16fbd17b234e38edc07e6a98a963c6327ad3fbccbf6c8` |
| `routing-analysis.json` | 48332 | `3ac6bcbe63f60dbebf7d17b667147812e5a214186467899e704a43d0a516fdb5` |
| `stage-b-pass2.json` | 228356 | `164333d7f9fec121462bf6eba0f7b2c701c1d492d31479e51dedbbf21eb5f081` |
| `stage-b-pass2.records.jsonl` | 145754 | `81fa792ed321b01fc2f06e7d331e9ad921d80651f682cc3980363e36e1479e87` |
| `raw/decisions/*.json` (36 files) | — | sha256 of concatenated per-file sha256 digests `443957a73836837998757caed9613aae27e85f671df71c3fdb3162b7a73a570a` |
| `baseline-ollama-0.40.5/ollama-show/*.json` (0 files; licence/modelfile stripped) | — | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## G. Status

Evidence saved: canonical run files on the owner's Mac (`Model_Router/stage-a/pass2/`, `baseline-0.40.5/`), this
folder on branch `evidence/stage-b-pass2` (from `main` `906bde0e…`). Opening or merging a pull request, any website
update and any further run are separate owner decisions. Not done in this task: Pass 1 rerun, result combination,
reasoning-budget sensitivity run, Stage C, publication.
