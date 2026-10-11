# X / short-thread draft (6 posts, each ≤280 chars)

1/ Running several local models means picking one in every app, every time. ModelSaar gives them one address: apps ask for "auto", the gateway picks a model that can actually do the job and tells you why. Open source, local-first. https://modelsaar.com

2/ Per request it checks what's needed — tools, images, strict JSON, context size — and crosses out every model without *verified* support. Unknown never counts as yes. If nothing qualifies you get a 422 with blockers and remedies, not a degraded answer.

3/ Tool round trips and chats stay on the model that started them. Failover happens only before a byte reaches you, never inside a tool exchange. Every decision is recorded without the prompt: modelsaar decisions / explain / the status page.

4/ Measured, not promised: one recorded run, 3 models, 32 held-out tasks — auto matched the best single model's score, completed one more request (the image task), 0 capability violations, higher p95 latency. n=32, CIs overlap. Raw records in the repo.

5/ An independent review found 18 real defects in the first public revision. All fixed with regression tests, in a draft PR anyone can read. Status: development preview, no release yet.

6/ Try it on the models you already have (Python 3.10+, Ollama or any OpenAI-compatible server): curl -fsSL https://modelsaar.com/install.sh | sh — read it first at https://modelsaar.com/get-started/ Feedback on vLLM/llama.cpp and Open WebUI setups especially welcome.
