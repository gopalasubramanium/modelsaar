# One address for your local AI — introducing ModelSaar

*Draft launch article for modelsaar.com and cross-posting. ~900 words. Status at the time of writing: development preview, no release tagged. Every claim below links to evidence in the repository; replace nothing with a stronger adjective.*

## The problem: several good models, one app at a time

If you run local models you probably run more than one. A coding model that follows tool-call schemas. A general model that can read a screenshot. A thinking model that is slow but careful. Each of them is a setting in each of your apps — the chat UI, the coding agent, the script you wrote last month — and every task starts with a small decision: which one, this time?

Change one model in Ollama and the setting is stale in four places. Ask an image question of the coding model and you get an answer that pretends it saw the picture. Nothing is broken; it is just friction, repeated all day.

## What ModelSaar does

ModelSaar is a small open-source gateway (Apache-2.0, Python, five dependencies) that sits between your apps and your inference backends. Apps connect once, to one address, with one key, and ask for a virtual model called `auto`. For each request the gateway:

1. reads the request's requirements — tools, images, strict JSON output, how many tokens the conversation needs;
2. crosses out every configured deployment that cannot do the job, on *verified* evidence: a capability that is unknown never counts as yes;
3. ranks what is left on measured task success where you have run the evaluation, labelled priors where you have not, minus costs for latency, loading and switching;
4. forwards the request unchanged, keeps the conversation and its tool calls on the same model, and
5. writes the decision down — exclusions with reasons, candidates with scores, the chosen deployment, the evidence used — without your prompt.

Three things stay distinct. Your apps keep their tools, memory and loops. Your backends (Ollama first; any OpenAI-compatible server with declared models) keep the weights and the hardware. ModelSaar selects, forwards and explains. It does not download models, accept model licences, or lower hardware requirements.

## What a decision looks like

A request "Fix the failing pytest in src/app.py" with a `bash` tool is a coding task that needs tool calling. All three models in the example configuration pass the tools probe, so none is excluded; the measured calibration evidence favours the coder model and it is chosen. An image question excludes the coder model outright ("image input unsupported, backend metadata") and goes to a vision-capable model. A tool result coming back goes to the model that issued the tool call, even if another would score higher, and the record says `failover_allowed: false`. When nothing qualifies — an image question with only a coding model configured — the answer is an HTTP 422 with a blocker and a remedy, never a degraded reply.

The website shows these as interactive illustrations: https://modelsaar.com/#walk-title. They are scripted; the recorded run they are based on is linked from the benchmarks page.

## What we measured, honestly

On 2026-10-11 we ran the evaluation harness against three models on an ASUS GX10 (Ollama 0.32.13): 15 calibration and 32 held-out synthetic tasks, temperature 0, a 400-token budget, executable or exact scoring with code run in a sandbox, no LLM judge. Automatic routing matched the strongest single model's task score (30 of 32 each), completed one more request (the image task the fixed model cannot take) and recorded no capability violation, with a higher p95 end-to-end latency because two requests went to a slower thinking model. Routing itself took under 1 ms at p95.

That is one run, n = 32, overlapping confidence intervals, a budget that penalises thinking models, three of eight available models. It does not show that routing is better in general. What it does show is where routing helps today: coverage (every request goes somewhere that can handle it) and transparency (you can see why). Raw per-request records, the configuration and model digests are in the repository, and `scripts/eval_aggregate.py` regenerates every number from them.

## Privacy by construction

The gateway binds to loopback, generates its keys, logs no prompts and sends no telemetry. Under the default `local_only` policy, deployments that Ollama marks as cloud-forwarded are excluded even when asked for by name. Nothing derived from a request leaves the gateway before policy filtering — tokenizer counts are requested only from deployments that already passed every filter, and the optional classifier must be local unless you opt in twice. Unsupported media is rejected before dispatch. These are regression-tested; the independent review that found the gaps, and the fixes, are public (F01–F18).

## First setup

You need Python 3.10+ (or `uv`) and a backend with at least one model. Then:

```
curl -fsSL https://modelsaar.com/install.sh | sh
```

The installer pins a reviewed commit, installs with `uv`, `pipx` or `pip --user`, runs `modelsaar init` (it finds Ollama on 127.0.0.1:11434), starts a temporary gateway, sends one request through `auto`, and prints your next step. Prefer to read it first: https://modelsaar.com/get-started/. Then set Base URL `http://127.0.0.1:8484/v1`, model `auto` and your generated key in any OpenAI-compatible app; `modelsaar client-config open-webui|opencode|openclaw|hermes` prints the exact settings.

## What is not there yet

No tagged release, PyPI package or container image. Real client workflows (Open WebUI, OpenCode, OpenClaw, Hermes) are configured from their documentation but not yet recorded end to end. No run against vLLM or llama.cpp server. Audio/video, Responses API and Anthropic Messages are explicit non-features. The roadmap is on the site; the verification report lists everything still marked NOT RUN with the command that would run it.

If you try it on your own models, the most useful thing you can send is a decision record that surprised you: `modelsaar decisions --limit 10` and the `doctor` output are what the issue templates ask for.

— Source: https://github.com/gopalasubramanium/modelsaar · Site: https://modelsaar.com
