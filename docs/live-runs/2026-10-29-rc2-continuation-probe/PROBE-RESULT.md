# `v0.1.0-rc.2` continuation probe — one bounded live run (2026-10-29, Ollama 0.40.5): `supported`

One probe, no more, of the `continuation` capability shipped in the GitHub pre-release **`v0.1.0-rc.2`** (annotated tag on
`main` commit `7e7579825a2d37c238b04fbbb2d3a225119600f0`, verified from the remote before the run), executed **20:40:47 SGT**
on the GX10 (aarch64, Python 3.12.3) from an **isolated RC2 checkout** (`<RC2_CHECKOUT>`, detached at the tag, clean,
`modelsaar 0.1.0`, `continuation` present in `PROBE_NAMES`) with an **isolated home** (`<RC2_HOME>`, `modelsaar init
--endpoint http://127.0.0.1:11434 --type ollama --port 8486`, then `server.host` set to the GX10's LAN address and
`security.allow_lan: true`; **no `deployments[]` override of any kind** — `deployments: []`, asserted before the probe).
Gateway run as a plain background process (`setsid nohup modelsaar serve`), listening on `<GX10_LAN_IP>:8486` only.
**Not touched:** the production `modelsaar.service` (pid 3756, port 8484; active before and after), `~/.modelsaar`
(`config.yaml` mtime 2026-10-14 01:06:36 unchanged), the rc.1 process on port 8485 (pid 1516183; running before and after),
Ollama, model tags, firewall, the installer pin, the release tags, the evaluator/scorer.

**What this is:** a protocol-acceptance check of one deployment through the gateway's own admission-coordinated probe path.
**What it is not:** proof that the model uses the replayed reasoning, a statement about any other model or runtime, a
latency measurement, a benchmark, or an end-to-end real-client test of this candidate.

## Preconditions observed (read-only)
Ollama 0.40.5, 11 tags, `qwen3.8:latest` present; `/api/ps` empty (nothing resident). Discovery from the RC2 home: 11
deployments; `ollama/qwen3.8:latest` generative, `ctx=4096` (pre-load default), tools/vision supported, healthy, local.
`modelsaar doctor`: 0 failures. `/admin/status` **before the probe**, deployment `ollama/qwen3.8:latest` (family qwen35,
27.3B, Q4_K_M, identity = Ollama digest `aaee06c3…`, fingerprint `d004025f23bf51de`):
`continuation: {value: unknown, provenance: none}` — i.e. the state in which every follow-up turn carrying
`reasoning_content` would be refused with `422 no_eligible_deployment`.

## The one probe
```
modelsaar probe ollama/qwen3.8:latest --which continuation
```
(run exactly once; `--json` appended for the record — the same single request). The CLI found the gateway listening and
sent the probe through `POST /admin/probe` (admission-coordinated). The probe forwards the fixed three-message history from
`probes.py` (user → assistant with `content` **and** `reasoning_content` → user) to the backend unchanged.

| field | value |
|---|---|
| deployment | `ollama/qwen3.8:latest` (fingerprint `d004025f23bf51de`) |
| capability | `continuation` |
| **value** | **`supported`** |
| backend response | one `POST /v1/chat/completions` → HTTP 200 with a well-formed assistant message (`raw/serve.log`, 20:40:57 local) |
| latency | 9738 ms — includes the first load of `qwen3.8` (resident with 18.8 GB afterwards) |
| note (verbatim) | accepted an assistant history carrying reasoning_content and answered (protocol acceptance; whether the model semantically uses the replayed reasoning is not verifiable through the OpenAI-compatible API) |
| details | `answer_mentions_7: true` (diagnostic only; see below) |
| uncertain / errors / skipped | false / none / none |
| request id | none — a probe is an admin action inside the gateway, not a `/v1` request, so no `X-ModelSaar-Request-Id` is issued |

`/admin/status` **after the probe**: `continuation: {value: supported, provenance: probe, checked_at: 2026-10-29T12:40:57Z}`;
registry version 1 → 2; the `probes` table holds exactly one `continuation` row for this deployment and fingerprint
(`raw/probes-table.json`). The gateway stayed healthy; production and the rc.1 process were re-checked afterwards.

## What it establishes — and what it does not
* **Established:** *protocol acceptance.* Ollama 0.40.5 serving `qwen3.8:latest` accepted a history whose assistant turn
  carries `reasoning_content` and answered it. On this candidate that deployment is therefore eligible for such follow-up
  turns **without an operator override**, and the remedy printed for the `422` now points at a probe that works.
* **Not established:** that the model *semantically* uses the replayed reasoning. The OpenAI-compatible API offers no way
  to check that; `answer_mentions_7` only records that the answer contained "7", which follows from the replayed `content`
  ("4") alone. Nothing here speaks for other models or runtimes (each deployment is probed on its own fingerprint), for
  answer quality or latency (one sample, including a model load), or for a real client's follow-up turn end to end on
  this candidate (the earlier real-client runs used rc.1 with an override).

## Observations (facts, not conclusions)
1. After the load, the gateway's observed served context for `qwen3.8` changed from 4096 to 131072 — the documented
   residency refresh reading the running model; unrelated to the probe's result.
2. The probe's latency is one sample that includes the model load; it is not a measurement.

## Files
`PROBE.json` (summary read by the website at build time), `raw/` (`probe-stdout.txt` with the human report and the `--json`
report, `probes-table.json`, `admin-status-before.trimmed.json` / `admin-status-after.trimmed.json` (one deployment,
security block, no keys), `serve.log`, `config-trimmed.json` (server/security/backends/deployments — no secrets),
`init.txt`, `discover.txt`, `doctor.txt`, the launcher `124_rc2_probe_on_gx10.command.txt` and its console
`124-launcher-console.txt`). Paths are redacted to `<RC2_CHECKOUT>`, `<RC2_HOME>`, `<RC1_HOME>`, `~`, `<GX10_LAN_IP>`,
`<GX10_HOST>`; no API keys (verified by scan); no prompts or answers beyond the fixed probe fixture in `probes.py`.
