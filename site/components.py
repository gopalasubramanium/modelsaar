"""Reusable HTML components for the site build (walkthrough scenarios, command blocks, matrices)."""

from __future__ import annotations

import html

import facts


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# --------------------------------------------------------------------------- #
# Routing walkthrough — ILLUSTRATIVE scenarios.
# Deployment names and capability facts are the three models of the recorded GX10 run
# (docs/live-runs/2026-10-11-gx10-hardening); the selections follow the decision records of that run
# where one exists (chat/coding/image/tool round trip) and the gateway's documented rules otherwise.
# They are scripted explanations, not live inference and not benchmark results.
# --------------------------------------------------------------------------- #
DEPLOYMENTS = [
    {"id": "ollama/qwen3-coder:latest", "label": "qwen3-coder (30B)", "tools": True, "vision": False, "ctx": 131072, "thinking": False},
    {"id": "ollama/gemma4:31b", "label": "gemma4 (31B, thinking)", "tools": True, "vision": True, "ctx": 4096, "thinking": True},
    {"id": "ollama/qwen3.6:latest", "label": "qwen3.6 (35B, thinking)", "tools": True, "vision": True, "ctx": 4096, "thinking": True},
]

SCENARIOS = [
    {
        "title": "General chat",
        "subtitle": "a short question, no tools, no images",
        "request": "“Give me one sentence of encouragement before an exam.”",
        "facts": ["task: conversation", "needs: nothing special", "context: ~40 tokens"],
        "alias": "auto",
        "verdict": {"ollama/qwen3-coder:latest": ("yes", "eligible"), "ollama/gemma4:31b": ("yes", "eligible"), "ollama/qwen3.6:latest": ("yes", "eligible")},
        "chosen": "ollama/qwen3-coder:latest",
        "why": "All three can answer. Measured evidence from the calibration run gives qwen3-coder the best conversation success at the lowest latency, so the <em>quality</em> profile picks it. Had the evidence been missing, the tie would resolve to the lowest-overhead deployment and the record would say <code>uncalibrated</code>.",
        "evidence": "measured (calibration run)",
    },
    {
        "title": "Coding with tools",
        "subtitle": "an agent asks to fix a test and offers a shell tool",
        "request": "“Fix the failing pytest in src/app.py” + tools: [bash]",
        "facts": ["task: coding", "needs: tool calling", "context: ~3 200 tokens"],
        "alias": "auto",
        "verdict": {"ollama/qwen3-coder:latest": ("yes", "tools verified by probe"), "ollama/gemma4:31b": ("yes", "tools verified by probe"), "ollama/qwen3.6:latest": ("yes", "tools verified by probe")},
        "chosen": "ollama/qwen3-coder:latest",
        "why": "Tool calling is a hard requirement; every candidate passed the tools probe, so none is excluded. On coding tasks the measured calibration success favours qwen3-coder (2/2, versus 1/2 and 0/2 within the run's 400-token budget), and the request is forwarded unchanged — the client keeps its own agent loop and runs the tool itself.",
        "evidence": "measured (calibration run)",
    },
    {
        "title": "Question about an image",
        "subtitle": "the message carries a base64 image",
        "request": "“What is in this picture?” + image",
        "facts": ["task: document_vision", "needs: image input", "context: ~1 250 tokens"],
        "alias": "auto",
        "verdict": {"ollama/qwen3-coder:latest": ("no", "image input unsupported (backend metadata)"), "ollama/gemma4:31b": ("yes", "vision verified by probe"), "ollama/qwen3.6:latest": ("yes", "vision verified by probe")},
        "chosen": "ollama/gemma4:31b",
        "why": "A failed capability check can never be outscored: qwen3-coder is excluded with the reason recorded. Between the two vision-capable models the recorded run picked gemma4 on its measured evidence (calibration success 0.80 versus 0.47 overall). The image is never dropped or described away — if no deployment could take it, the request would fail with blockers and remedies instead.",
        "evidence": "measured (calibration run)",
    },
    {
        "title": "Tool result comes back",
        "subtitle": "the second turn of a tool call issued by gemma4",
        "request": "assistant: tool_call(id=call_7f2…) → tool: “14:05” → continue",
        "facts": ["task: agent", "needs: tool calling + continuity", "tool round trip: call_7f2…"],
        "alias": "auto",
        "verdict": {"ollama/qwen3-coder:latest": ("no", "would hand the tool history to another model"), "ollama/gemma4:31b": ("yes", "issued the tool call"), "ollama/qwen3.6:latest": ("no", "would hand the tool history to another model")},
        "chosen": "ollama/gemma4:31b",
        "why": "The gateway remembers which deployment issued the tool-call ids. The follow-up turn stays on it even when another candidate would score higher, and the record marks <code>failover_allowed: false</code>: if gemma4 fails now, the client gets the error rather than a silent switch to a model that never saw the tool call.",
        "evidence": "continuity rule",
    },
    {
        "title": "Nothing qualifies",
        "subtitle": "an image question when only qwen3-coder is configured",
        "request": "“What is in this picture?” + image — with one deployment",
        "facts": ["task: document_vision", "needs: image input", "deployments: 1"],
        "alias": "auto",
        "verdict": {"ollama/qwen3-coder:latest": ("no", "image input unsupported (backend metadata)")},
        "chosen": None,
        "why": "Automatic routing with one model simply uses that model whenever it qualifies. When it does not, the answer is an HTTP 422 with the blocker (<em>image input required; capability vision is unsupported</em>) and a remedy (<em>use a deployment whose vision capability is supported</em>) — never a degraded answer that pretends the image was read.",
        "evidence": "hard filter",
    },
]


