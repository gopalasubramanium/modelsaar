"""Client configuration generators (Open WebUI, OpenClaw, OpenCode V1/V2, Hermes Agent).

Every key emitted here was checked against the client's current primary
documentation on 2026-10-11 (see docs/clients/*.md for sources). Generators
only *propose* changes; ``--apply`` writes a backup and merges into the file,
preserving unrelated settings.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AliasInfo:
    name: str
    context_length: int
    tools: bool
    vision: bool
    description: str = ""


@dataclass
class ClientTarget:
    gateway_url: str  # e.g. http://127.0.0.1:8484  (no /v1)
    api_key_env: str = "MODELSAAR_API_KEY"
    aliases: list[AliasInfo] | None = None
    in_docker: bool = False

    @property
    def base_v1(self) -> str:
        url = self.gateway_url.rstrip("/")
        if self.in_docker:
            url = url.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
        return url + "/v1"

    def alias_list(self) -> list[AliasInfo]:
        return self.aliases or [AliasInfo("auto", 8192, False, False, "Best expected quality within limits")]


CLIENTS = ("open-webui", "openclaw", "opencode", "opencode-v2", "hermes")


# --------------------------------------------------------------------------- #
def open_webui(t: ClientTarget) -> str:
    aliases = t.alias_list()
    names = ", ".join(a.name for a in aliases)
    return f"""# Open WebUI -> ModelSaar  (checked against docs 2026-10-11)

Open WebUI concatenates paths onto the connection URL (`{{url}}/chat/completions`, `{{url}}/models`),
so the URL MUST include `/v1` and must not end with a slash.

## UI steps
1. Admin Panel -> Settings -> Connections -> "Manage OpenAI API Connections" -> Add Connection
2. URL:      {t.base_v1}
3. API Key:  <your ModelSaar API key>   (file: ~/.modelsaar/keys/api_keys)
4. Save, then "Verify Connection" (this calls GET {t.base_v1}/models with a Bearer token).
   Models are auto-listed from /models: {names} plus concrete deployments.

## Environment-variable equivalent (Docker / compose)
ENABLE_OPENAI_API=true
OPENAI_API_BASE_URLS={t.base_v1}
OPENAI_API_KEYS=<your ModelSaar API key>
# Route Open WebUI's background tasks (titles, tags, follow-ups) to the fast alias instead of the chat model:
TASK_MODEL_EXTERNAL=auto-fast
# Optional: forward the chat id so ModelSaar keeps a conversation on one deployment (session affinity):
ENABLE_FORWARD_USER_INFO_HEADERS=true     # sends X-OpenWebUI-Chat-Id (and user headers) to the gateway

## Docker networking
Open WebUI in a container cannot reach 127.0.0.1 of the host. Use host.docker.internal (macOS/Windows);
on Linux add `--add-host=host.docker.internal:host-gateway` and bind ModelSaar to a non-loopback address
(server.host: 0.0.0.0, security.allow_lan: true) - only on a trusted network. Podman: host.containers.internal.

## Notes
- Tool calling: Native (default) mode sends `tools`; Open WebUI does not send tool_choice.
- Per-model capability toggles (vision, etc.) live in Admin -> Models; ModelSaar also enforces them server-side.
"""


def openclaw(t: ClientTarget) -> dict[str, Any]:
    models = []
    for a in t.alias_list():
        models.append(
            {
                "id": a.name,
                "name": f"ModelSaar {a.name}",
                "reasoning": False,
                "input": ["text", "image"] if a.vision else ["text"],
                "contextWindow": a.context_length,
                "maxTokens": min(32000, max(1024, a.context_length // 4)),
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "compat": {"supportsTools": a.tools, "supportsPromptCacheKey": True},
            }
        )
    primary = t.alias_list()[0].name
    return {
        "agents": {"defaults": {"model": {"primary": f"modelsaar/{primary}"}}},
        "models": {
            "mode": "merge",
            "providers": {
                "modelsaar": {
                    "baseUrl": t.base_v1,
                    "apiKey": f"${{{t.api_key_env}}}",
                    "api": "openai-completions",
                    "timeoutSeconds": 300,
                    "models": models,
                }
            },
        },
    }


def openclaw_text(t: ClientTarget) -> str:
    cfg = openclaw(t)
    return f"""# OpenClaw -> ModelSaar  (checked against docs.openclaw.ai 2026-10-11, release v2026.9.9)

