# Stage B Pass 1 — acceptance against the predeclared targets (Phase 7)

Targets are the ones predeclared in `docs/evaluation.md` ("Acceptance targets for a reference
configuration") and restated in the Stage B Pass 1 brief. No threshold was added or changed after
seeing results. Evaluated on **Pass 1b** (`stage-b-pass1b.json`, 2026-10-15 22:01–22:30 IST); the
original Pass 1 of 11:21 IST is the compromised, preserved run under `pass1-compromised/` and is not
scored here (its `auto` row measured a health refusal, not routing).

| # | target (predeclared) | observed on Pass 1b | result |
|---|---|---|---|
| 1 | capability violations under `auto` = 0 | 0 of 32 (fixed-fast: 1, `vis-02`; `auto` routed that task to qwen3.8) | **PASS** |
| 2 | completion rate under `auto` ≥ fixed-strong | 1.000 vs 1.000 (32/32 each) | **PASS** |
| 3 | success under `auto` ≥ fixed-strong − 0.05 | 0.938 (30/32) vs 0.906 (29/32); threshold 0.856; paired difference +0.031, 95 % CI [−0.105, +0.168] (3 tasks auto-only passes, 2 fixed-strong-only) | **PASS** (the margin is within noise: the interval includes zero) |
| 4 | deterministic routing overhead p95 < 5 ms | p95 0.5 ms from the 32 decision records (report: mean 0.37 ms, p95 0.47 ms; max 3.18 ms) | **PASS** |
| 5 | classifier timeouts < 5 % of consulted requests | classifier disabled by contract; consulted 0 | NOT APPLICABLE |

Supporting facts: `auto` selected qwen3-coder on 31 of 32 held-out tasks and qwen3.8 on `vis-02`
(the only task requiring vision; qwen3-coder was excluded as `vision unsupported`). On every task
except `vis-02` the router scored qwen3-coder 0.9555 and qwen3.8 0.938 — both with measured quality
1.00 for the inferred task — so the latency term decided. `auto` therefore reproduces fixed-fast's
outcomes on 31 tasks and avoids fixed-fast's one capability violation; against fixed-strong it is
faster (p50 377 ms vs 3443 ms) with a success difference that the data cannot distinguish from zero.

## Stage B disposition

**1. DETERMINISTIC ROUTING BASELINE ACCEPTED** — on the Pass 1b evidence, all four applicable
predeclared targets pass; the classifier stays off (Stage C design remains prepared, not run).

This disposition is **conditional on the owner accepting Pass 1b as the Pass 1 result**. The run is a
separately labelled replacement for the compromised Pass 1 (Mac idle sleep → Tailscale relay
re-establishment → one health-poll timeout → 103 refusals; see `pass1-compromised/diag/flap-findings.md`),
executed under the identical frozen contract with the same identities. Taken on its own, the original
Pass 1 would be disposition **3. STAGE B INVALID / MUST BE RERUN**, which is what Pass 1b is.

Material limits that the owner should weigh (details in `MANIFEST.md` §E): Pass 1's calibration
measurements were already in the Stage A store when Pass 1b started; the run's console transcript is
empty and the health sidecar recorded nothing (the report/checkpoint, with complete policy rows and
no health-refused records, are the health evidence); 19 SUSPECTED budget-limited events on the qwen3.6
and gemma4 sweeps are unproven because the harness records no finish reason.
