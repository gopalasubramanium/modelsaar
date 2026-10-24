# Stage C — manifest (GX10, 2026-10-24, Ollama 0.40.5; all eight roadmap deployments, classifier off)

This folder holds **one run**: Stage C of `docs/plans/measured-routing-quality.md` — the frozen Stage B harness
with all eight generative deployments the roadmap names, under the GX10's current runtime (Ollama **0.40.5**,
recorded before and after). The classifier stayed off (a classifier-ON run would be a routing-policy change and
was not authorised). Pass 1 (compromised, preserved), Pass 1b (accepted Pass 1 result, Ollama 0.40.3) and Pass 2
(Ollama 0.40.5, five deployments) are **unchanged, not combined and not re-run**; the launcher verified their
hashes before and after. Comparisons with Pass 1b are **cross-runtime**; Pass 2 **did not isolate** the effect of
adding `qwen3-coder-next` and **never selected it (0/32)**.

Read `STAGE-C-RESULT.md` first; `acceptance.md` for the predeclared targets; `environment.json`, `deployments.json`,
`capabilities.json` for identities and probes; `raw/` for the command outputs. No keys, prompts, completions or
application data (the 38 stored decisions are the synthetic tasks' routing records; `/api/show` copies have licence
and modelfile text stripped).

## A. Execution baseline

| item | value | evidence |
|---|---|---|
| Date/time, zone | 2026-10-24 **07:32:56–08:28:33 IST** (UTC+05:30), 3337 s, exit 0; probes 07:33–07:37; watchdog (115 min) not triggered | `raw/81-stage-c-launcher-console.txt` |
| Owner authorisation | 2026-10-24 01:09 IST: one Stage C run, one maintenance window ≤ 2 h, current runtime, eight roadmap tags; no tag/Ollama/config/evaluator/scorer/routing change | `environment.json` |
| Repository `main` at run | `51465a927101b51ae28c8ccaa035a6895dceb4f3` | `environment.json` |
| Evaluator / gateway revision | `cf56cdd3416d8c853b64111b9b40211e5b126031` (clean checkout, `modelsaar 0.1.0`, Python 3.12.15); `src/` identical to `main` | launcher console |
| Scorer / tasks | `2026.10.12-3`; tasks sha256 `84c34596cb64835be9d0407e6ae513e1f4dc8c7a29c5d4c141d0a9030b0a9b5c` (15 calib + 32 test) | `stage-c.json` `conditions` |
| Budgets / seed / config | max_tokens 400, temperature 0, seed 7; routing config hash `c58ce04fa1ed9902`; classifier disabled (consulted 0) | report; `raw/config-show.txt` |
| Sandbox | `sandbox-exec` (`MODELSAAR_MACOS_SANDBOX=verify`); 5 `code_exec` tasks executed in isolation | report `sandbox` |
| Placement | A — in-process gateway on the Mac (Stage A home), GX10 Ollama over Tailscale; **production `modelsaar.service` not stopped, not touched**; its `/healthz` unreachable from the Mac (HTTP 000) before and after — state NOT OBSERVED (as in Stage A) | launcher console |
| Ollama | **0.40.5** before and after (Pass 1b: 0.40.3; re-baseline and Pass 2: 0.40.5) | `raw/ollama-version*.json` |
| Deployments (eligible) | qwen3.8, qwen3.6, qwen3.6-fast, qwen3.6-accurate, qwen3-coder, qwen3-coder-next, gemma4:31b, muse-glimmer — all discovered, healthy; identities equal the 0.40.5 re-baseline (8/8); vs Stage A only qwen3.6's digest differs (tag re-created 2026-10-16) | `raw/stage-c-identities.json`, `deployments.json` |
| Inventory | 11 tags on the GX10 (unchanged since 2026-10-16); `--probe` probed 9 generative deployments (8 + d1) | `raw/ollama-tags.json`, `capabilities.json` |
| Records | 408 (120 calib + 256 test + 32 auto): 402 × 200, 6 × 422 (vision exclusions on qwen3-coder, qwen3-coder-next and muse-glimmer); resumed 0; resume_rejected {} | `stage-c.records.jsonl` |
| Health | sidecar 660 samples 07:33–08:28, **0 unhealthy**, no `last_refresh_error`; requests_total 408, requests_failed 6 (the 422s) | `raw/gateway-status-timeline.jsonl`, `raw/sidecar.log` |
| Residency | `/api/ps` empty before; after: qwen3.8 (18.8 GB) and qwen3.6-fast (24.6 GB) | `raw/ollama-ps-*.json` |
| Mac | macOS 27.0.1, AC asserted, owner's `caffeinate -i -s` (PreventUserIdleSystemSleep + PreventSystemSleep verified before/after) + launcher `caffeinate -i -w`, lid open | `raw/pmset-assertions-*.txt` |
| Verification | `scripts/eval_aggregate.py stage-c.records.jsonl stage-c.json` → "all aggregates in the report match the records" (canonical and public copy) | this folder |

