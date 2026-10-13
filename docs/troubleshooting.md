# Troubleshooting

Start with `modelsaar doctor` — it checks most of the items below and prints a remedy per finding.

| symptom | cause | fix |
|---|---|---|
| `doctor`: cannot reach backend | runtime not running or wrong URL | `ollama serve`; `curl http://127.0.0.1:11434/api/version`; fix `backends[].base_url` |
| `doctor`: base_url points at the container's own loopback | gateway runs in Docker with `127.0.0.1` backend | use `http://host.docker.internal:11434`; on Linux add `extra_hosts: ["host.docker.internal:host-gateway"]`; Ollama must listen on `0.0.0.0` |
| `401 missing or invalid API key` | client sends no/old key | copy `head -1 ~/.modelsaar/keys/api_keys` into the client; after `keys rotate`, restart `serve` and update clients |
| `403 admin key required` | inference key used on `/admin/*` | use `keys/admin_key` (CLI `status`/`decisions` do this automatically) |
| `404 model_not_found` | alias not advertised or deployment id misspelled | `modelsaar discover`; aliases appear only when a usable deployment backs them |
| `422 no_eligible_deployment` with `capability tools is unknown` | the runtime did not report the capability and no probe/override exists | `modelsaar probe <deployment>`; or add `deployments[] … capabilities: {tools: supported}` (operator provenance) |
| `422 … effective context 4096 < required …` | Ollama's served context is assumed 4096 | set `PARAMETER num_ctx 32768` in a Modelfile, `OLLAMA_CONTEXT_LENGTH`, or an override `context_length:`; verify with `/api/ps` while loaded |
| `422 … tool_choice=required/named` | Ollama's OpenAI layer ignores `tool_choice` | use a backend that supports it (vLLM with a tool parser), or let the client use `tool_choice: auto` |
| `422 … remote image URL` | gateway does not fetch media | send images as base64 `data:` URLs (Open WebUI does this) |
| `422 … locality policy local_only` | model is cloud-forwarded (`:cloud`) or backend declared remote | pull a local model, or deliberately set `security.locality_mode: allow_remote` |
| `503 admission_rejected` / `429` | pool/backend at capacity and queue full or timed out | raise `resource_pools[].max_concurrent` only if memory allows; clients should retry after `Retry-After` |
| Stream ends with an `error` frame | backend failed after the response started | the gateway never switches mid-stream; check `modelsaar decisions <id>`; client-side retries need their own safeguards |
| Tool calls fail on small models | model emits malformed tool JSON (known for sub-30B models) | prefer a tool-probed larger model; `auto-code`; check `probe` results |
| Open WebUI "connection failed" | URL missing `/v1`, trailing slash, or Docker networking | URL must be `http://host:8484/v1` (no trailing slash); see clients/open-webui.md |
| OpenCode cannot find model | V1/V2 config mixed, or model not declared | `modelsaar client-config opencode` vs `opencode-v2`; never mix `provider` and `providers` |
| Hermes ignores the endpoint | relying on `OPENAI_BASE_URL` | use `providers.<name>` with `key_env` in `~/.hermes/config.yaml` |
| Port already in use | another gateway or service on 8484 | change `server.port`; `doctor` reports it |
| Missing tool/reasoning parser (vLLM) | server started without `--enable-auto-tool-choice --tool-call-parser` | restart vLLM with the flags; probe reports `tools unsupported` until then |
| `config version N is not supported` | config written by a newer/older build | `modelsaar config migrate` or upgrade the package |
| `modelsaar test`: `no gateway is listening at …` | the gateway is not running on the configured port | `modelsaar serve` in another terminal (or under launchd/systemd), then `modelsaar test` |
| `error: externally-managed-environment` from the one-line installer | the installer served before 2026-10-13 fell back to `pip install --user` into the OS interpreter (Debian/Ubuntu refuse that, PEP 668) | re-run `curl -fsSL https://modelsaar.com/install.sh \| sh`: the current installer creates its own virtual environment (or fetches a pinned `uv` when your Python cannot) and never installs into the OS Python |
| `ModuleNotFoundError: No module named 'httpcore…'` (or another dependency) right after a `uv tool install` | a corrupt entry in uv's wheel cache (seen on macOS) | `uv cache clean httpcore` (or `UV_NO_CACHE=1 uv tool install --force …`), then re-run the installer |

Logs: `modelsaar serve` prints warnings only; set `observability.log_level: DEBUG` for more (still no
prompt content unless `security.log_prompts: true`, which is for debugging only).