File: ~/.openclaw/openclaw.json (JSON5; comments allowed). Custom providers are NOT auto-discovered from
/v1/models, so each alias you want must be declared under models.providers.modelsaar.models[].
`api: "openai-completions"` is the Chat Completions adapter (default when omitted; do not use openai-responses).
`compat.supportsPromptCacheKey: true` makes OpenClaw send `prompt_cache_key` (session id) so ModelSaar can keep
a session on one deployment. Set the key in your environment: export {t.api_key_env}=<your key>.

Merge this into your config (`modelsaar client-config openclaw --apply` does it with a backup when the file is plain JSON):

{json.dumps(cfg, indent=2)}
"""


def opencode_v1(t: ClientTarget) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for a in t.alias_list():
        models[a.name] = {
            "name": f"ModelSaar {a.name}",
            "tool_call": a.tools,
            "reasoning": False,
            "attachment": a.vision,
            "modalities": {"input": ["text", "image"] if a.vision else ["text"], "output": ["text"]},
            "limit": {"context": a.context_length, "output": min(32000, max(1024, a.context_length // 4))},
            "cost": {"input": 0, "output": 0},
        }
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"modelsaar/{t.alias_list()[0].name}",
        "provider": {
            "modelsaar": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "ModelSaar",
                "options": {"baseURL": t.base_v1, "apiKey": f"{{env:{t.api_key_env}}}", "setCacheKey": True},
                "models": models,
            }
        },
    }


def opencode_v2(t: ClientTarget) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for a in t.alias_list():
        models[a.name] = {
            "name": f"ModelSaar {a.name}",
            "capabilities": {"tools": a.tools, "input": ["text", "image"] if a.vision else ["text"], "output": ["text"]},
        }
    return {
        "$schema": "https://opencode.ai/config.json",
        "providers": {
            "modelsaar": {
                "name": "ModelSaar",
                "env": [t.api_key_env],
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": t.base_v1},
                "models": models,
            }
        },
    }


def opencode_text(t: ClientTarget, v2: bool = False) -> str:
    if v2:
        return f"""# OpenCode V2 -> ModelSaar  (checked against opencode.ai/v2/docs 2026-10-11)

File: ~/.config/opencode/opencode.json(c) or <project>/.opencode/opencode.json(c).
V2 uses top-level `providers` / `package` / `settings` / `capabilities`. NEVER mix with V1 keys
(`provider` / `npm` / `options` / `tool_call`) in one entry. Credential comes from the env var listed in `env`.
`@opencode/ai/providers/openai-compatible` speaks Chat Completions; include /v1 in baseURL.

{json.dumps(opencode_v2(t), indent=2)}
"""
    return f"""# OpenCode V1 -> ModelSaar  (checked against opencode.ai/docs 2026-10-11, docs updated Oct 8 2026)

File: ~/.config/opencode/opencode.json (global) or ./opencode.json (project). JSON or JSONC.
V1 uses top-level `provider` (singular) with `npm: "@ai-sdk/openai-compatible"` (Chat Completions; do NOT use
`@ai-sdk/openai`, which defaults to the Responses API that ModelSaar does not implement). Include /v1 in baseURL.
Models are declared manually; `tool_call: true` is required for agent use. `setCacheKey: true` asks OpenCode to
attach its session id as a prompt cache key (whether the compatible transport emits it on the wire is not
documented - affinity falls back to tool-round-trip continuity, which always works).
Set the key: export {t.api_key_env}=<your key>

{json.dumps(opencode_v1(t), indent=2)}
"""


def hermes(t: ClientTarget) -> dict[str, Any]:
    primary = t.alias_list()[0]
    return {
        "model": {
            "default": primary.name,
            "provider": "custom",
            "base_url": t.base_v1,
            "key_env": t.api_key_env,
            "context_length": primary.context_length,
        },
        "providers": {
            "modelsaar": {
                "api": t.base_v1,
                "key_env": t.api_key_env,
                "transport": "chat_completions",
                "default_model": primary.name,
                "context_length": primary.context_length,
                "session_affinity_header": "X-ModelSaar-Session",
            }
        },
    }


def hermes_text(t: ClientTarget) -> str:
    return f"""# NousResearch Hermes Agent -> ModelSaar  (checked against hermes-agent.nousresearch.com docs 2026-10-11)

