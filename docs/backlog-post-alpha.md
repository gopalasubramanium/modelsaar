# Post-alpha backlog

Items deliberately left out of the public alpha (2026-10-12). None of these is claimed fixed or
verified; each names the gate that would close it.

| item | status in the alpha | closing evidence |
|---|---|---|
| macOS code-execution sandbox (`sandbox-exec` deny-by-default profile) | **disabled pending verification** — `code_exec` tasks are skipped on macOS unless `MODELSAAR_MACOS_SANDBOX=verify` | `run_mac_tests.command` → `mac-tests-PASSED` (sandbox tests executed under `sandbox-exec`, no skips); then re-enable by default |
| real-client walkthrough (Open WebUI, OpenClaw, OpenCode, Hermes) | NOT RUN by the project; owner steps in `site/VALIDATION.md`. **Odysseus:** chat through ModelSaar on the GX10 is working, reported by the owner in conversation on 2026-10-14 (owner-reported use after the `cf56cdd` upgrade; not a project-recorded workflow; tool/vision/streaming/agent workflows not reported) | one recorded workflow per client (`modelsaar decisions` showing the request) |
| live evaluation under scorer `2026.10.12-3` | NOT RUN; the quoted result keeps scorer `2026.10.11-2` | a separately labelled GX10 run (`run_live_verify.command`) |
| real-model embeddings; vLLM / llama.cpp backends; `/tokenize` | NOT RUN (fixture-only) | live run with a declared `embeddings:` contract / a generic server |
| assumed residency for runtimes that cannot report it | conservative indefinite assumption unless `assumed_residency_ttl_s` is set | a residency signal for those runtimes, or operator guidance per runtime |
| CI run at the published revision | **done** — green runs exist on `main` for every merged PR (#1–#6, 2026-10-13/14), including the installer job against a real systemd user unit on x86_64 and arm64 | — |
| evaluation with a reasoning-matched budget and all eight GX10 models | not run; planned as the next milestone (`docs/plans/measured-routing-quality.md`, representative subset first, expanding within an explicit budget) | separately labelled run |
| website copy refinement, SEO, launch optimisation | out of scope for the alpha (the 2026-10-14 layout repair fixed component overlaps and added rendered-layout checks; copy and SEO untouched) | after real-user feedback (`site/launch/feedback-log.md`) |
