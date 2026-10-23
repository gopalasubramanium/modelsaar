# Stage B Pass 2 (Ollama 0.40.5) — acceptance against the predeclared targets

Targets are the ones predeclared in `docs/evaluation.md` ("Acceptance targets for a reference
configuration"); none was added or changed after seeing results. Evaluated on **Pass 2**
(`stage-b-pass2.json`, 2026-10-16 14:49–15:19 IST, five deployments incl. `qwen3-coder-next`, Ollama 0.40.5).
This table is about Pass 2's own evidence. It does **not** compare with Pass 1b: that comparison is
cross-runtime (0.40.3 → 0.40.5) and cannot isolate the added model (`STAGE-B-PASS2-RESULT.md`).

| # | target (predeclared) | observed on Pass 2 | result |
|---|---|---|---|
| 1 | capability violations under `auto` = 0 | 0 of 32 (fixed-fast: 1, `vis-02`; `auto` routed that task to qwen3.8) | **PASS** |
| 2 | completion rate under `auto` ≥ fixed-strong | 1.000 vs 1.000 (32/32 each) | **PASS** |
| 3 | success under `auto` ≥ fixed-strong − 0.05 | 0.938 (30/32) vs 0.938 (30/32); threshold 0.888; paired difference 0.000, 95 % CI [−0.122, +0.122] (2 tasks auto-only passes, 2 fixed-strong-only) | **PASS** (equal; no advantage claimed either way) |
| 4 | deterministic routing overhead p95 < 5 ms | p95 0.6 ms from the 32 decision records (report: mean 0.40 ms, p95 0.57 ms; max 3.14 ms) | **PASS** |
| 5 | classifier timeouts < 5 % of consulted requests | classifier disabled by contract; consulted 0 | NOT APPLICABLE |

Supporting facts: `auto` selected qwen3-coder on 31 of 32 held-out tasks and qwen3.8 on `vis-02`; it never
selected the added `qwen3-coder-next` (its score 0.8447 trailed qwen3-coder 0.9785 and qwen3.8 0.9606 on every
non-vision task because it was not resident — residency cost 1.0 — and carries the largest load heuristic,
while all three had measured quality 1.00). Against fixed-strong, `auto` is faster (p50 407 ms vs 2986 ms)
with identical success.

## Disposition

Pass 2 was planned as "pass 1 + qwen3-coder-next" (`stage-b-plan.md` §3) to observe the residency/loading
cost case. Observation: under the frozen `quality` profile the router never chose the 80B model while a
measured-equal, resident, lighter coder was available; the four applicable predeclared targets pass on Pass
2's evidence. **The accepted Stage B disposition (1 — DETERMINISTIC ROUTING BASELINE ACCEPTED, decided on Pass
1b) is unchanged; Pass 2 does not replace Pass 1b**, the classifier stays off, and no routing change follows
from this run. Any statement combining Pass 1b and Pass 2 must carry the cross-runtime caveat.

Material limits (details in `MANIFEST.md` §E): runtime 0.40.5 with re-baselined identities; `qwen3.6:latest`
tag re-created (same blobs, new digest); 9 deployments probed (d1 added on the GX10); `console-transcript.txt`
empty (launcher log carries the stream); 17 SUSPECTED budget-limited events on the qwen3.6/gemma4 sweeps,
unproven; no sensitivity run.
