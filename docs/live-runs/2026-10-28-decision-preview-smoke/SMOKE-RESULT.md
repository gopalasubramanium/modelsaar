# Decision-model preview — one bounded live smoke test (2026-10-28, Ollama 0.40.5): COMPLETED

Three requests, no more, against the merged decision-model features of `main` `6075cdcf3b0952d4213a7899438f5fe546e95d19`
(`POST /v1/decisions`, PR #18; `routing.classifier.mode: decision`, PR #17), run **01:11:07–01:11:42 SGT** from an
**isolated preview checkout** (`<PREVIEW_CHECKOUT>`, detached at that commit, clean, `modelsaar 0.1.0`, Python 3.12.15) with an
**isolated home** (`<PREVIEW_HOME>`, `modelsaar init --endpoint <GX10 Ollama> --port 50826`, classifier set to
`enabled: true, mode: decision, backend: ollama, model: nimble-v3:latest, only_when_ambiguous: true, timeout_s: 2.0`).
Backend: the GX10's Ollama **0.40.5** over Tailscale (placement A, as every earlier run). **Not touched:** the production
`modelsaar.service`, `~/.modelsaar`, the Stage A home (`config.yaml` hash `c58ce04fa1ed9902` verified), the Pass 1 checkout
(`cf56cdd`, clean), model tags (nothing pulled, retagged or altered; `nimble-v3` and `qwen3.8` were loaded by Ollama for the
requests and unload by its own keep-alive). Mac on AC with the owner's `caffeinate -i -s` plus the launcher's own assertion.

**What this is:** a wire-contract and routing smoke test. **What it is not:** a measurement of answer quality, latency
distributions, or the classifier decision rule (one consultation establishes nothing about that rule).

## Preconditions observed (read-only)
Inventory 11 tags; `nimble-v3:latest` present, `/api/show` capabilities `["decision"]`, family qwen35, 9.0B, Q8_0, served
context 32768; `/api/ps` empty before. Discovery from the preview home: 11 deployments, **two with role `decision`**:
`ollama/nimble-v3:latest` and `ollama/d1:latest` (the discovery rule of PR #17 — `decision` without `completion`);
`modelsaar doctor`: "classifier ollama/nimble-v3:latest available (mode decision)".

## The three requests
| # | request | HTTP | time | deployment | outcome |
|---|---|---|---|---|---|
| 1 | `POST /v1/decisions`, `model: ollama/nimble-v3:latest`, one `choice` (bug / billing / account) + one `noul` question about a checkout-500 ticket | 200 | 13 s (first load of nimble-v3) | `ollama/nimble-v3:latest` (explicit) | schema valid: `label` → **billing** {bug 0.246, billing 0.753, account 0.001}, confidence 0.630; `urgent` noul 0.933; usage in 480 / out 0 |
| 2 | `POST /v1/decisions`, `model: auto`, same body | 200 | 3 s | `ollama/d1:latest` (selected among 2 eligible decision deployments; "not resident") | schema valid: `label` → **bug** {bug 0.715, billing 0.267, account 0.018}, confidence 0.573; `urgent` noul 0.927 |
| 3 | `POST /v1/chat/completions`, `model: auto`, the ambiguous prompt `thoughts?`, `max_tokens 16` | 200 | 9 s | `ollama/qwen3.8:latest` (chat routing, catalogue prior) | classifier **used, status ok**: task `conversation`, probability 0.997, 255 ms (nimble-v3 resident); signal `classifier:conversation@1.00`; routing overhead 255.7 ms |

`/admin/status` → classifier `{enabled: true, mode: decision, calls: 1, timeouts: 0, failures: 0}`. Decision records (no prompts)
in `raw/decision-*.json`; responses in `raw/*.json`; headers show `X-ModelSaar-Request-Id` / `X-ModelSaar-Deployment`.

## Observations (facts, not conclusions)
1. The two decision models disagreed on the label (nimble-v3 "billing" 0.75; d1 "bug" 0.72) for a ticket a human would
   likely file as a bug. Answer quality is not what this test measures.
2. `auto` chose `d1` although request 1 had just loaded `nimble-v3`: at decision time neither was observed resident
   (residency is refreshed on an interval), so the documented tie-break "resident first, then by id" fell to the id order
   (`d1` < `nimble-v3`). Documented behaviour; use the explicit deployment id to pick a specific decision model.
3. The classifier's one consultation took 255 ms end to end with the model resident — above the 250 ms median bound of the
   classifier decision rule in `docs/plans/measured-routing-quality.md`. One request says nothing about that rule.
4. Everything the preview page on modelsaar.com states about the live test is read from `SMOKE.json` in this folder at
   build time.

## Files
`SMOKE.json` (summary read by the site), `raw/` (responses, headers, decision records, `discover.json`, `/api/show` of
nimble-v3 with licence/modelfile stripped, `/api/ps` before/after, `config-show.txt`, `doctor.txt`, `init.txt`, `serve.log`,
pmset assertions, the launcher `102_decision_preview_smoke.command.txt` and its console). Paths are redacted to
`<RUN_ROOT>`, `<PREVIEW_CHECKOUT>`, `<PREVIEW_HOME>`, `~`; no API keys (verified by scan).
