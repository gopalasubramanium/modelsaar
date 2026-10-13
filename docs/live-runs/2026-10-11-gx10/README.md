# Live run — 2026-10-11, MacBook Air M5 → ASUS GX10 (Ollama 0.32.13 over Tailscale)

Raw outputs of the verification described in `docs/verification-report.md` ("Live results on real
hardware"). Produced by `scripts/live_check.sh` (via `run_live_check.command`), then the detached
`run_live_eval.command` (3-deployment subset) and `run_reprobe.command` (probes after the thinking-model
fix). API keys in `summary.txt` are redacted; `home/` (config, keys, state DB) is not included.

| file | content |
|---|---|
| `00-03-*` | environment, backend version, `/api/tags`, `/api/ps` |
| `10-12-*` | `init`, `discover`, `doctor` |
| `13-probe-all.txt` | first probe pass (pre-fix: thinking models wrongly `unsupported`) |
| `14-18-*` | discover after probe (pre-fix bug: evidence not shown), `explain` dry runs |
| `21-28-*` | `/v1/models`, `test`, chat/code/stream/tools through `auto`, decisions, status |
| `30-eval-live.txt` | console of the FIRST full 8-model evaluation attempt, which was interrupted (KeyboardInterrupt when its Terminal window was closed); kept as the record of that interruption, not a result |
| `eval-live.json`, `eval-live-summary.json` | the completed detached live evaluation (subset: qwen3.6, gemma4:31b, qwen3-coder); the files cited in the verification report. Both were initially missing from the repository because `.gitignore` matched `eval-*.json` at any depth; fixed in the hardening pass (`/eval-*.json`) |
| `40-45-*` | re-probe with fixed probes, discover/doctor/explain with stored evidence |
