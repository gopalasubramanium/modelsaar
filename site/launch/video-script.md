# Product walkthrough — script, storyboard, captions, transcript (≈75 s)

**Recording status: NOT RECORDED.** No screen recording exists; this is the verified script. Every command
shown runs against the real CLI at the pinned commit; the terminal output in the storyboard is taken from
the recorded GX10 run (`docs/live-runs/2026-10-11-gx10-hardening/`). Record at 1920×1080, 30 fps, no
music needed; captions below double as the transcript. Keep real request ids and deployment names; redact
keys (the CLI never prints them unless asked).

| t | screen | caption / voice |
|---|---|---|
| 0–6 s | Title card: wordmark, "One address for your local AI." | "If you run more than one local model, every app needs its own model setting. ModelSaar gives them one address." |
| 6–16 s | Terminal: `modelsaar discover` output (8 deployments, tools/vision/ctx columns) | "It discovers what your backend serves and verifies what each model can really do — tools, images, strict JSON — with short probes. Unknown never counts as yes." |
| 16–30 s | Terminal: `modelsaar explain -m "Fix the failing pytest in src/app.py" --tools` showing the candidate breakdown and the chosen deployment | "Ask it to explain a request before sending it: here, a coding task that needs tool calling. Every model that passed the tools probe is a candidate; measured evidence picks the coder model." |
| 30–42 s | Terminal: `curl` chat completion with `"model":"auto"` and an image part; response headers `X-ModelSaar-Deployment: ollama/gemma4:31b` | "Apps just ask for `auto`. An image question goes to a vision-capable model; the coder model is excluded with the reason recorded. The request itself is forwarded unchanged." |
| 42–54 s | Browser: `/admin/ui` status page, then `modelsaar decisions --limit 5` | "Every decision is written down — exclusions, scores, evidence, overhead — without your prompt. Routing took under a millisecond." |
| 54–66 s | Terminal: `curl -fsSL https://modelsaar.com/install.sh \| sh` output ending in `verification: OK` and the next steps | "Install pins a reviewed commit, finds your backend, and sends one request through `auto` to prove it works. Then point any OpenAI-compatible app at the gateway." |
| 66–75 s | End card: modelsaar.com, GitHub URL, "Development preview — Apache-2.0" | "ModelSaar is open source and in development preview. Try it on the models you already have." |

Transcript (plain text, for the video description):
If you run more than one local model, every app needs its own model setting. ModelSaar gives them one address. It discovers what your backend serves and verifies what each model can really do — tools, images, strict JSON — with short probes; unknown never counts as yes. Ask it to explain a request before sending it: a coding task that needs tool calling; every model that passed the tools probe is a candidate and measured evidence picks the coder model. Apps just ask for "auto". An image question goes to a vision-capable model; the coder model is excluded with the reason recorded; the request is forwarded unchanged. Every decision is written down — exclusions, scores, evidence, overhead — without your prompt; routing took under a millisecond. Install pins a reviewed commit, finds your backend and sends one request through "auto" to prove it works; then point any OpenAI-compatible app at the gateway. ModelSaar is open source and in development preview. Try it on the models you already have.
