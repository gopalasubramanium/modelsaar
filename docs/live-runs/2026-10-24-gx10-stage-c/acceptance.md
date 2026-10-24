# Stage C (eight deployments, Ollama 0.40.5) — acceptance against the predeclared targets

Targets are the ones predeclared in `docs/evaluation.md` ("Acceptance targets for a reference configuration");
none was added or changed after seeing results. Evaluated on **Stage C** (`stage-c.json`, 2026-10-24
07:32–08:28 IST, eight deployments, classifier off, Ollama 0.40.5). This table is about Stage C's own evidence;
comparisons with Pass 1b are cross-runtime (0.40.3 → 0.40.5), and Pass 2 did not isolate the model it added.

| # | target (predeclared) | observed on Stage C | result |
|---|---|---|---|
| 1 | capability violations under `auto` = 0 | 0 of 32 (fixed-fast: 1, `vis-02`; `auto` routed that task to qwen3.8) | **PASS** |
| 2 | completion rate under `auto` ≥ fixed-strong | 1.000 vs 1.000 (32/32 each) | **PASS** |
| 3 | success under `auto` ≥ fixed-strong − 0.05 | 0.938 (30/32) vs 0.938 (30/32); threshold 0.888; identical outcomes on every task (auto selected the fixed-strong model qwen3.8 on all 32), paired difference 0.000 with no discordant task | **PASS** (identical; no advantage claimed) |
| 4 | deterministic routing overhead p95 < 5 ms | p95 0.5 ms from the 32 decision records (report: mean 0.38 ms, p95 0.52 ms; max 2.91 ms) | **PASS** |
| 5 | classifier timeouts < 5 % of consulted requests | classifier disabled by contract; consulted 0 | NOT APPLICABLE |

Supporting facts: with eight candidates the router's choice among the measured-equal top three (qwen3.8,
qwen3-coder, qwen3-coder-next — all quality 1.00) was decided by residency: qwen3.8 was resident when the
`auto` phase began (score 0.9607), qwen3-coder was not (0.9428), qwen3-coder-next was not and carries the
largest load heuristic (0.8447). The same mechanism chose qwen3-coder in Pass 1b/Pass 2, where it was the
resident one. `auto` therefore reproduced fixed-strong exactly here; against fixed-fast it avoided the one
violation at a p50 of 3.0 s instead of 0.48 s.

## Disposition

Stage C completes the roadmap's deployment stages (A: 3 characterised → B: 4 then 5 → C: 8) under one frozen
contract. **The accepted Stage B disposition (1 — DETERMINISTIC ROUTING BASELINE ACCEPTED, decided on Pass 1b)
is unchanged**; Stage C passes the four applicable targets on its own evidence and establishes no success
advantage of `auto` over the strongest single model (identical outcomes). The classifier stays off; no routing
change follows from this run. Any statement combining runs must carry the cross-runtime caveat (Pass 1b on
0.40.3) and the residency-state caveat (`auto`'s choice among measured-equal models depends on what was
resident when the phase began).

Material limits (details in `MANIFEST.md` §E): residency-state artefact; muse-glimmer vision declared but
probed unsupported (two 422s in its sweep); 40 SUSPECTED budget-limited events on the five thinking-family
sweeps, unproven; production gateway state not observable from the Mac; no sensitivity run.
