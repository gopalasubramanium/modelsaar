# Changelog

## Unreleased — `POST /v1/decisions`: decision-model endpoint (Ollama `/v1/systemone`), 2026-10-27

* **New endpoint `POST /v1/decisions`** (`protocol/decisions.py`, `Router.route_decisions`, `server.decisions`):
  typed questions (`choice` 2–255 options, `noul`, `score` 2–10 levels; 1–64 per request; optional base64
  `images`) about a `state` (string, object or array), answered by a decision-role deployment through
  `OllamaAdapter.decide` → `POST /v1/systemone`. `model` is a decision deployment id or `auto` (every
  decision-role deployment passing the hard filters — enabled, healthy, locality, memory feasibility,
  vision when images are sent — resident first, then by id; no quality scoring, choice explained in the
  record). Strict request validation names the offending field (`param`); `keep_alive`, `stream` and any
  other field are refused; state + questions are capped at the documented 64 KiB. Answers are validated
  against the questions (type, options/levels, finite probabilities and confidence in [0, 1], arg-max
  choice) → `502 decision_contract_violation` on violation. Errors follow the gateway's conventions
  (`401`, `404 model_not_found`, `422 no_eligible_deployment` with blockers, `503 admission_rejected`,
  `501 unsupported_backend`, upstream status + `upstream_error`, `504 upstream_timeout` with the slot
  held as uncertain). Decision records carry `endpoint: "decisions"`. Chat routing and defaults unchanged.
* `BaseAdapter.decide`/`OllamaAdapter.decide` accept object/array `state` and `images` (base64) per the
  documented contract; the fake backend refuses images on a non-vision decision model (400).
* Tests: `tests/test_decisions_endpoint.py` (33: success for all question types, `auto` residency
  preference, image routing, authentication, 16 invalid-request shapes, size/JSON limits, helper
  validation, role mismatch, unknown model/alias, images on a text-only model, no decision model
  discovered, unsupported backend, upstream 500/timeout, two malformed-answer shapes, chat unchanged).
  Site test count 248 → 281 (`site/check_site.py` consistency; site not published).
* **Request-size limits:** `_read_json` (all JSON routes) now reads the body incrementally and refuses it
  with `413` as soon as `server.max_request_bytes` is exceeded — a declared `Content-Length` above the
  limit is refused before reading, a chunked body is cut off at the limit — instead of buffering the whole
  body first; `/v1/decisions` additionally checks the re-serialised upstream request (JSON incl. base64
  images) against Ollama's documented 32 MiB whole-request limit before dispatch (`413`). Tests cover the
  declared, chunked, within-limit and upstream-limit cases on this route.
* Not done: any live call against a real decision model (fixture-tested only).

## Unreleased — routing: decision-model classifier (Ollama `/v1/systemone`), 2026-10-25

* **`routing.classifier.mode: decision`** (opt-in; default `chat`, unchanged): the optional classifier can
  now be a decision model — a deployment with `role: decision` such as Ollama's `nimble`, `clef` or `laya` —
  asked through its native endpoint (`OllamaAdapter.decide` → `POST /v1/systemone`, Ollama ≥ 0.35.0) one
  `choice` question whose criteria are the closed task-label set. The answer's arg-max label and that
  label's probability become the task refinement; the answer is validated strictly (type `choice`, labels
  from the closed set only, finite probabilities in [0, 1] with the choice as arg-max, confidence in
  [0, 1]) and any timeout, error or out-of-contract answer falls back to the deterministic label exactly
  as in chat mode. Nothing but `model`, `state` and `questions` is sent; no free text is generated.
* **Discovery:** an Ollama model whose `/api/show` capabilities list `decision` without `completion` is
  registered with `role: decision` (previously `generative` unless the catalogue matched it), so it is
  never offered or chosen for chat and an explicit request for it is refused.
* **Guards:** the router and `modelsaar doctor` refuse a role/mode mismatch (a generative model in
  `decision` mode or a decision model in `chat` mode) before any call; backends without a decision
  endpoint (`openai_compatible`) report `unavailable`. `/admin/status` → `classifier` now carries `mode`.
* Tests: `tests/test_decision_classifier.py` (answer validation, discovery, end-to-end refinement,
  ambiguity gating, acceptance bar, failure fallbacks, role guards, unsupported backend, defaults) against
  the fake backend's documented `/v1/systemone`; site test count updated to the collected total.
* Not done: a `/v1/decisions`-style endpoint; any live measurement (the classifier comparison of
  2026-10-25 used `mode: chat`).

## Unreleased — website: layout repair, rendered-layout checks, roadmap refresh, 2026-10-14

