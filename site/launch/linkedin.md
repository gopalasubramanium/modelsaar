# LinkedIn draft (first person, the owner's voice; ≤1,300 characters)

I built ModelSaar because I kept re-selecting models in every AI app I use.

It's a small open-source gateway (Apache-2.0, Python) that gives all your local AI one address. Apps connect once and ask for "auto"; ModelSaar sends each request to a model that can actually do the job — verified tool support, image input, JSON schemas, context size, your local-only policy — and records why. No cloud, no telemetry, no prompt logging. Your models stay in Ollama or any OpenAI-compatible server; your apps keep their own tools and memory.

Honest status: a development preview. In one recorded run on my own hardware, automatic routing and the best single model each scored 30/32; routing completed more requests (32 vs 31) with zero capability violations, at a higher p95 latency — one run, small n, overlapping intervals. An independent review found 18 real defects; the fixes are public, with regression tests.

If you run more than one local model, I'd value your feedback — especially on backends and apps I haven't verified yet.

https://modelsaar.com

#LocalAI #OpenSource #LLM #Ollama
