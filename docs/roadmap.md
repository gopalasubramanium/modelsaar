# Roadmap (not implemented in 0.1)

Later milestones, each with its own tests before being described as supported:

* Native decision-model adapters (Ollama `/v1/systemone`: clef, nimble, laya) as routing classifiers
  and as a `/v1/decisions`-style endpoint.
* Audio/video inputs; multimodal embeddings (EmbeddingGemma 2 image/video/audio); OCR pipeline
  (GLM-OCR with layout stage) and guardrail pipelines (Granite Guardian) as separate results.
* Responses API and Anthropic Messages with fail-closed translation (currently explicit 501).
* Exact tokenization for more runtimes; Ollama served-context detection improvements.
* Managed model lifecycle (keep-alive/unload) under leases and locks; composition with llama-swap.
* Cascades/ensembles; distributed scheduling across hosts.
* Opt-in adaptive learning from outcomes with versioning, holdout evaluation, privacy controls and
  rollback.
* Optional LLM-judge scorers in the evaluation harness (identity, bias and cost disclosed).
* PyPI package and container image publication (requires separate authorization).
