# Open WebUI → ModelSaar

Verified against the Open WebUI docs and `main` source on 2026-10-11 (sources in
[research/clients-2026-10-11.md](../research/clients-2026-10-11.md), §1). Test status: configuration
keys **documented**; a live Open WebUI tool round trip through ModelSaar is **NOT RUN** in this build.

Generate the current snippet: `modelsaar client-config open-webui [--docker]`.

## Protocol and URL

Open WebUI sends **Chat Completions** and string-concatenates paths onto the connection URL
(`{url}/chat/completions`, `{url}/models`). Therefore the URL **must include `/v1`** and must not end
with a slash: `http://127.0.0.1:8484/v1`. Models are **auto-listed** from `GET /v1/models`, which
ModelSaar serves truthfully (aliases only when backed by a usable deployment).

## Steps (UI)

1. Admin Panel → Settings → Connections → *Manage OpenAI API Connections* → Add.
2. URL `http://127.0.0.1:8484/v1` (from Docker: `http://host.docker.internal:8484/v1`).
3. API Key: contents of `~/.modelsaar/keys/api_keys` (first line).
4. Save → *Verify Connection* (this is `GET /models` with the Bearer key).
5. Pick `auto` (or `auto-code`, `auto-vision`, a concrete `ollama/...` id) in the chat model selector.

## Environment variables (Docker / compose)

```env
ENABLE_OPENAI_API=true
OPENAI_API_BASE_URLS=http://host.docker.internal:8484/v1
OPENAI_API_KEYS=<modelsaar api key>
TASK_MODEL_EXTERNAL=auto-fast
ENABLE_FORWARD_USER_INFO_HEADERS=true
```

* `TASK_MODEL_EXTERNAL` sends Open WebUI's background tasks (title, tags, follow-ups, query
  generation — non-streaming) to `auto-fast` instead of the current chat model.
* `ENABLE_FORWARD_USER_INFO_HEADERS=true` makes Open WebUI add `X-OpenWebUI-Chat-Id` (plus user
  headers). ModelSaar reads it by default (`affinity.session_headers`) to keep a conversation on one
  deployment. Alternatively add a per-connection custom header `X-ModelSaar-Session: {{CHAT_ID}}`
  without forwarding user info. Without either, chats are request-routed (stateless).

## Container networking

Open WebUI in Docker cannot reach the host's `127.0.0.1`. Use `host.docker.internal`; on Linux add
`--add-host=host.docker.internal:host-gateway` (compose: `extra_hosts`). ModelSaar must then listen
beyond loopback: `server.host: 0.0.0.0` + `security.allow_lan: true` — do this only on a trusted
machine/network, or run ModelSaar in the same compose network (`docker-compose.yml` in this repo).
Podman: `host.containers.internal`.

## Tools, images, context

* Native function calling (default) sends `tools`; Open WebUI does not send `tool_choice` or
  `parallel_tool_calls`. ModelSaar routes tool requests only to tool-verified deployments.
* Images are sent as base64 data URLs → routed to vision-verified deployments (`auto-vision`).
* Per-model context/capability toggles in Admin → Models are UI-side; ModelSaar enforces the real
  limits server-side and returns a 422 with blockers when nothing fits.

## Verify

```bash
modelsaar test                       # gateway alone
# in Open WebUI: new chat with model `auto`, ask something; then
modelsaar decisions                  # shows the request and the chosen deployment
```
