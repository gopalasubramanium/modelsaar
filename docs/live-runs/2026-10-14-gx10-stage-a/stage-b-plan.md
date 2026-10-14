# Stage B — safe execution plan (prepared in Stage A; NOT scheduled, NOT started)

Stage B runs the frozen harness (`evaluation-contract.md`) on the Stage A subset (`model-subset.md`)
once, in an owner-approved idle window. Nothing below changes routing, the classifier, models, Ollama
or the GX10 service beyond what §1 says explicitly.

## 1. Where it runs and what happens to production

Two admissible placements; the owner picks one when approving the window.

| | **A. From the Mac (as Stage A ran)** | **B. On the GX10 host** |
|---|---|---|
| gateway used | the harness's own in-process gateway on the Mac (free loopback port, its own admission, Stage A home `~/.modelsaar-stage-a`) | the harness's own in-process gateway on the GX10 (free port) using the production config/keys |
| production `modelsaar.service` | **left running, untouched**; it is not on the Mac's port so `run_live` does not refuse | must be **stopped for the window** (`systemctl --user stop modelsaar.service`, restart after): `run_live` refuses to start while a gateway listens on the configured address, and the refusal is correct — two gateways would run uncoordinated inference on one GPU |
| admission coordination | within the run: complete (one gateway). Against production: **none** — if a client (Odysseus) sends requests during the window they compete for the GPU and contaminate both latencies | complete (production stopped) |
| code_exec tasks (5) | macOS `sandbox-exec` is **disabled in the alpha** unless the owner first runs the verification (`MODELSAAR_MACOS_SANDBOX=verify`, `run_mac_tests.command`); otherwise the 5 tasks are skipped and reported | needs bubblewrap on the GX10 (presence NOT KNOWN — not exposed over the API); otherwise skipped and reported |
| network path | Tailscale Mac→GX10 adds latency to every request (Stage A: NOT separately measured); affects latency columns of every policy equally, not success | none |
| GX10 changes | none | service stop/start for the window only; config untouched |

`--allow-concurrent` is **not** to be used in either placement: it exists to acknowledge an unrelated
listener on the same port, not to run a benchmark beside the production gateway; using it would make the
harness's admission accounting (pool memory, queue, residency) wrong for the whole run.

Recommended: **A** with an explicit idle window (no client use for its duration) and, before it, the
owner's one-time `sandbox-exec` verification so `code_exec` tasks are scored; fall back to **B** only if
the Tailscale path proves unstable.

## 2. Preconditions checked at the start of the window (read-only)

1. `ollama /api/ps` empty or only models the owner accepts to evict; record it.
2. `modelsaar discover --json` from the run home: 8 deployments, fingerprints equal to
   `deployments.json` (a changed digest = re-run Stage A identity for that model).
3. Context: `run_live` discovers before each sweep; a model never loaded reports the assumed 4096 until
   it has been seen in `/api/ps`. To avoid eligibility flapping, the run uses `--probe` (loads every
   subset model once, so `/api/ps` context is observed) and records `context_length` per deployment from
   the report's `deployments` list. No operator context override is added in Stage B (that would be a
   config change requiring approval and a new routing-config hash).
