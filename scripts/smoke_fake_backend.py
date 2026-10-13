"""Quick end-to-end smoke run against the fake backend (SIMULATED models)."""

import json
import tempfile
from pathlib import Path

import httpx

from modelsaar.config import BackendConfig, Config, ResourcePool, generate_key, write_key_file
from modelsaar.runtime import GatewayThread, free_port
from modelsaar.testing.fakebackend import FakeBackend, FakeModel

fake = FakeBackend(
    [
        FakeModel("small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True, good_at=["conversation"]),
        FakeModel("big:27b", ["completion", "tools", "vision", "thinking"], 32768, parameter_size="27B", size_bytes=18_000_000_000, good_at=["coding", "math"]),
        FakeModel("embed:0.6b", ["embedding"], 2048, parameter_size="0.6B"),
        FakeModel("cloud:latest", ["completion", "tools"], 128000, remote=True),
    ]
)
burl = fake.start()
tmp = Path(tempfile.mkdtemp())
api_key, admin_key = generate_key("msk"), generate_key("msa")
write_key_file(tmp / "keys/api_keys", [api_key])
write_key_file(tmp / "keys/admin_key", [admin_key])
cfg = Config(
    resource_pools=(ResourcePool(id="pool", max_concurrent=2),),
    backends=(BackendConfig(id="ollama", type="ollama", base_url=burl, resource_pool="pool"),),
).model_copy(update={"config_path": str(tmp / "config.yaml"), "config_hash": "smoke"})
cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port()})})
gw = GatewayThread(cfg)
url = gw.start()
h = {"Authorization": f"Bearer {api_key}"}
c = httpx.Client(base_url=url, headers=h, timeout=30)
print("models:", [m["id"] for m in c.get("/v1/models").json()["data"]])
r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi there"}]})
print(r.status_code, r.headers.get("x-modelsaar-deployment"), r.json()["model"], r.json()["choices"][0]["message"]["content"][:50])
r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "Write a python def to parse dates ```py```"}]})
print(r.status_code, r.headers.get("x-modelsaar-deployment"))
r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": [{"type": "text", "text": "what is this"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]})
print(r.status_code, r.headers.get("x-modelsaar-deployment"), json.dumps(r.json().get("error", r.json().get("choices")))[:200])
with c.stream("POST", "/v1/chat/completions", json={"model": "auto-fast", "stream": True, "messages": [{"role": "user", "content": "stream please"}]}) as s:
    print(s.status_code, s.headers.get("x-modelsaar-deployment"))
    txt = b"".join(s.iter_bytes()).decode()
    print(txt[:300].replace("\n", "|"))
r = c.post("/v1/embeddings", json={"model": "ollama/embed:0.6b", "input": "hello"})
print(r.status_code, len(r.json()["data"][0]["embedding"]))
r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "x"}], "tools": [{"type": "function", "function": {"name": "f"}}], "tool_choice": "required"})
print(r.status_code, json.dumps(r.json())[:400])
ad = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=30)
print(json.dumps(ad.get("/admin/decisions?limit=1").json()["decisions"][0], indent=1)[:1500])
gw.stop()
fake.stop()