File: ~/.hermes/config.yaml (single source of truth); secrets in ~/.hermes/.env.
Each provider has ITS OWN credential setting (`key_env` / `api_key` / `key_cmd`). There is no generic
HERMES_* variable for custom endpoints, and OPENAI_BASE_URL applies only to the built-in openai-api provider.
`transport: chat_completions` (default) is what ModelSaar implements. `session_affinity_header` makes Hermes
send its conversation id in that header; ModelSaar reads X-ModelSaar-Session by default.
Interactive alternative: `hermes model` -> "Custom endpoint" -> URL {t.base_v1}.

~/.hermes/.env:
{t.api_key_env}=<your ModelSaar API key>

~/.hermes/config.yaml (merge; `modelsaar client-config hermes --apply` merges with a backup):
{yaml.safe_dump(hermes(t), sort_keys=False)}
"""


# --------------------------------------------------------------------------- #
def render(client: str, t: ClientTarget) -> str:
    if client == "open-webui":
        return open_webui(t)
    if client == "openclaw":
        return openclaw_text(t)
    if client == "opencode":
        return opencode_text(t, v2=False)
    if client == "opencode-v2":
        return opencode_text(t, v2=True)
    if client == "hermes":
        return hermes_text(t)
    raise ValueError(f"unknown client {client}; choose one of {CLIENTS}")


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = _deep_merge(out.get(k), v) if k in out else v
        return out
    return patch


def default_path(client: str) -> Path | None:
    home = Path.home()
    return {
        "openclaw": home / ".openclaw" / "openclaw.json",
        "opencode": home / ".config" / "opencode" / "opencode.json",
        "opencode-v2": home / ".config" / "opencode" / "opencode.json",
        "hermes": home / ".hermes" / "config.yaml",
    }.get(client)


def proposed_patch(client: str, t: ClientTarget) -> dict[str, Any] | None:
    if client == "openclaw":
        return openclaw(t)
    if client == "opencode":
        return opencode_v1(t)
    if client == "opencode-v2":
        return opencode_v2(t)
    if client == "hermes":
        return hermes(t)
    return None


def apply_patch(client: str, t: ClientTarget, path: Path | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Merge the proposed snippet into the client's config file.

    Returns {path, existed, backup, before, after, applied}. Idempotent: re-applying yields no change.
    """
    patch = proposed_patch(client, t)
    if patch is None:
        raise ValueError(f"{client} is configured through its UI/env; nothing to apply")
    path = path or default_path(client)
    assert path is not None
    existed = path.exists()
    text = path.read_text(encoding="utf-8") if existed else ""
    is_yaml = path.suffix in (".yaml", ".yml")
    if existed and text.strip():
        try:
            current = yaml.safe_load(text) if is_yaml else json.loads(text)
        except Exception as e:
            raise ValueError(
                f"{path} is not parseable as {'YAML' if is_yaml else 'strict JSON'} ({e}); "
                "it may use JSON5/JSONC comments. Merge the printed snippet manually."
            ) from e
    else:
        current = {}
    if client in ("opencode", "opencode-v2") and isinstance(current, dict):
        if client == "opencode" and "providers" in current:
            raise ValueError("this file uses the OpenCode V2 schema (`providers`); use `client-config opencode-v2`")
        if client == "opencode-v2" and "provider" in current:
            raise ValueError("this file uses the OpenCode V1 schema (`provider`); use `client-config opencode`")
    merged = _deep_merge(current or {}, patch)
    after = yaml.safe_dump(merged, sort_keys=False) if is_yaml else json.dumps(merged, indent=2) + "\n"
    changed = after != text
    result = {"path": str(path), "existed": existed, "backup": None, "changed": changed, "applied": False, "after": after}
    if dry_run or not changed:
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        backup = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        result["backup"] = str(backup)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(after, encoding="utf-8")
    tmp.replace(path)
    result["applied"] = True
    return result