4. Ollama version still `0.40.3` (a change invalidates the Stage A identities' runtime field).

## 3. Commands (reproducible; run inside the window)

```bash
# placement A, on the Mac; EXE = the cf56cdd executable used in Stage A
export MODELSAAR_HOME=~/.modelsaar-stage-a/.modelsaar
EXE=~/.modelsaar-install-test/public-20261013-145747/.local/share/modelsaar/envs/current/bin/modelsaar
$EXE --version; curl -s http://100.83.54.124:11434/api/version; curl -s http://100.83.54.124:11434/api/ps
$EXE discover --json > stage-b-discover.json
# Stage B pass 1: 4 deployments, probes first, measurements saved to the Stage A home's store only
$EXE eval --mode live --probe --save-measurements --seed 7 \
  --deployments ollama/qwen3.8:latest ollama/qwen3-coder:latest ollama/gemma4:31b ollama/qwen3.6:latest \
  --out stage-b-pass1.json --checkpoint stage-b-pass1.records.jsonl
# pass 2 (only inside the remaining budget): add qwen3-coder-next
$EXE eval --mode live --probe --save-measurements --seed 7 \
  --deployments ollama/qwen3.8:latest ollama/qwen3-coder:latest ollama/gemma4:31b ollama/qwen3.6:latest ollama/qwen3-coder-next:latest \
  --out stage-b-pass2.json --checkpoint stage-b-pass2.records.jsonl
```

`--save-measurements` writes evidence into the **Stage A home's** state DB on the Mac, never into the
GX10's production state; production routing is unchanged by Stage B.

## 4. Expected cost (estimates from Stage A smoke latencies and the 2026-10-11 run; not measurements)

| | pass 1 (4 deployments) | pass 2 (5 deployments) |
|---|---|---|
| requests | probes 4×7 = 28; calib 15×4 = 60; test 32×4 = 128; auto 32 → **≈ 250** | 35 + 75 + 160 + 32 → **≈ 300** |
| tokens (upper bound) | ≤ 400 output + ~150 input per request → ≤ ~140 k; realistic ~80–100 k (coder answers are short; thinking models often hit the 400 cap) | ≤ ~165 k |
| wall-clock | per-deployment sweeps: qwen3-coder ~1 min, qwen3.8 ~3 min, qwen3.6 ~5 min, gemma4 ~15 min (p50 17.8 s in 2026-10-11 calib); auto ~4 min; probes ~6 min; loads 7–13 s per switch → **≈ 35–45 min** | + qwen3-coder-next ~3 min + 13 s loads → **≈ 45–55 min** |
| GPU / residency | Ollama 0.40.3 kept two models resident at once during Stage A (e.g. qwen3.8 18.5 GB + the active one 19–25 GB); each sweep loads one model; qwen3-coder-next needs 51.7 GB resident | |
| storage | report JSON ≈ 150–300 KB; checkpoint JSONL ≈ 100–200 KB; no prompts stored | |
| recommended window | **90 minutes** of no client use, pass 2 included; abort pass 2 if pass 1 exceeds 60 min | |

## 5. Interruption, recovery, restore

- Checkpoints: `--checkpoint` records every request; re-running with `--resume` skips records whose
  `conditions_key` (scorer, budgets, routing config hash, eligible set, deployment fingerprints) still
  matches; anything else is re-run and counted under `resume_rejected`. A pass is one report; passes are
  never merged.
- If the harness stops (Tailscale drop, timeout): re-run the same command with `--resume`; the
  in-process gateway restarts on a new free port automatically.
- Restore: placement A needs no restore (production untouched). Placement B: `systemctl --user start
  modelsaar.service`, then `curl http://192.168.0.12:8484/healthz` and one `modelsaar test --model auto`.
- Retained: the two report JSONs, checkpoint JSONL (sanitised: ids, status, latency, scorer detail),
  `stage-b-discover.json`, `/api/ps` snapshots, the console transcript. **Not retained:** prompts and
  completions (the harness never writes them), keys, the Stage A home.

## 6. Stage C design (classifier OFF vs ON) — prepared only

- OFF = Stage B pass 1 `auto` result (deterministic router).
- ON = the same deployment pool, tasks, budgets and seed with `routing.classifier.enabled: true`,
  `backend: ollama`, `model: <the smallest subset model by weights — qwen3.8 at 17.7 GB, or qwen3-coder
  at 18.6 GB as the non-thinking option>`, `timeout_s 2.0`, `only_when_ambiguous true` (the classifier is
  consulted only for tasks the deterministic requirements call ambiguous — the `ambig-*` tasks — after
  eligibility, and refines the task label only). This is a **different routing config hash**, so it is a
  separate report, never resumed from the OFF checkpoint.
- Compare: test success and interval, routing overhead mean/p95, classifier `status` counts
  (used/skipped/unavailable/timeout) from decision records, the classifier model's residency and
  `size_vram`, and the selection distribution. Decision rule (from `docs/plans/measured-routing-quality.md`):
  keep the classifier off unless success improves with the interval excluding zero and median overhead
  stays under 250 ms.
- Not executed in Stage A or Stage B.
