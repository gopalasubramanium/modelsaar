# LinkedIn draft (first person, the owner's voice; ≤1,300 characters)

I built ModelSaar because I kept re-selecting models in every AI app I use.

It's a small open-source gateway (Apache-2.0, Python) that gives all your local AI one address. Apps connect once and ask for "auto"; ModelSaar sends each request to a model that can actually do the job — verified tool support, image input, JSON schemas, context size, your local-only policy — and records why. No cloud, no telemetry, no prompt logging. Your models stay in Ollama or any OpenAI-compatible server; your apps keep their own tools and memory.

Honest status: a development preview. One recorded run on my own hardware shows automatic routing matching the best single model's score with better coverage and zero capability violations — one run, small n, overlapping intervals. An independent review found 18 real defects; the fixes are public, with regression tests.

If you run more than one local model, I'd value your feedback — especially on backends and apps I haven't verified yet.

https://modelsaar.com

#LocalAI #OpenSource #LLM #Ollama