## B. Differences from earlier runs (all recorded; none gated)

1. **Runtime** 0.40.5, same as Pass 2; cross-runtime vs Pass 1b (0.40.3).
2. **Identities** equal the 0.40.5 re-baseline of 2026-10-16 (`../2026-10-16-gx10-stage-b-pass2/baseline-ollama-0.40.5/`); vs
   Stage A only `qwen3.6:latest` differs (digest `096fdbd02fe6…` → `a7eb95c53bcf…`, same blobs).
3. **Pool** eight (Pass 1b 4, Pass 2 5). The sweep order ended with qwen3.6-fast, so at the `auto` phase qwen3.8 and
   qwen3.6-fast were resident; in Pass 1b/2 qwen3-coder and qwen3.8 were.
4. **Capabilities**: muse-glimmer's live vision probe returned unsupported ("image accepted but answer did not identify
   the colour") although Ollama declares vision → excluded from vision tasks under `auto`, 422 in its own sweep.
5. **Monitoring**: console transcript captured (437 lines; empty in Pass 1b/2); sidecar 660 samples.
6. **Service state**: recorded read-only (unreachable from the Mac, as in Stage A); nothing stopped or restarted.

## C. Results in one paragraph

Calibration chose fixed-strong **qwen3.8** (1.000) and fixed-fast **qwen3-coder** (p50 501 ms), as in Pass 1b/2.
Held-out: **auto 0.938 (30/32)**, fixed-strong 0.938, fixed-fast 0.938 (1 violation), rules 0.844, random 0.812,
oracle 1.000. **`auto` selected qwen3.8 on all 32 tasks**, so auto ≡ fixed-strong (paired difference 0.000, no
discordant task; p50 3.0 s). The choice among the measured-equal top three (qwen3.8 0.9607, qwen3-coder 0.9428,
qwen3-coder-next 0.8447) was decided by residency state at decision time (qwen3.8 resident; the coders not) —
the mirror image of Pass 1b/2, where qwen3-coder was resident and chosen 31/32. Sweeps: qwen3.8, gemma4, both
coders 0.938; muse-glimmer 0.688 (p50 22 s); qwen3.6 variants 0.56–0.59. Overhead p95 0.5 ms. 40 SUSPECTED
budget-limited events on the five thinking-family sweeps, none proven, none under `auto`. Predeclared targets:
4 PASS, 1 N/A; disposition unchanged (Pass 1b's).

## D. Derived files

`aggregate.json`, `routing-analysis.json` (per-task candidate scores and exclusions), `reasoning-budget-analysis.json`,
`acceptance.json` / `acceptance.md`, `environment.json`, `deployments.json`, `capabilities.json` (9 probed). Generated
from the report, checkpoint and stored decisions only; descriptive; no routing change follows.

## E. Material limits

1. **Cross-runtime vs Pass 1b**; Pass 2 did not isolate its added model and never selected it.
2. **Residency-state artefact**: `auto`'s choice among measured-equal candidates followed which models the harness
   had left resident; the runs do not measure routing under realistic residency churn.
3. **Probe vs declaration** for muse-glimmer's vision (above).
4. **Budget events SUSPECTED**, not proven (no finish reason / usage recorded); no sensitivity run.
5. **Production gateway not observable from the Mac** (HTTP 000 both addresses) — never contacted by placement A.
6. **Path redaction**: public copies of `stage-c.json`, `aggregate.json`, `raw/discover.json`, the decisions and the text
   logs replace the Mac absolute paths by `<EVAL_CHECKOUT>` / `<RUN_ROOT>` / `~`; the public report equals the canonical
   Mac object once the placeholders are restored (verified); the checkpoint is byte-identical. Canonical Mac hashes:
   report `f7cdd2e8d1d4edda613886351b5f9edc8f5cfbc3278f2286c7895d549ad45972`, checkpoint
   `1bf93d845d88d647d35e827282d7cfd5cea7e50b8ff1dc5028f6d8836cd67353`.

## F. Hashes (sha256, public copies in this folder)

| file | bytes | sha256 |
|---|---|---|
| `STAGE-C-RESULT.md` | 10100 | `5b90ca6e478e99d01609ce0bbf04b99cbe9e33a209e7c9526a1444326f0c2a7c` |
| `acceptance.json` | 857 | `e359fef168b8573f653e048ca64140701cbefadf121aaa19281cfcc3314b903e` |
| `acceptance.md` | 2986 | `2f332c97f9140f4091e5fb25b7f4a513cc23660d4d93816c15692d0b1d5ca79c` |
| `aggregate.json` | 23273 | `08328a9b0c206cf0bfb775897f08d5987ce0b74fd9c1a3a017b0c8c8b4a0d6fc` |
| `capabilities.json` | 10741 | `e98c4d7fe2e534ed56bc0d665c74049798daa22da8485e2764b82bda9a2a83b9` |
| `deployments.json` | 5637 | `5f56b68a65991c27e0634ded558211176845b0cce94110a58e35050a48f16f35` |
| `environment.json` | 6437 | `5542ab2e12c991516238011df090e44633e8688be4d64f6ca846b9375f2e5b15` |
| `raw/81-stage-c-launcher-console.txt` | 40389 | `34c7c7cc1cfe7ffad590005574a1e2a89bbd4aa3793f4717fa3e88ac98a550ec` |
| `raw/81_stage_c.command.txt` | 17332 | `87472310197d0ba0568d1e303179930106c9b009f5afff2db523e186fca06f86` |
| `raw/config-show.txt` | 2887 | `4793f1a358c1bdb0e3927cc356cb2d7d4ca5c2e358432e357905669c633c5b67` |
| `raw/console-transcript.txt` | 35095 | `70311d77dfbcf5171a71433c49f5b85fb1ffaeb1d9f31cdf41cd732572af5662` |
| `raw/discover.json` | 105047 | `19e72853a6c15f3dee0ab448416bf83bd2ec10addc6e3f20f7d74b2efd7842cd` |
| `raw/gateway-status-timeline.jsonl` | 579682 | `58e6486ebb54c6e5ae6dea4e901b4e85d41375fe5b2b3bbaca3a52bd05f593c5` |
| `raw/ollama-ps-after.json` | 839 | `fcd9ce1c1a48ddc561071f1ec422ff9c69cab4b422acbe06f71ebf8bbcc9a135` |
| `raw/ollama-ps-before.json` | 13 | `a6fe9ec6e26a38d99fca418b69826e0238b7a2bb319ff05eb153a6fcfd1fa28d` |
| `raw/ollama-tags.json` | 5281 | `82d0926e7c3218773bfb906914060027a670d3d7fec6aa649bb12b05d7d71570` |
| `raw/ollama-version-after.json` | 20 | `3e0af2d0f8e0e9855489c55aef07186d33f4bbc39bdf89330bfcbb2ae4ab2250` |
| `raw/ollama-version.json` | 20 | `3e0af2d0f8e0e9855489c55aef07186d33f4bbc39bdf89330bfcbb2ae4ab2250` |
| `raw/pmset-assertions-after.txt` | 3124 | `3ce6e8ce33c78c77fbc22feae6a2c7915f1ddeb82eb4663bdd1bd710b46b5d94` |
| `raw/pmset-assertions-before.txt` | 3614 | `bc4875d9c202e754351e55e9e0b2834834a56a571b4d947e19b413440d53d777` |
| `raw/sidecar.log` | 2972 | `e20bcc406ccce7240b6e1c112388cc36674240aae3785c76dee1023a6162f7f7` |
| `raw/stage-c-identities.json` | 9010 | `545bb2823f8a606c1032173364060dfff92684bdd4fcb4d54f62f762efcaf949` |
| `raw/store-measurements-after.json` | 32665 | `01ea846473bff64f093a2c39bf6e3ce242568925d1863b441d5730db24c738a8` |
| `raw/store-measurements-before.json` | 25252 | `1b89b50e378b9a507ebf758745065d69b89cd823bb3f4ce67aef26c4ed93d0c2` |
| `reasoning-budget-analysis.json` | 38701 | `0ab111fafe5b0e510727cc9a4b276ededccd706b1779f7dabb45370a5db92718` |
| `routing-analysis.json` | 57213 | `a9dd967a084457585e49cb03ff5881e94219ab31b40f8a48e3445677018e4ae7` |
| `stage-c.json` | 336990 | `78efb3d0c2ed817a379aff6e82415f429c89285e92b73071d6f9e604086921b3` |
| `stage-c.records.jsonl` | 224662 | `1bf93d845d88d647d35e827282d7cfd5cea7e50b8ff1dc5028f6d8836cd67353` |
| `raw/decisions/*.json` (38 files) | — | sha256 of concatenated per-file sha256 digests `3aab88708667290468fd50793770e512ee5e85d6e3cd236c1d3fa7b2a6debf43` |
| `raw/ollama-show/*.json` (11 files; licence/modelfile stripped) | — | `3aefcd377a8b6dda5e889a86e53de76b9d0feeb83fac4ff628b80bb1c3d5769f` |

## G. Status

Evidence saved: canonical run files on the owner's Mac (`Model_Router/stage-a/stage-c/`), this folder on branch
`evidence/stage-c` (from `main` `51465a92…`). Not done in this task: reasoning-budget sensitivity run, classifier-ON run,
routing change, Pass 1/1b/2 rerun, PyPI package or container image.
