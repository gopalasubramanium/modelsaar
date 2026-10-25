# Roadmap

## Status, 2026-10-14

Done (evidence in `CHANGELOG.md`, `docs/verification-report.md` and the repository's CI runs):

* Hardening accepted and merged on 2026-10-13 (PR #1); the three independent reviews covered
  `1122e1f` (F01–F18), `80276bb` (R1–R8) and `5cb7443` (alpha closure). Everything merged after that —
  website (PR #2), isolated installer (PR #3), Odysseus `session_id`/`cache_prompt` compatibility (PR #4),
  atomic environment switch (PR #5), one-command upgrades (PR #6) — was verified by the project's test
  suite and CI (installer cases against a real systemd user unit on x86_64 and arm64) and by live checks
  on the owner's hardware, not by an independent reviewer.
* Website published from the `gh-pages` output branch with a recorded build identity; the public
  installer pins gateway `cf56cdd3416d8c853b64111b9b40211e5b126031`, which the owner's GX10 runs.
* Owner-reported: Odysseus chat through ModelSaar on the GX10 is working, reported by the owner in
  conversation on 2026-10-14. Owner-reported use, not a project-recorded workflow; no client version or
  transcript is recorded and tool, vision, streaming and agent workflows through Odysseus were not reported.

Still open (unchanged limitations): the published benchmark used scorer `2026.10.11-2` at an earlier
revision; the optional live classifier was disabled; real-model embeddings, vLLM/llama.cpp backends and
the other client workflows are unverified; the macOS code-evaluation sandbox stays disabled pending
verification. See `docs/backlog-post-alpha.md`.

## Next milestone: Measured Routing Quality

Evaluate the current revision with the existing harness on a representative subset of the GX10's installed
models, with separate calibration and held-out splits, fixed-model and deterministic-rule baselines and an
optional classifier off/on comparison. Plan and commands: `docs/plans/measured-routing-quality.md`. The
run starts only with the owner's approval of a GX10 window; the simpler router stays if extra
classification does not demonstrate value.

## Later milestones (not implemented)

Each with its own tests before being described as supported:

* Native decision-model adapters (Ollama `/v1/systemone`: clef, nimble, laya): **as routing
  classifiers — implemented, opt-in (`routing.classifier.mode: decision`; see `docs/routing.md` §C),
  not yet measured live**; as a `/v1/decisions`-style endpoint — not implemented.
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
