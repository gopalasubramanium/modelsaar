# Pass 1 — audit of the 72 non-`auto` HTTP 422 decisions (read-only; 2026-10-15 15:06 IST)

Source: `~/.modelsaar-stage-a/.modelsaar/state/modelsaar.db` opened read-only (URI `mode=ro`) by
`61_collect_422_decisions.command`; no gateway, no network, no inference. Records written as new files under
`pass1/decisions-422/<request_id>.json` (each carries `_checkpoint` = the matching checkpoint record's index,
policy, task, split, status, detail, and `_store_created_at`). Existing evidence unchanged: `stage-b-pass1.json`
sha256 d72ddc66…, `stage-b-pass1.records.jsonl` sha256 6d1ca65c…, `pass1/decisions/` 32 files (before and after).

## Matching
- Checkpoint: 220 records; non-`auto` HTTP 422: 72 (71 test-sweep + 1 calibration), all with a `request_id`.
- Store: 260 decisions in total (span 2026-10-14 … 2026-10-15 11:47:54); all 220 Pass 1 request_ids present.
- Found and matched: **72 of 72; 0 missing, 0 unmatched.** Every record: `outcome no_eligible`, `candidates []`,
  `chosen null`, `explicit true`, `requested_model` = the sweep's deployment, `config_hash c58ce04fa1ed9902`,
  reason "no deployment satisfies all hard requirements".

## Exclusion reasons (71 sweep decisions; an explicit deployment request evaluates only that deployment, so each
## decision has exactly one excluded deployment)
| group | reason | count |
|---|---|---|
| backend health | `backend unhealthy: ollama: ConnectTimeout: ` | **71 / 71** (gemma4:31b 7, qwen3.8 32, qwen3-coder 32) |
| capability | `image input required; capability vision is unsupported (source_claim)` | 1 (test qwen3-coder `vis-02`, listed alongside the unhealthy reason) |
| other | — | 0 |

- `registry_version` 13 on all 71 — the same registry generation as the 32 `auto` decisions.
- `created_at` 11:47:54.575 → 11:47:54.654 (79 ms for all 71); the 32 `auto` decisions follow at 11:47:54.656 → .683.
  The whole 103-request cascade (sweep + auto) took 108 ms, immediately after test gemma4 `ambig-03`
  (HTTP 200, 43.6 s) — shorter than one `residency_refresh_s` (15 s) health-poll interval.
- Routing overhead 0.03–3.6 ms; no backend contact (consistent with the 0.0 s console latencies).

**Same state as the auto failures: yes.** The `auto` decisions show all four deployments of backend `ollama`
unhealthy with the identical `ConnectTimeout` message; each explicit sweep request shows its own deployment
excluded for the identical reason, in the same registry generation, in the same sub-second window. The sweeps'
HTTP 422s are not a different failure.

## Calibration failure (1)
`req_216689be356b452d`, calib qwen3-coder `vis-01`, 11:33:58.829, registry_version 7, overhead 0.35 ms:
exclusion `image input required; capability vision is unsupported (source_claim)` only; requirements
`needs_vision true`, images 1; remedy "use a deployment whose vision capability is supported". The backend was
healthy at that time (no health reason). **This is a legitimate capability exclusion:** qwen3-coder declares no
vision (Stage A: declared, not probed), and the task carries an image. It is unrelated to the later cascade.

## Evidence limits
- The `ConnectTimeout` message carries no detail (httpx's empty exception text); the records show the gateway's
  state, not the cause of the one failed `/api/version` TCP connect (Tailscale path vs. GX10 accept during the
  43.6 s gemma4 generation). The gemma4 request on its existing connection completed (HTTP 200) while the
  gateway's new connection timed out — an observation, not a diagnosis.
- No gateway log for the run exists (the harness's in-process gateway); an unhealthy poll is state, not an
  exception, so the console transcript has no trace of it. The decisions' `created_at` are the only timestamps.
- The `DELETE … created_at < now-7d` retention runs on insert; nothing was inserted here, but store contents are
  not permanent — the dumped files are the durable copy.
- This audit reports what the records contain; it does not classify the Pass 1 run as valid or invalid.