def decision_record(sc: dict, req_id: str) -> str:
    rows = []
    deps = [d for d in DEPLOYMENTS if d["id"] in sc["verdict"]]
    for d in deps:
        v, reason = sc["verdict"][d["id"]]
        mark = '<span class="yes">✓</span>' if v == "yes" else '<span class="nope">✗</span>'
        cls = ' class="chosen"' if sc["chosen"] == d["id"] else ""
        chosen = " — selected" if sc["chosen"] == d["id"] else ""
        rows.append(f"<tr{cls}><td>{esc(d['label'])}{chosen}</td><td>{mark} {esc(reason)}</td></tr>")
    facts_html = "".join(f"<li>{esc(f)}</li>" for f in sc["facts"])
    outcome = f"<strong>{esc(sc['chosen'])}</strong>" if sc["chosen"] else '<strong class="nope">no eligible deployment (HTTP 422)</strong>'
    return f"""
<div class="decision" aria-label="Decision record (illustration)">
  <div class="decision-head"><span>decision {esc(req_id)}</span><span>{esc(sc['alias'])} → {outcome}</span></div>
  <div class="decision-req"><p>{esc(sc['request'])}</p><ul class="facts">{facts_html}</ul></div>
  <div class="table-wrap" tabindex="0"><table><thead><tr><th scope="col">deployment</th><th scope="col">hard checks</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
  <div class="decision-why"><p>{sc['why']}</p></div>
  <div class="decision-foot">Evidence: {esc(sc['evidence'])}. Illustration based on the three models of the 2026-10-11 run; not a live result.</div>
</div>"""


def walkthrough(site) -> str:  # type: ignore[no-untyped-def]
    out = ['<div class="walkthrough">']
    for i, sc in enumerate(SCENARIOS):
        out.append(
            f'<details class="scenario" id="scenario-{i}"{" open" if i == 0 else ""}>'
            f'<summary>{esc(sc["title"])} <span class="small">{esc(sc["subtitle"])}</span></summary>'
            f"{decision_record(sc, f'req_{i + 1:02d}…')}</details>"
        )
    out.append("</div>")
    return "\n".join(out)


def cmd(text: str, note: str | None = None, lang: str = "bash") -> str:
    """A command block: a toolbar row (what the block is; the Copy button lands there when JS runs) above a
    dedicated code area, so text and button never share space. Shell commands wrap visually (``wrap``);
    structured multi-line text keeps its columns and scrolls inside the block (``scroll``, keyboard-focusable).
    The clipboard value is the code element's exact text, independent of visual wrapping."""
    n = f'<p class="cmd-note">{note}</p>' if note else ""
    label = {"bash": "Terminal", "sh": "Terminal", "text": "Values to paste"}.get(lang, lang)
    mode = "wrap" if lang in ("bash", "sh") else "scroll"
    pre_attr = ' tabindex="0"' if mode == "scroll" else ' class="wrap"'
    return (
        f'<div class="cmd cmd-{mode}"><div class="cmd-bar"><span class="cmd-label">{esc(label)}</span></div>'
        f'<pre{pre_attr}><code class="language-{lang}">{esc(text)}</code></pre></div>{n}'
    )


def support_matrix(site) -> str:  # type: ignore[no-untyped-def]
    def badge(ev: str) -> str:
        parts = [p.strip() for p in ev.split(",")]
        out = []
        for p in parts:
            cls = {"live": "live", "fixture": "fixture", "docs": "docs", "not-run": "not-run", "owner": "owner"}[p]
            label = {"live": "live", "fixture": "fixture tests", "docs": "documented", "not-run": "not run", "owner": "owner-reported"}[p]
            out.append(f'<span class="evidence {cls}">{label}</span>')
        return " ".join(out)

    rows = "".join(
        f"<tr><td>{esc(r['kind'])}</td><td>{inline_md(r['item'])}</td><td>{badge(r['evidence'])}</td><td>{inline_md(r['note'])}</td></tr>" for r in facts.SUPPORT
    )
    return f'<div class="table-wrap"><table><thead><tr><th scope="col">area</th><th scope="col">what</th><th scope="col">evidence</th><th scope="col">notes</th></tr></thead><tbody>{rows}</tbody></table></div>'


def inline_md(s: str) -> str:
    """Backticks -> <code>, nothing else (keeps facts.py readable)."""
    out = []
    parts = s.split("`")
    for i, p in enumerate(parts):
        out.append(f"<code>{esc(p)}</code>" if i % 2 else esc(p))
    return "".join(out)


def benchmark_table(site) -> str:  # type: ignore[no-untyped-def]
    ev = facts.live_eval()
    rows = []
    for r in ev["rows"]:
        name = r["policy"]
        rows.append(
            f"<tr><td>{esc(name)}</td><td>{r['success']:.3f}</td><td>[{r['ci'][0]:.2f}, {r['ci'][1]:.2f}]</td>"
            f"<td>{r['completion']:.3f}</td><td>{r['violations']}</td><td>{r['p50']:,.0f}</td><td>{r['p95']:,.0f}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th scope="col">policy</th><th scope="col">success</th><th scope="col">95 % CI</th>'
        '<th scope="col">completion</th><th scope="col">violations</th><th scope="col">p50 ms</th><th scope="col">p95 ms</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
