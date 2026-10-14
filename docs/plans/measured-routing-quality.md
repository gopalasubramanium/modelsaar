# Plan: Measured Routing Quality

Status: **plan only** (2026-10-14). Nothing here has been run. It maps to the roadmap item "evaluation at
the current revision" (`docs/roadmap.md`, `docs/backlog-post-alpha.md`) and starts only when the owner
approves a GX10 window. It does not change production routing, does not download or load new models and
does not touch the GX10's `modelsaar.service`.

## Question

Does `auto` at the current revision beat the strong fixed, fast fixed and deterministic-rule policies on
held-out tasks, by how much, at what latency and routing cost — and does the optional classifier add
anything over the deterministic router?

## What exists

* Harness: `modelsaar eval --mode live` (`docs/evaluation.md`): calibration split (15 tasks) and test
  split (32 tasks) with different templates; per-deployment sweeps; policies **auto**, **fixed-strong**
  (best calibration success), **fixed-fast** (lowest calibration p50), **rules** (deterministic specialist
  mapping given the gold category — a diagnostic, not deployable), **random** (seeded) and **oracle**
  (any deployment solved it — an offline upper bound). Wilson 95 % intervals, completion rate, capability
  violations, latency, routing overhead per request from the decision record. Resumable checkpoints bound
  to task content, scorer version, budgets, routing configuration, eligible set and deployment fingerprints.
* Published result (`docs/live-runs/2026-10-11-gx10-hardening/eval-live.json`): revision `0f8af84`,
  scorer `2026.10.11-2`, three deployments (`ollama/qwen3.6:latest`, `ollama/gemma4:31b`,
  `ollama/qwen3-coder:latest`), `max_tokens 400`, temperature 0, seed 7, sandbox `sandbox-exec`. The live
  classifier was disabled. This remains the quoted benchmark until a new labelled run exists.
* GX10: Ollama with eight pulled models as recorded on 2026-10-11 (`qwen3.8:latest`, `qwen3.6:latest`,
  `qwen3.6-fast:latest`, `qwen3.6-accurate:latest`, `qwen3-coder:latest`, `qwen3-coder-next:latest`,
  `gemma4:31b`, `muse-glimmer:latest`); the gateway runs `cf56cdd` as a user service at
  `http://<lan-address>:8484/v1` and serves the owner's clients.

## Design

1. **Revision and scorer.** Current `main` (merge commit recorded in the report's `conditions.git_commit`);
   current `SCORER_VERSION`; the shipped task file (`tasks_file_sha256` recorded). One report per run,
   never merged with the 2026-10-11 result.
2. **Splits.** Calibration (15) → fixed-model baselines and `--save-measurements` evidence; test (32) →
   every reported number. **No routing weight, profile or threshold is tuned on the test split**; the
   routing configuration used for `auto` is frozen in the config file before the test sweep and its hash is
   recorded.
3. **Deployments, in stages within a budget.** Stage A (representative subset, ~45 min at the published
   per-task latencies): `qwen3.8:latest`, `qwen3-coder:latest`, `gemma4:31b` — the current default
   quality model, the coding specialist and the strongest non-Qwen general model. Stage B (only if stage A
   completes inside its budget): add `qwen3.6-fast:latest` and `qwen3-coder-next:latest`. Stage C (separate
   approval): all eight. Each stage is its own labelled report; the budget is the wall-clock allowance the
   owner grants for the window, and a stage that would exceed it is not started.
4. **Baselines.** fixed-strong, fixed-fast, rules (labelled "gold-category diagnostic"), random, oracle
   (labelled "offline upper bound"). The deployable comparison is `auto` vs fixed-strong vs fixed-fast.
5. **Classifier off/on (optional, stage A only).** Run `auto` twice with identical everything except
   `routing.classifier.enabled` (`only_when_ambiguous: true`, a small local model already pulled on the
   GX10 — the smallest of the eight by parameter size — timeout 2 s). Record: classifier model, its load
   time and resident memory from `/api/ps`, timeouts, per-request routing overhead with and without, and
   the task-success delta with its interval. **Decision rule:** the classifier stays off unless its success
   gain on the test split is positive with the interval excluding zero *and* the median routing overhead
   stays under 250 ms; otherwise the simpler router is retained.
6. **Measurements reported.** Task success per category with intervals, completion rate, capability
   violations (count and kind), first-token and total latency (p50/p95), warm vs cold (a request is tagged `cold` when the chosen candidate's residency cost in the decision record is
   non-zero, i.e. the deployment was not resident when selected), selection distribution
   of `auto` over deployments, and uncertainty (interval width; `resume_rejected` count). Exact identities:
   code commit, scorer version, task file sha256, deployment fingerprints (model, size, quantization,
   runtime, context), Ollama version, `max_tokens`, temperature, seed, reasoning/thinking settings.
7. **One additional real-client workflow.** Odysseus is the existing accessible app (owner-reported
   working). Record one short workflow through the gateway — a question, a follow-up on the same
   `session_id`, and `modelsaar decisions --limit 3` showing both requests on one deployment with
   `session_source=body:session_id`. Store the sanitised decision records (no prompts) in the run folder.
8. **Safe GX10 operation.** The evaluation runs a separate in-process gateway on a free port and refuses to
   start while the production service listens, so it must run in an approved idle window with the
   production service stopped for the window (`systemctl --user stop modelsaar.service`, restarted after),
   **or** the owner explicitly accepts shared admission; `--allow-concurrent` is not used to bypass that
   coordination. The window, start and end times are recorded in the report folder.

## Reproducible commands (on the GX10, inside the approved window)

```bash
# identities
modelsaar --version; git -C ~/modelsaar rev-parse HEAD; ollama --version; ollama list
# stage A: probes, calibration + test sweeps, auto, baselines; checkpointed and resumable
modelsaar eval --mode live --probe --save-measurements --seed 7 \
  --deployments ollama/qwen3.8:latest ollama/qwen3-coder:latest ollama/gemma4:31b \
  --out ~/eval/$(date +%F)-stageA.json --checkpoint ~/eval/$(date +%F)-stageA.records.jsonl
# classifier on (same config except routing.classifier.*), same deployments and seed
modelsaar --config ~/eval/config-classifier.yaml eval --mode live --seed 7 \
  --deployments ollama/qwen3.8:latest ollama/qwen3-coder:latest ollama/gemma4:31b \
  --out ~/eval/$(date +%F)-stageA-classifier.json
# stage B (only inside the remaining budget)
modelsaar eval --mode live --save-measurements --seed 7 \
  --deployments ollama/qwen3.8:latest ollama/qwen3-coder:latest ollama/gemma4:31b ollama/qwen3.6-fast:latest ollama/qwen3-coder-next:latest \
  --out ~/eval/$(date +%F)-stageB.json
```

Reports are added under `docs/live-runs/<date>-gx10-measured-routing/` with a README naming the window,
the revision, the scorer and every NOT RUN stage; `site/facts.py` keeps quoting the 2026-10-11 result until
a completed run is reviewed.

## Out of scope

Changing routing weights from these results, new models, new clients, website changes, a release tag.
Follow-up items go to `docs/backlog-post-alpha.md`.
