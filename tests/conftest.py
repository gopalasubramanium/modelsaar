"""Shared fixtures: a controllable fake backend and a gateway on real sockets."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from modelsaar.config import (
    BackendConfig,
    Capabilities,
    Config,
    DeploymentOverride,
    ResourcePool,
    generate_key,
    write_key_file,
)
from modelsaar.runtime import GatewayThread, free_port
from modelsaar.testing.fakebackend import FakeBackend, FakeModel


def make_models() -> list[FakeModel]:
    return [
        FakeModel("small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True),
        FakeModel("big:27b", ["completion", "tools", "vision", "thinking"], 32768, parameter_size="27B", size_bytes=18_000_000_000),
        FakeModel("plain:3b", ["completion"], 4096, parameter_size="3B"),
        FakeModel("embed:0.6b", ["embedding"], 2048, parameter_size="0.6B", embedding_dimensions=8),
        FakeModel("embed-other:1b", ["embedding"], 2048, parameter_size="1B", embedding_dimensions=16),
        FakeModel("cloud:latest", ["completion", "tools", "vision"], 128000, remote=True),
    ]


@pytest.fixture
def fake():
    f = FakeBackend(make_models())
    f.start()
    yield f
    f.stop()


class Gateway:
    def __init__(self, gw: GatewayThread, api_key: str, admin_key: str, tmp: Path) -> None:
        self.gw = gw
        self.api_key = api_key
        self.admin_key = admin_key
        self.tmp = tmp
        self.url = gw.url
        self.client = httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        self.admin = httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=30)

    @property
    def router(self):
        return self.gw.router

    def refresh(self) -> None:
        self.admin.post("/admin/refresh")

    def decision(self, request_id: str) -> dict:
        return self.admin.get(f"/admin/decisions/{request_id}").json()


def build_gateway(backend_url: str, **overrides) -> Gateway:
    tmp = Path(tempfile.mkdtemp(prefix="modelsaar-test-"))
    api_key, admin_key = generate_key("msk"), generate_key("msa")
    write_key_file(tmp / "keys/api_keys", [api_key])
    write_key_file(tmp / "keys/admin_key", [admin_key])
    base = dict(
        resource_pools=(ResourcePool(id="pool", max_concurrent=2, max_queue=2, queue_timeout_s=2.0),),
        backends=(BackendConfig(id="ollama", type="ollama", base_url=backend_url, resource_pool="pool", max_concurrent=4),),
        deployments=(
            # Probe evidence is simulated by operator overrides here; probe tests cover the live path.
            DeploymentOverride(backend="ollama", model="big:27b", tags=("code",), capabilities=Capabilities(json_schema="supported", parallel_tools="supported")),
            DeploymentOverride(backend="ollama", model="small:1b", capabilities=Capabilities(json_schema="unsupported")),
        ),
    )
    base.update(overrides)
    cfg = Config(**base)
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port(), "residency_refresh_s": 0.5, "discovery_refresh_s": 3600}), "config_path": str(tmp / "config.yaml"), "config_hash": "test"})
    gw = GatewayThread(cfg)
    gw.start()
    return Gateway(gw, api_key, admin_key, tmp)


@pytest.fixture
def gateway(fake):
    g = build_gateway(f"http://127.0.0.1:{fake.port}")
    yield g
    g.gw.stop()


def chat(g: Gateway, model: str = "auto", content="hello", **extra) -> httpx.Response:
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    body.update(extra)
    return g.client.post("/v1/chat/completions", json=body)


def stream_events(resp: httpx.Response) -> list[str]:
    raw = b"".join(resp.iter_bytes()).decode("utf-8")
    return [fr for fr in raw.split("\n\n") if fr.strip()]
