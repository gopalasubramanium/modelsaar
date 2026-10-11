# Installation, upgrade, rollback, uninstall

## Native (recommended)

Prerequisites: Python 3.10+ (`python3 --version`), `git`, and a running inference server with at
least one model (e.g. `ollama serve` + `ollama pull gemma4:e4b`). ModelSaar never downloads models.

```bash
git clone <repository> modelsaar && cd modelsaar
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # editable install from source; `pip install .` for a plain install
modelsaar init              # discovers Ollama on 127.0.0.1:11434 or pass --endpoint/--type
modelsaar doctor
modelsaar serve
```

With `uv`: `uv venv && . .venv/bin/activate && uv pip install -e .` (or `uv tool install .` to get a
global `modelsaar` command).

Files created by `init` (default `~/.modelsaar`, override with `MODELSAAR_HOME` or `--config`):

```
~/.modelsaar/config.yaml      versioned configuration (version: 1), mode 600
~/.modelsaar/keys/api_keys    generated inference key(s), one per line, mode 600
~/.modelsaar/keys/admin_key   generated admin key, mode 600
~/.modelsaar/state/modelsaar.db   probe evidence, measurements, decision log (metadata only)
```

No PyPI package or container image is published; the commands above are the supported path.

## Configuration essentials

```yaml
version: 1
server: { host: 127.0.0.1, port: 8484 }
security: { allow_lan: false, locality_mode: local_only, log_prompts: false }
resource_pools:
  - { id: local-machine, kind: unified, max_concurrent: 1 }    # one inference at a time on this box
backends:
  - { id: ollama, type: ollama, base_url: http://127.0.0.1:11434, resource_pool: local-machine }
  # - id: vllm
  #   type: openai_compatible
  #   base_url: http://127.0.0.1:8000/v1
  #   resource_pool: local-machine
  #   models:                                   # declare what discovery cannot tell
  #     - name: Qwen/Qwen3.8-27B
  #       context_length: 65536
  #       capabilities: { tools: supported, json_schema: supported }
  #       tags: [code]
deployments:                                     # operator overrides with visible provenance
  - { backend: ollama, model: "qwen3.8:27b", context_length: 32768, tags: [code] }
routing:
  default_profile: quality
  classifier: { enabled: false }                 # optional local classifier (see routing.md)
affinity: { mode: session, session_headers: [X-ModelSaar-Session, X-OpenWebUI-Chat-Id] }
embeddings:
  - { alias: docs-index, deployments: ["ollama/embeddinggemma-2:latest"], dimensions: 768 }
```

`modelsaar config validate|show|example`. Reload by restarting `serve` (in-flight requests keep
their snapshot).

## Docker Compose (optional)

`docker compose up --build` builds a local image from `Dockerfile` (no published image). The
container needs to reach your inference server **on the host**:

| host OS | backend URL inside the container | notes |
|---|---|---|
| macOS / Windows (Docker Desktop) | `http://host.docker.internal:11434` | works out of the box |
| Linux | `http://host.docker.internal:11434` | requires `extra_hosts: ["host.docker.internal:host-gateway"]` (already in `docker-compose.yml`) |
| WSL2 | `http://host.docker.internal:11434` if Ollama runs in Windows; `http://<wsl-ip>:11434` if Ollama runs inside WSL | Ollama must listen beyond loopback (`OLLAMA_HOST=0.0.0.0`) for a container to reach it |

Inside a container the gateway binds `0.0.0.0` (`security.allow_lan: true` in `examples/config.docker.yaml`)
so Docker can publish the port; publish it to `127.0.0.1:8484` only unless you intend LAN exposure.
The container provides the **gateway** only; model execution and hardware acceleration remain with
your runtime on the host.

## Upgrade

```bash
cd modelsaar && git pull && pip install -e .      # or uv pip install -e .
modelsaar config validate                          # fails loudly if the config version is unsupported
modelsaar config migrate                           # applies migrations when a newer config version exists
modelsaar doctor
```

Config files carry `version: 1`. A build that cannot read your version refuses to start with a
message instead of guessing. Keys and state are untouched by upgrades.

## Rollback

`git checkout <previous tag>` then `pip install -e .`. Configuration is forward-compatible within a
major version; if a migration changed your file, restore `config.yaml.bak-*` written by `migrate`.

## Service management (optional)

Run `modelsaar serve` under your service manager. A minimal `launchd` plist (macOS) and `systemd`
unit (Linux) are in `examples/`. Remove the unit/plist to stop auto-starting.

## Uninstall

```bash
modelsaar uninstall        # removes ~/.modelsaar (config, keys, state) after confirmation
pip uninstall modelsaar    # or: uv tool uninstall modelsaar
```

Uninstall never touches models in your runtime or client configuration files. Client configs
changed with `client-config --apply` have `.bak-<timestamp>` copies next to them; restore those to
undo the change.
