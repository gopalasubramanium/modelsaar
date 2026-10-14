# Changelog

## Unreleased — client compatibility: `session_id` / `cache_prompt` (Odysseus), 2026-10-13

* **Gateway:** Odysseus adds llama.cpp-style `session_id` and `cache_prompt: true` to requests it sends to a
  self-hosted endpoint; the gateway rejected them as unknown fields. Both now have a defined, gateway-owned
  meaning and are never forwarded: `session_id` (validated: non-empty printable string ≤ 256 chars) is
  caller-scoped conversation affinity with a fixed precedence among session hints
  (`modelsaar.session` → `session_id` → configured headers → configured body fields; conflicting ids are
  reported as `affinity.ignored_hints`); `cache_prompt: true` is an advisory hint whose disposition is
  recorded in the decision (`compat.cache_prompt`); `cache_prompt: false` is refused with
  `400 unsupported_capability` before dispatch because no shipped backend path can guarantee a per-request
  cache bypass. Non-boolean `cache_prompt` and invalid `session_id` values are `400` naming the field; every
  other unknown field is still rejected. Decisions carry a `compat` map. Docs: `docs/clients/odysseus.md`.

## Unreleased — one-line installer: isolated installation on externally managed Python, 2026-10-13

* **Installer (`site/static/install.sh`):** the `python3 -m pip install --user` fallback is gone — on
  Debian/Ubuntu (PEP 668) it failed with `error: externally-managed-environment`. The installer now uses
  your `uv` or `pipx` if present, otherwise a user-owned virtual environment under
  `~/.local/share/modelsaar/envs/<commit>` created by your Python 3.10+, and when that Python cannot
  create one (no `python3-venv`, older Python) it downloads one pinned, checksum-verified official `uv`
  release binary (0.12.24; Linux x86_64/aarch64 gnu+musl, macOS) into `~/.local/share/modelsaar/uv` and
  lets it build the environment (uv fetches a Python of its own, 3.10–3.13, only when none exists). The package is installed from the pinned commit's GitHub source archive
  (no `git` needed). The exact installed executable is used for `init` and the routed check; a
  `~/.local/bin/modelsaar` link is created only when that name is free; repeat runs reuse a complete
  environment and a working installation is replaced only after the new one installed; exit codes 0/1/2
  distinguish installed+configured+routed, not installed, and routing check failed. Gateway package pin
  unchanged (`d6e09e7`).
* **Tests:** `scripts/installer_fallback_tests.py` runs the real installer with real package
  installations on externally managed Ubuntu 24.04 (reproduction of the old failure with the kept
  fixture, venv path, no-ensurepip bootstrap with checksum tamper check, uv/pipx paths, repeat and
  failed-attempt preservation, exit codes) against the controlled fake backend; CI job `installer` runs
  it on `ubuntu-24.04` and `ubuntu-24.04-arm`; `installer-public` (manual) runs the literal
  `curl -fsSL https://modelsaar.com/install.sh | sh` on both.

## Unreleased — alpha closure pass, 2026-10-12 (correction review R1-C, R2-A/B, R4-C, R7-C)

* **Residency (R2-A/B):** a failed `/api/ps` query is no longer an empty observation — known and
  assumed occupancy is kept until the query succeeds (`loaded_models()` returns `None` on failure);
  a connection refused before the request was sent releases the reservation without assuming
  residency, so failover is not blocked by phantom weights.
* **Streams (R4-C):** the upstream `[DONE]` is held back; the gateway emits exactly one terminal
  marker after validation, so a client reading to the first `[DONE]` sees any error frame.
* **Evaluator (R1-C, R7-C):** `--probe` goes through gateway admission, holds after an uncertain
  timeout and reports deferred deployments; routed-policy checkpoints are bound to the eligible
  deployment set (`eligible_set_key`) so changed alternatives re-run.
