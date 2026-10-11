# Live run — 2026-10-11 18:32–19:02 IST, MacBook Air M5 → ASUS GX10 (Ollama 0.32.13 over Tailscale), commit 0f8af84

Produced by `scripts/live_verify.sh` (resumable) through `run_live_verify.command`, detached. Summarised in
`docs/verification-report.md` ("Hardening pass"). Keys are redacted (`ms*_REDACTED`); `home/` (config,
keys, state DB) is not included; `10b-config-redacted.txt` is the config with the key redacted.

| file | content |
|---|---|
| `00-03-*` | environment + commit, backend version, `/api/tags` (digests = identities), `/api/ps` |
| `10-12-*` | `init`, redacted config, `discover`, `doctor` |
| `13-probe-all.txt`, `14-discover-after-probe.txt` | offline probes of all 8 deployments, discover JSON with evidence/fingerprint inputs |
| `15-18-*` | `explain` dry runs |
| `20-serve.log`, `21-models.txt`, `22-test.txt` | gateway log, `/v1/models`, `modelsaar test` |
| `23-admin-probe-via-gateway.txt` | `POST /admin/probe` under the gateway's admission |
| `29-client-checks.txt`, `client-checks.json` | wire-level client checks (chat, stream, tool emission, tool-result continuation, session header, unsupported part) |
| `27-decisions.txt`, `28-status.txt` | decisions and status after the checks |
| `30-eval-live.txt`, `eval-live.json`, `eval-live.json.records.jsonl` | live evaluation console, report and sanitised per-request checkpoint records |
| `31-33-*` | `explain`/`discover`/`doctor` after the evaluation (stored measurements in use) |
| `50-real-clients.txt` | real clients: NOT RUN (none installed) with exact commands |
| `summary.txt` | step log with exit codes |
