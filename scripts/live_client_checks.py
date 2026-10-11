"""Wire-level client checks against a running ModelSaar gateway (no model downloads).

Exercises what a real client does: ordinary chat, streaming, tool emission, tool-result
continuation on the same deployment, session-header pinning and model attribution. Writes a
JSON report with request ids, deployments and headers only (no prompts, no keys).

Usage: python scripts/live_client_checks.py GATEWAY_URL API_KEY OUT.json [ADMIN_KEY]
"""

from __future__ import annotations

import json
import sys
import time

import httpx

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Current time in a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
        },
    }
]


def main() -> int:
    url, key, out = sys.argv[1], sys.argv[2], sys.argv[3]
    admin = sys.argv[4] if len(sys.argv) > 4 else None
    c = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {key}"}, timeout=600)
    rep: dict = {"gateway": url, "checks": {}, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    def rec(name: str, r: httpx.Response, **extra) -> dict:
        d = {
            "status": r.status_code,
            "request_id": r.headers.get("x-modelsaar-request-id"),
            "deployment": r.headers.get("x-modelsaar-deployment"),
            "profile": r.headers.get("x-modelsaar-profile"),
            **extra,
        }
        rep["checks"][name] = d
        print(f"[client-check] {name:34s} HTTP {r.status_code} -> {d.get('deployment')} {extra if extra else ''}")
        return d

    # 1. ordinary chat + attribution (response.model must be the requested alias)
    r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "Reply with one word: ready"}], "max_tokens": 16})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    rec("chat", r, response_model=body.get("model"), attribution_ok=body.get("model") == "auto", finish=(body.get("choices") or [{}])[0].get("finish_reason"))

    # 2. streaming: frames, finish_reason, [DONE], model field rewritten in every frame
    with c.stream("POST", "/v1/chat/completions", json={"model": "auto-fast", "stream": True, "messages": [{"role": "user", "content": "Count from 1 to 5."}], "max_tokens": 40}) as rs:
        raw = b"".join(rs.iter_bytes()).decode("utf-8", "replace")
        frames = [f for f in raw.split("\n\n") if f.strip()]
        models = set()
        finish = None
        for f in frames:
            if f.startswith("data: ") and f != "data: [DONE]":
                try:
                    obj = json.loads(f[6:])
                    models.add(obj.get("model"))
                    for ch in obj.get("choices") or []:
                        finish = ch.get("finish_reason") or finish
                except ValueError:
                    pass
        rec("stream", rs, frames=len(frames), done=frames[-1].strip() == "data: [DONE]" if frames else False, finish=finish, model_fields=sorted(m for m in models if m), content_type=rs.headers.get("content-type"))

    # 3. tool emission
    r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "What time is it in Paris? Use the tool."}], "tools": TOOLS, "max_tokens": 200})
    body = r.json()
    msg = (body.get("choices") or [{}])[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    d = rec("tools_emission", r, tool_calls=len(calls), finish=(body.get("choices") or [{}])[0].get("finish_reason"))
    issuer = d["deployment"]

    # 4. tool-result continuation: must stay on the issuer (header), never another deployment
    if calls:
        msgs = [
            {"role": "user", "content": "What time is it in Paris? Use the tool."},
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "tool", "tool_call_id": calls[0]["id"], "content": "14:05"},
        ]
        r = c.post("/v1/chat/completions", json={"model": "auto", "messages": msgs, "tools": TOOLS, "max_tokens": 100})
        d2 = rec("tool_result_continuation", r, same_deployment=r.headers.get("x-modelsaar-deployment") == issuer, issuer=issuer)
        if admin:
            a = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {admin}"}, timeout=30)
            dec = a.get(f"/admin/decisions/{d2['request_id']}").json()
            d2["affinity"] = dec.get("affinity")
            d2["failover_allowed"] = dec.get("failover_allowed")
    else:
        rep["checks"]["tool_result_continuation"] = {"status": "NOT RUN", "reason": "no tool call emitted"}

    # 5. session header on the wire: second request with the same X-ModelSaar-Session pins
    h = {"X-ModelSaar-Session": f"verify-{int(time.time())}"}
    r1 = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "Say hi."}], "max_tokens": 8}, headers=h)
    r2 = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "Say hi again."}], "max_tokens": 8}, headers=h)
    d = rec("session_header_pin", r2, first=r1.headers.get("x-modelsaar-deployment"), pinned=r1.headers.get("x-modelsaar-deployment") == r2.headers.get("x-modelsaar-deployment"))
    if admin:
        a = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {admin}"}, timeout=30)
        d["affinity"] = a.get(f"/admin/decisions/{d['request_id']}").json().get("affinity")

    # 6. unsupported content part -> 400 before any dispatch
    r = c.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAA"}}]}]})
    rec("unsupported_part_400", r, code=(r.json().get("error") or {}).get("code") if r.headers.get("content-type", "").startswith("application/json") else None)

    rep["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2)
    print(f"[client-check] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
