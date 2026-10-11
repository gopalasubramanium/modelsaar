# Privacy and security

ModelSaar implements security as product behaviour. Defaults, what they guarantee, and what they
cannot.

## Defaults

| control | default | where |
|---|---|---|
| Bind address | `127.0.0.1` (loopback). Non-loopback requires `security.allow_lan: true` explicitly; config load fails otherwise | `server.host`, `security.allow_lan` |
| Authentication | Generated inference key(s) and a separate admin key (mode 600). No default/universal key exists | `keys/api_keys`, `keys/admin_key` |
| Admin vs inference authority | `/admin/*` requires the admin key; an inference key is rejected (403). The admin key is also accepted on inference routes (one-way separation): keep it on the host only | `security.py` |
| Execution locality | `local_only`: only deployments with locality `local` are eligible or advertised. Ollama cloud-forwarded models (`remote_model`/`remote_host`, `:cloud` names) are classified `remote` with the evidence recorded; generic endpoints carry the operator's declaration as a stated trust assumption | `security.locality_mode` |
| Backend destinations | Adapters only build paths relative to the configured `base_url`; absolute or protocol-relative paths raise; redirects are not followed; hosts are allow-listed | `adapters/base.py` |
| Remote media | Never fetched. Requests with `http(s)` image URLs are rejected with a remedy (send `data:` URLs) | `security.fetch_remote_media: false` |
| Prompt logging | Off. Decision records hold metadata only (task labels, token counts, capability flags) plus at most a short redacted upstream error excerpt (≤200 chars) when a backend fails. Error messages are redacted for key-like strings | `security.log_prompts`, `security.redact` |
| Caches | No response cache, no prompt-derived cache. Affinity is scoped per caller and holds only a deployment id | `routing/affinity.py` |
| Telemetry / learning | None. `security.telemetry_opt_in` exists for future opt-in features; nothing is sent anywhere | |
| Request size | 32 MiB limit; unknown fields rejected rather than forwarded | `server.max_request_bytes` |
| Untrusted content | Prompts, tool outputs, model cards and classifier output are data. Classifier output is schema-validated against a closed label set and can only refine a task label | `routing/classifier.py` |
| Payload-bearing operations | Nothing derived from a request leaves the gateway before policy filtering. Tokenizer counts (`/tokenize`) are requested only from deployments that already passed locality, enablement, health and capability filters; the optional classifier must be a local deployment unless `routing.classifier.allow_remote` **and** `security.locality_mode: allow_remote` are both set. Unknown content part types (`audio_url`, `video_url`, `file`, …) are rejected with `400 unsupported_content_type` before any dispatch | `routing/router.py`, `protocol/openai.py` |
| Code execution | The gateway never executes model-generated commands. The evaluation harness runs *model-written Python* only inside bubblewrap (Linux), `sandbox-exec` (macOS) or a `--network none --read-only` Docker container with CPU/memory/output/time limits; when none is available the task is **skipped**. There is no unsandboxed fallback and no flag to enable one | `evaluation/sandbox.py` |
| Dependencies | Five pinned-range runtime deps; CI runs `pip-audit` and secret scanning; workflow permissions are read-only | `.github/workflows/ci.yml` |

## LAN exposure

Set `server.host: 0.0.0.0` **and** `security.allow_lan: true`. Keys then travel over plain HTTP:
terminate TLS in front (Caddy/nginx) or use a trusted private tunnel (Tailscale/WireGuard). Rotate
keys with `modelsaar keys rotate`. The admin key should never leave the host. `modelsaar keys ensure`
creates missing key files (idempotent, never rotates) and is what the container runs before `serve`.

## File handling

`client-config --apply` keeps the target file's permission bits (a `0600` file stays `0600`; new files
are created `0600` because the snippet carries the gateway key), writes temp files and backups private
from creation and never reuses a backup name. `modelsaar uninstall` removes only the files ModelSaar
created (config and its backups, its key files, its state database), refuses symlinked `keys/`/`state/`
boundaries and leaves anything else in place.

## Offline operation — scope of the claim

What was tested: with the fake backend on loopback and `locality_mode: local_only`, no request,
classification or telemetry leaves the host; cloud aliases are excluded even when requested
explicitly (`tests/test_acceptance.py::test_local_only_blocks_cloud_even_when_explicit`,
`test_prompt_injection_cannot_change_routing`); a remote-labelled backend with a `/tokenize` endpoint
receives zero bytes of message text (`tests/test_hardening_2026_10_11.py::test_local_only_sends_no_message_text_to_remote_tokenizer`).

What the gateway cannot prove: that an opaque backend is truly local. A localhost address can be a
proxy; Ollama can forward `:cloud` models. ModelSaar records the evidence it has (`locality_evidence`
in `/admin/status`) and treats operator declarations as trust assumptions.

What is outside the gateway: client tools (web search, browsers, code execution), auxiliary models
(Open WebUI task model, OpenClaw utility model, Hermes compression model) and unrelated applications
have their own network behaviour. Changing the main model endpoint does not make a whole application
offline. To check: run `modelsaar serve` and the client with outbound network blocked (macOS: a
firewall rule or Little Snitch; Linux: `unshare -n` / nftables) and confirm the client still
completes a chat through the gateway.

## Reporting

See [SECURITY.md](../SECURITY.md).