* **Command blocks:** the Copy button was positioned over the scrolling code and covered the end of the
  installation command, the API-key command and the connection example (3 of 5 home and 5 of 12 Get-started
  blocks at 1280 px; more at phone widths; in every label state). Each block is now a toolbar row (label +
  Copy) above a dedicated code area; shell commands wrap visually, structured text keeps its columns in a
  keyboard-focusable scroller; the clipboard value is the code's exact text (the install one-liner is
  checked byte for byte against `site/facts.py`).
* **"Where it fits" diagram:** the SVG's subtitle and step 4 ran past the gateway box (x 704). The page now
  uses semantic HTML cards with decorative connectors (theme-aware, stacked on narrow screens, accessible
  description); the downloadable SVG is repaired at source (wider box, two-line subtitle, fallback-font
  margins). Wording: "route the request; preserve continuity" replaces "forward unchanged" (the gateway
  consumes `session_id`/`cache_prompt`), also in How-it-works step 4 and the README.
* **Also found and fixed:** at 200 % text the home decision-record tables were clipped by the card's
  rounded-corner overflow (now a scroll wrapper) and the request-id header overflowed; the apps/backends/
  models definition list could not shrink on narrow screens; body text size is now in `rem` so browser
  text-size preferences apply.
* **Checks:** `site/browser_checks.py` is tiered — every sitemap route at 320/390/768/1024/1280/1440 px in
  both themes (console, document and element overflow, clipped text, Copy-button/code geometry in every
  label state, diagram labels inside their containers, the SVG's text boxes), breakpoint boundaries, 200 %
  text, 320 px reflow at device scale 4, fallback fonts, JavaScript disabled, expanded `<details>`, exact
  clipboard values, keyboard focus; Firefox and WebKit on representative pages; unavailable engines are
  reported NOT RUN. The `site` workflow gains a `browsers` job that requires all three engines and uploads
  screenshots. Regressions fail on the previous site (112 failures) and pass after the repair.
* **Roadmap and status:** completed work (hardening merged 2026-10-13, publication, installer, Odysseus
  contract, one-command upgrades) is no longer presented as future; independent reviews are attributed to
  the revisions they covered; owner-reported Odysseus chat on the GX10 (2026-10-14) is recorded as such;
  the Measured Routing Quality plan (`docs/plans/measured-routing-quality.md`) and a release-readiness list
  (`docs/release.md`) are added. Gateway package and public installer bytes are unchanged.

## Unreleased — installer: one-command upgrades with managed-service handling, 2026-10-14

* **Upgrade mode:** an existing configuration means upgrade — `init` never runs again; config, keys, state,
  backend, listening address and port are preserved (verified byte-identical and reported). The new revision is
  validated against the existing configuration *before* it becomes `envs/current`; the previous environment
  stays as the rollback target; concurrent runs are refused by a lock.
* **Linux user service:** `modelsaar.service` is restarted only when it belongs to this installation (ExecStart
  into the runtime directory or the installed executable) and uses this configuration; bounded readiness wait
  ("Waiting for service…"), the running revision is read from the process's mapped files, the routed check uses
  the restarted service, no temporary gateway is started. Already-current services are not restarted, stopped
  services stay stopped, foreign units are reported and left alone; a replacement that does not start is rolled
  back (previous environment + service), exit 3. A backend outage after a good restart is exit 2, never a rollback.
* **Effective address:** the health check and the summary use `server.host`/`server.port` from the configuration
  (e.g. `http://<lan-address>:8484/v1`), not a hard-coded loopback; "loopback only" is said only when it is true;
  `modelsaar serve` is suggested only when no managed service runs.
* **Summary:** installed and running revision, service state, endpoint, configuration/keys preservation, routing
  check, and what (if anything) is still required. Tests: harness cases for upgrade of an active matching service,
  same-revision repeat, inactive service preserved, failed replacement rolled back, unrelated unit refused — run
  against a real systemd user unit in CI (x86_64 and arm64), plus the existing fresh/repeat/failed-install cases.

## Unreleased — installer: atomic `envs/current` switch, previous environment retained, 2026-10-14

* **Installer defect (upgrade between commits):** `activate_env` replaced the `envs/current` symlink with
  `mv -f tmp current`; on GNU/Linux and macOS, when `current` points at an existing directory, that moves the
  temporary link *inside* the old environment and leaves `current` unchanged (exit 0), and the following
  cleanup removed the older environment the running service still used. Fixed: the symlink itself is
  replaced atomically with `os.replace` run by the newly installed environment's Python (the environment
  directory is never renamed — entry points carry absolute paths); the previous complete environment is kept
  for the running service and as rollback target; only environments older than that are removed; config,
  keys and state are untouched. New harness case 5d (install A, install B: `current` → B, B runs, A still
  runs, older environments removed) runs in CI on x86_64 and arm64; it fails against the previous script.

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
