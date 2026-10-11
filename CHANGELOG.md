# Changelog

## 0.1.0 (unreleased, 2026-10-11)

First release: OpenAI-compatible gateway (`/v1/models`, `/v1/chat/completions` incl. SSE,
`/v1/embeddings`, health/readiness), Ollama + generic OpenAI-compatible adapters, deployment
registry with three-state capabilities and fingerprints, deterministic requirements/eligibility/
ranking pipeline with optional local classifier, affinity (sessions + tool round trips), admission
control, pre-commit-only failover, decision records and inspection API/status page, probes,
verified starter catalogue, CLI (`init discover probe serve status doctor explain decisions test
client-config keys config eval demo uninstall`), client configuration generators for Open WebUI,
OpenClaw, OpenCode V1/V2 and Hermes Agent, evaluation harness with baselines, fault-injection test
suite, CI, Dockerfile/compose.