* **macOS code execution:** `sandbox-exec` is disabled in this alpha pending verification
  (`MODELSAAR_MACOS_SANDBOX=verify` enables it for the owner's verification run); `code_exec` tasks
  are skipped on macOS otherwise.

## Unreleased — correction pass for the second independent review (R1–R8), 2026-10-12

The reviewer's desired-contract tests are included verbatim (`tests/independent_review_2026_10_11/`).

* **Inference occupancy (R1):** a read timeout *while streaming*, an embedding timeout and a probe
  timeout hold the slot and pool memory as uncertain (`admission.uncertain_hold_s`) like non-stream
  timeouts; a probe run stops after the first uncertain timeout and reports `skipped`. New decision
  outcomes `stream_timeout_after_commit`, `stream_invalid_after_commit`, `upstream_timeout`.
* **Memory accounting (R2):** completed dispatches leave their weights counted as assumed resident
  until a residency observation reconciles them; `ResourcePool.assumed_residency_ttl_s` for runtimes
  that cannot report residency; `unknown_memory_policy: reject` applies to every counted member;
  `/admin/status` shows `memory_assumed_resident`.
* **Embedding identity (R3):** the alias identity is anchored before dispatch (declared > recorded >
  first member in contract order with a verified identity) and recorded synchronously.
* **Deadlines and stream validation (R4):** every upstream call uses the tighter of the server and
  backend deadlines (an explicit `None` never disables the timeout); SSE data frames that are not a
  completion structure invalidate the stream and are not relayed; comments, keepalives and usage-only
  frames are fine.
* **First use (R5):** `GET /healthz` returns `service: modelsaar`; `modelsaar test` identifies the
  listener before sending the API key and requires ModelSaar routing attribution; an unrelated
  listener is reported as a port collision.
* **Evaluator (R7):** `code_exec` completion evidence is a nonce-keyed record written by the trusted
  runner (model stdout captured separately); tool arguments must conform to the declared schema;
  checkpoint records are bound to task content, scorer version, budgets, routing configuration and
  deployment fingerprint (format 2; legacy records are re-run and counted in `resume_rejected`);
  bubblewrap binds only the Python runtime and system libraries; the macOS profile is
  deny-by-default. `SCORER_VERSION` is `2026.10.12-3`; saved results keep their own scorer label.

## Unreleased — hardening pass (branch `hardening/review-2026-10-11`, 2026-10-11)

Fixes for the eight findings of the independent review of commit `1122e1f`; each has a regression
test in `tests/test_hardening_2026_10_11.py` (see docs/progress.md for the finding → fix → test table).

* **Privacy:** policy filters run before any payload-bearing operation; `/tokenize` counts only for
  policy-allowed deployments under one deadline, labelled `tokenize:<backend>+template-estimate`;
  classifier must be local unless `routing.classifier.allow_remote` + `locality_mode: allow_remote`;
  unknown content part types → `400 unsupported_content_type`.
* **Dispatch contract:** no failover inside tool round trips, reasoning continuation or pinned sessions
  (`failover_allowed`/`failover_note` in decisions); timeouts hold capacity as uncertain; circuit success
  and session pinning only after validated completion; attribution per attempt; non-completion 200s →
  `502 upstream_bad_response`.
* **Resources:** `resource_pools[].memory_gb` enforced (`memory_margin_gb`, `unknown_memory_policy`);
  `POST /admin/probe`; `modelsaar probe` coordinates through a running gateway (`--offline`,
  `--allow-concurrent`); live eval refuses to run next to a listening gateway without `--allow-concurrent`.
* **Embeddings:** deployment identity (digest / `backends[].models[].identity`); aliases bound to one
  verified identity (`embeddings[].identity`); request `dimensions`/`encoding_format` guarded; output
  validated (`502 embedding_contract_violation`); non-empty prefixes rejected.
* **Evidence:** fingerprints include endpoint and identity; evidence scheme 2 (old rows kept, unused,
  reported by `doctor`); measurements carry conditions.
* **Evaluator:** sandbox-or-skip code execution, strict scorers, schema-validated classifier output,
  `--checkpoint`/`--resume`, dataset/scorer revision recorded.
* **Files/first run:** mode-preserving `client-config --apply` with private temp files and unique backups;
  uninstall removes only owned files and refuses symlinks; `modelsaar keys ensure` + container CMD;
  `init --profile` sets the `auto` alias profile; `scripts/compose-smoke.sh`, `scripts/install-check.sh`,
  `scripts/live_verify.sh` (resumable live verification), `scripts/live_client_checks.py`.
* `.gitignore` no longer hides `docs/live-runs/**/eval-*.json`; the GX10 artefacts are tracked.

## 0.1.0 (unreleased, 2026-10-11)

First release: OpenAI-compatible gateway (`/v1/models`, `/v1/chat/completions` incl. SSE,
`/v1/embeddings`, health/readiness), Ollama + generic OpenAI-compatible adapters, deployment
registry with three-state capabilities and fingerprints, deterministic requirements/eligibility/
ranking pipeline with optional local classifier, affinity (sessions + tool round trips), admission
control, pre-commit-only failover, decision records and inspection API/status page, probes,
verified starter catalogue, CLI (`init discover probe serve status doctor explain decisions test
client-config keys config eval demo uninstall`), client configuration generators for Open WebUI,
OpenClaw, OpenCode V1/V2 and Hermes Agent, evaluation harness with baselines, fault-injection test
suite, CI, Dockerfile/compose. Verified live against Ollama 0.32.13 on an ASUS GX10 (8 models);
fixes from that run: thinking-aware probes, discover/doctor read stored evidence, fingerprint excludes
served context, `eval --deployments` subset filter.
