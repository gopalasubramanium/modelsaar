# Classifier OFF vs ON (Ollama 0.40.5) — acceptance against the predeclared targets and the decision rule

Targets are the ones predeclared in `docs/evaluation.md` ("Acceptance targets for a reference configuration");
the decision rule is the one written in `docs/plans/measured-routing-quality.md` item 5 and
`../2026-10-14-gx10-stage-a/stage-b-plan.md` §6 before any classifier run existed. Nothing was added or changed
after seeing results. Evaluated on the **ON run** (`on/classifier-on.json`, 2026-10-25 03:30–04:08 IST); the OFF
side of the rule is **Stage B Pass 1b `auto`** as §6 defines it (Ollama 0.40.3 → cross-runtime). The same-session
OFF twin (`off-compromised/`) is compromised by a backend health flap and is not used.

| # | target (predeclared) | observed on the ON run | result |
|---|---|---|---|
| 1 | capability violations under `auto` = 0 | 0 of 32 (fixed-fast: 1, `vis-02`; `auto` routed it to qwen3.8) | **PASS** |
| 2 | completion rate under `auto` ≥ fixed-strong | 1.000 vs 1.000 (32/32 each) | **PASS** |
| 3 | success under `auto` ≥ fixed-strong − 0.05 | 0.938 (30/32) vs 0.938 (30/32); threshold 0.888 | **PASS** |
| 4 | routing overhead with classifier: p95 < `classifier.timeout_s` (2000 ms) | p95 **2003.52 ms** (report); the six consulted requests recorded 2002.3–2004.5 ms each — the 2.0 s wait plus bookkeeping; median 0.55 ms | **FAIL (marginal, 2–4 ms over)** |
| 5 | classifier timeouts < 5 % of consulted requests | **6 of 6** consulted `auto` requests timed out (100 %); gateway-wide 38 of 38 calls, 0 other failures; classifier model resident throughout | **FAIL** |
| 6 | decision rule: enable only if success gain > 0 with the 95 % interval excluding zero **and** median routing overhead < 250 ms | gain **0.000** (30/32 vs Pass 1b 30/32; identical outcomes on every task; paired interval [0, 0]); median overhead 0.55 ms (< 250 ms, but only because 26 of 32 tasks skipped the classifier) | **KEEP OFF** |

Supporting facts: the classifier (`qwen3.8:latest`, 18.8 GB resident in every `/api/ps` snapshot) returned no
label in the whole run, so ON reproduced OFF's task labels, selections (qwen3-coder 31, qwen3.8 1) and outcomes
exactly. Its only measurable effects were the 2.0 s decision wait on the six ambiguous tasks and an
unattributed ≈ 20 s end-to-end stall on those same requests under every policy (see the result document; cause
not established).

## Disposition

**The accepted Stage B disposition (1 — DETERMINISTIC ROUTING BASELINE ACCEPTED, decided on Pass 1b) is
unchanged; the classifier stays off.** This comparison adds no evidence of value from the classifier and two
pieces of evidence against this configuration (100 % timeouts; the stall). It does not show that a classifier
with a non-thinking model or a longer timeout would fail or succeed — that would be a different experiment with
its own contract, not run here.

Material limits (details in `MANIFEST.md` §E and the result document): no same-runtime OFF reference (twin
compromised; rule evaluated cross-runtime against Pass 1b); classifier never effective (38/38 timeouts);
≈ 20 s unattributed stall per consulted request; n = 32 with six ambiguous tasks; harness has no back-off while
the backend is unhealthy; production gateway not observed.
