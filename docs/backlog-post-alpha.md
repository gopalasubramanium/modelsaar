# Post-alpha backlog

Items deliberately left out of the public alpha (2026-10-12). None of these is claimed fixed or
verified; each names the gate that would close it.

| item | status in the alpha | closing evidence |
|---|---|---|
| macOS code-execution sandbox (`sandbox-exec` deny-by-default profile) | **disabled pending verification** — `code_exec` tasks are skipped on macOS unless `MODELSAAR_MACOS_SANDBOX=verify` | `run_mac_tests.command` → `mac-tests-PASSED` (sandbox tests executed under `sandbox-exec`, no skips); then re-enable by default |
| real-client walkthrough (Open WebUI, OpenClaw, OpenCode, Hermes) | NOT RUN; owner steps in `site/VALIDATION.md` | one recorded workflow per client (`modelsaar decisions` showing the request) |
| live evaluation under scorer `2026.10.12-3` | NOT RUN; the quoted result keeps scorer `2026.10.11-2` | a separately labelled GX10 run (`run_live_verify.command`) |
| real-model embeddings; vLLM / llama.cpp backends; `/tokenize` | NOT RUN (fixture-only) | live run with a declared `embeddings:` contract / a generic server |
| assumed residency for runtimes that cannot report it | conservative indefinite assumption unless `assumed_residency_ttl_s` is set | a residency signal for those runtimes, or operator guidance per runtime |
| CI run at the published revision | definition only; no run exists until the branches are pushed | green run on the PR revision |
| evaluation with a reasoning-matched budget and all eight GX10 models | not run | separately labelled run |
| website copy refinement, SEO, launch optimisation | out of scope for the alpha | after real-user feedback (`site/launch/feedback-log.md`) |
