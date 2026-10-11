# ModelSaar 0.1.0 — independent adversarial review

Scope: `src/modelsaar/**` at `/home/claude/modelsaar`, checked against README.md, docs/routing.md,
docs/architecture.md, docs/privacy.md (no `/home/claude/mnt-spec.md` present). No files in the
repository were modified. All probe scripts live in the session scratchpad.

Baseline: `python -m pytest -q` → 48 passed (CPython 3.13.16 venv **and** a fresh CPython 3.10.20
venv built with `uv`); `ruff check src tests` → clean. Installed: starlette 1.7.0, uvicorn 0.54.0,
httpx 0.28.1, pydantic 2.14.0, anyio 4.15.1.

"Confirmed by running" = reproduced with the fake backend / a custom backend / a unit call.
"By inspection" = read from the code, not executed.

---

## Findings

### 1. HIGH — Unknown context length disables the context filter (silent truncation path)
- **File:** `src/modelsaar/routing/eligibility.py:106` (`if dep.context_length and total_tokens > dep.context_length`)
- **What:** For a deployment whose `context_length` is `None` — every model discovered via
  `GET /models` on an `openai_compatible` backend that is not declared under `backends[].models`
  (`adapters/openai_compat.py:50-67` never sets it) — the effective-context check is skipped
  entirely. The deployment becomes eligible for any request size. llama.cpp's server truncates
  prompts by default; LM Studio and others behave similarly. This directly violates "never silently
  truncate history" and the README's "Unknown required capabilities never qualify" principle
  (context is treated as known-infinite instead of unknown).
- **Confirmed by running:** custom `openai_compatible` backend with an undeclared model; a
  2,000,000-char prompt with `max_tokens=100000` (estimate 800,009 tokens) was routed to
  `vllm/undeclared-model` and forwarded (HTTP 200); the declared 8k model was correctly excluded.
- **Fix:** treat `context_length is None` as a hard exclusion with remedy "declare `context_length`
  under `backends[].models` or add an operator override" (mirroring the capability tri-state), or at
  minimum apply a conservative assumed default (as the Ollama adapter does with 4096) and label its
  provenance. Also make `doctor` fail, not warn, on unknown context for routable deployments.

### 2. HIGH — Negative `max_tokens` bypasses the context filter
- **File:** `src/modelsaar/routing/tokens.py:85-89`; `src/modelsaar/protocol/openai.py:118-119` (no bounds on `max_tokens`/`max_completion_tokens`)
- **What:** `output_allowance = int(body["max_tokens"])` is added to the input estimate without
  validation. A negative value makes `total_tokens` negative, so `total_tokens > context_length` is
  never true. Ollama interprets a negative `num_predict` as "unlimited" and silently truncates the
  prompt to `num_ctx`; the gateway forwards the oversized request as if it fit.
- **Confirmed by running:** `model=ollama/small:1b` (8192 ctx), 20,000-word prompt
  (input_estimate 35,010), `max_tokens=-100000` → HTTP 200, forwarded; the decision record shows
  `total: -62942`. The same prompt with `max_tokens=50` is correctly rejected (422).
- **Fix:** validate `max_tokens`/`max_completion_tokens` as `>= 1` (reject otherwise with 400), and
  clamp `output_allowance` to `max(1, …)` in `estimate_chat_tokens` as defence in depth.

### 3. HIGH — Tool round-trip affinity pins to the *oldest* answered tool-call id in the history, enabling cross-model handover
- **Files:** `src/modelsaar/routing/requirements.py:178-220` (`outstanding_tool_call_ids` = every
  answered tool-call id in the whole conversation; the comment "ids in this round trip" is wrong),
  `src/modelsaar/routing/affinity.py:95-100` (`lookup_tool_round` iterates ids in history order and
  returns the first hit), `src/modelsaar/routing/router.py:328-345`.
- **What:** After the first round trip, the exact-set key never matches again, so the per-id
  fallback wins and it is evaluated oldest-first. If the current round's tool calls were issued by
  deployment B but an earlier round in the same conversation was issued by A (user switched model,
  or `auto` rerouted after A was unhealthy), the follow-up carrying B's tool results is pinned to A —
  exactly the handover the spec forbids. Conversely, if A is now ineligible the request fails with
  `affinity_broken` even though B (the real issuer) is healthy.
- **Confirmed by running:** turn 1 `auto`+image+tools → `big:27b` issues `call_big_27b_0`; turn 2
  answers it; turn 3 explicit `ollama/small:1b` issues `call_small_1b_0`; turn 4 (`auto`, tool
  result for `call_small_1b_0`) → routed to **`ollama/big:27b`**, decision
  `affinity.tool_round_trip = ollama/big:27b`, `outstanding = [call_big_27b_0, call_small_1b_0]`.
  With `big:27b` disabled the same turn returns 422 "tool round trip was started on ollama/big:27b".
- **Fix:** define the outstanding set as the `tool_calls` of the *last assistant message* that is
  followed only by `tool` messages (the current round), not all answered ids; and iterate newest
  first in `lookup_tool_round`. Record in the decision which id produced the pin.

### 4. MEDIUM — A truncated upstream stream is relayed as a complete answer (`[DONE]` synthesised, outcome `ok`)
- **File:** `src/modelsaar/server.py:283-289, 310-323`; `src/modelsaar/protocol/sse.py:113-114` (`StreamObserver.error` is never read)
- **What:** If the backend closes the HTTP response cleanly without a `finish_reason` chunk or
  `[DONE]` (crash handler, proxy cut-off, worker restart), `_relay` reaches `completed = True`,
  appends `data: [DONE]`, releases the slot and records `outcome=ok`. The client receives a
  partial answer indistinguishable from a complete one. Likewise an upstream `{"error": ...}` frame
  mid-stream is passed through but the decision is still recorded as `ok`, so failures are invisible
  in `/admin/decisions` and the circuit breaker never sees them.
- **Confirmed by running:** custom backend emitting one content chunk then ending → client got the
  chunk + `data: [DONE]`, decision `outcome: ok events=1 finish=None`. Backend emitting
  `data: {"error":...}` then ending → `outcome: ok events=2`.
- **Fix:** when the stream ends with `obs.finish_reason is None and not obs.saw_done` (and no usage
  chunk), emit the `upstream_stream_error` frame instead of a bare `[DONE]` and record
  `stream_truncated_after_commit`; when `obs.error` is set, record `upstream_error_in_stream` and
  count a circuit failure.

### 5. MEDIUM — Token estimate is not conservative for CJK/non-Latin text (chars/3)
- **File:** `src/modelsaar/routing/tokens.py:82` (`math.ceil(chars / cfg.chars_per_token)`), `config.py:185`
- **What:** chars/3 is pessimistic for English but optimistic for Chinese/Japanese/Korean, Thai,
  emoji and byte-fallback scripts, where common tokenizers produce ≥1 token per character (often
  1.3–2 for Llama-family BPE). The README promises the estimate "is deliberately pessimistic so that
  a deployment is never chosen whose context the real request would overflow"; for CJK this is
  false and Ollama will truncate silently.
- **Confirmed by running:** 6,400 Chinese characters → `input_estimate 2250`, routed to
  `plain:3b` (ctx 4096). Any real CJK tokenizer yields ≥ ~4,500–6,400 tokens here.
- **Fix:** weight characters by script class (e.g. count CJK/Hangul/Thai/emoji code points as ≥1.5
  tokens each, other non-ASCII as ≥0.5) before dividing; keep the 5 % margin. Also reconsider the
  fixed `image_tokens=1200` for dynamic-resolution VLMs.

### 6. MEDIUM — Declared models on `openai_compatible` backends lose adapter-level capabilities (`streaming` becomes `unknown`)
- **File:** `src/modelsaar/adapters/openai_compat.py:82` (`merge_capabilities(dep, d.capabilities.model_dump(), "operator")`) vs `src/modelsaar/routing/router.py:119` (filters `v != "unknown"`)
- **What:** `Capabilities.model_dump()` includes every key with its default `"unknown"`; at
  operator priority these overwrite the adapter's `streaming: supported` claim. Any model declared
  under `backends[].models` (the documented way to give vLLM/llama.cpp models a context length)
  therefore fails every streaming request with "capability streaming is unknown" until probed.
- **Confirmed by running:** declared model shows `streaming=unknown(operator)`; `stream: true`
  request → 422 with that blocker. The undeclared sibling keeps `streaming=supported(adapter)`.
- **Fix:** filter `"unknown"` values before merging (as `_apply_overrides` does), or make
  `merge_capabilities` skip `"unknown"` unless the caller explicitly asks to reset.

### 7. MEDIUM — Remote image URL detection only matches lowercase `http://`/`https://`
- **File:** `src/modelsaar/routing/requirements.py:201`
- **What:** URL schemes are case-insensitive. `HTTP://`, `Https://`, protocol-relative `//host/`,
  `ftp://`, `file:///etc/passwd` and leading-whitespace variants are not flagged, so the request
  is routed and forwarded to a vision deployment. The gateway itself does not fetch, but the
  backend may: vLLM fetches remote `image_url`s by default and can read local files when
  `--allowed-local-media-path` is set — i.e. a client-controlled SSRF/file-read through the
  backend, which docs/privacy.md says "never fetched" prevents.
- **Confirmed by running:** all five variants → HTTP 200 on `ollama/big:27b`, decision
  `has_remote_image_url: False`.
- **Fix:** parse with `urllib.parse.urlsplit` after `.strip()`; accept only `data:` URLs (and
  `data:image/...;base64,` specifically) when `fetch_remote_media` is false; treat any other scheme,
  including empty/protocol-relative, as remote.

### 8. MEDIUM — `modelsaar uninstall` recursively deletes the config file's parent directory
- **File:** `src/modelsaar/cli.py:472-487` (`home = path.parent; shutil.rmtree(home)`)
- **What:** The command claims to remove "ONLY the gateway's own files" but deletes whatever
  directory contains the config. With `--config ~/configs/modelsaar.yaml` or
  `MODELSAAR_CONFIG=~/modelsaar.yaml` (parent = `$HOME`) plus `--yes`, unrelated data is destroyed.
- **Confirmed by running:** `MODELSAAR_CONFIG=<dir>/shared/modelsaar.yaml modelsaar uninstall --yes`
  removed `<dir>/shared/other/notes.txt`.
- **Fix:** delete only the known artefacts (config file, `keys/`, `state/` as resolved from the
  config), and refuse `rmtree` unless the directory is `MODELSAAR_HOME`/`~/.modelsaar` and contains
  nothing else.

### 9. MEDIUM — Secret files are world-readable between creation and `chmod`
- **File:** `src/modelsaar/config.py:346-354` (`write_config_atomic`), `:367-375` (`write_key_file`); `src/modelsaar/store.py:56-62`
- **What:** `tmp.write_text(...)` creates the temp file with the process umask (0644 by default),
  then `os.replace`, then `chmod 0600`. The API key, admin key and a config that may contain
  `backends[].api_key` are briefly world-readable; the SQLite `-wal`/`-shm` side files are never
  chmod'ed at all. docs/privacy.md advertises "mode 600" keys.
- **Confirmed by running:** with umask 022 the temp file was `0o644` at the moment of `os.replace`,
  `0o600` afterwards.
- **Fix:** create with `os.open(tmp, O_WRONLY|O_CREAT|O_EXCL, 0o600)` (or `tmp.touch(0o600)` then
  write), `fsync` before `os.replace` to make "atomic" also durable; set `umask`/chmod for the
  SQLite directory or use `PRAGMA journal_mode=DELETE` for the keys of a single-process store.

### 10. MEDIUM — Non-ASCII bearer token crashes the request handler (HTTP 500 + traceback)
- **File:** `src/modelsaar/security.py:41` (`hmac.compare_digest(token, k)` on `str`)
- **What:** `compare_digest` raises `TypeError` for non-ASCII `str` operands. Starlette decodes
  header bytes as latin-1, so any byte ≥0x80 in `Authorization`/`x-api-key` becomes a non-ASCII
  string → unhandled exception → 500 with a server-side traceback instead of 401. Unauthenticated
  and trivially triggerable.
- **Confirmed by running:** raw socket `Authorization: Bearer msk_\xe9abcdefgh` → `HTTP/1.1 500
  Internal Server Error`, traceback ends in `TypeError: comparing strings with non-ASCII characters`.
- **Fix:** compare `token.encode("utf-8", "surrogateescape")` against `k.encode()` (bytes are
  always accepted), or pre-filter with `token.isascii()` → 401.

### 11. MEDIUM — Documentation claims exact `/tokenize` counting that is never used
- **Files:** `src/modelsaar/routing/tokens.py:3`, `src/modelsaar/adapters/openai_compat.py:5, 87-107`, `README.md:124,137`, `docs/architecture.md:27,48`
- **What:** `BaseAdapter.tokenize` / `OpenAICompatAdapter.tokenize` exist but nothing in
  `routing/` calls them; `estimate_chat_tokens` always returns `method="estimate:…"`. The README's
  "Token counts are conservative estimates unless the backend exposes `/tokenize` (vLLM)" and the
  support-matrix row "vLLM `/tokenize` … F (fixture)" are therefore untrue (no fixture exercises
  it either). Same for `config.py:1-5` / `docs/architecture.md:76-80`: there is no config reload
  path in the code.
- **Confirmed by running:** `grep -rn tokenize src` shows definitions only.
- **Fix:** either wire `tokenize()` into `analyze_chat` (async, cached per fingerprint, bounded
  timeout, fall back to the estimate) or remove the claims from docs/README/matrix.

### 12. LOW — Catalogue matching ignores backend type; trained context becomes "effective" context
- **File:** `src/modelsaar/catalogue/__init__.py:32-40, 56-57`
- **What:** `match.ollama` patterns are matched against any `dep.model`, and
  `context_length` (a model-card *trained* length, e.g. 131072) is written into `dep.context_length`
  when it is `None` — i.e. precisely for the unknown-context `openai_compatible` deployments from
  finding 1. A llama.cpp server running `gemma4` at `-c 8192` would be treated as a 131k context.
  Broad globs (`nimble*`, `clef*`, `laya*`, `tev1*`) also match unrelated names. (By inspection.)
- **Fix:** never let the catalogue set `context_length` (or record it only as
  `raw_metadata["trained_context_length"]`); match `ollama` patterns only for `backend_type == "ollama"`.

### 13. LOW — Trailing partial SSE frame without a blank line is concatenated with `[DONE]`
- **File:** `src/modelsaar/protocol/sse.py:61-66` (`flush` only appends `\n\n` when the frame does not end in `\n`), `server.py:283-289`
- **What:** A final frame ending in a single `\n` is yielded verbatim; when it has no `model` key
  (so `rewrite_model_field` returns `ev.raw`), the client sees one event whose data is
  `{"…"}\n[DONE]` → JSON parse error. Upstream error frames are the realistic case.
- **Confirmed by running (unit):** `feed(b'data: {"a":1}\n')` + `flush()` + `[DONE]` →
  `b'data: {"a":1}\ndata: [DONE]\n\n'`.
- **Fix:** in `flush`, always normalise to end with `\n\n`; in `rewrite_model_field`, return a
  normalised frame rather than `ev.raw`.

### 14. LOW — `Admission._tasks` grows without bound
- **File:** `src/modelsaar/routing/admission.py:96`
- **What:** every `mark_uncertain` adds the `_expire` task to a set that is never pruned.
- **Confirmed by running:** 40-way disconnect stress → 29 finished tasks retained after expiry.
- **Fix:** `t.add_done_callback(self._tasks.discard)`.

### 15. LOW — `Admission.acquire` rollback catches `Exception`, not `BaseException`
- **File:** `src/modelsaar/routing/admission.py:146-151`
- **What:** a `CancelledError` while waiting for the *second* slot (pool) leaves the first slot's
  `active` incremented forever. Not reachable with the current uvicorn/Starlette combination (the
  handler is not cancelled on disconnect), but it is the kind of invariant that should not depend
  on the server's behaviour. (By inspection.) Otherwise the Condition usage is correct: the lock is
  re-acquired before `AdmissionRejected` is raised, `waiting` is decremented in `finally`, slots
  are always acquired backend→pool (no lock-order deadlock), and `release`/`mark_uncertain` are
  idempotent. Stress test: `active` and `uncertain` returned to 0.
- **Fix:** `except BaseException:` for the rollback; same for `server.py` (see 16).

### 16. LOW — Reservation is released only on `AdapterError`; other exceptions leak the slot
- **File:** `src/modelsaar/server.py:166-239`
- **What:** `adapter.chat()` is only expected to raise `AdapterError`; any other exception (bug,
  `CancelledError`, a future adapter) escapes before `reservation.release()`, permanently
  consuming a slot. (By inspection.)
- **Fix:** wrap dispatch in `try/except BaseException` that releases and re-raises, or hand the
  reservation to the `StreamingResponse` path only after a successful open and release in a
  `finally` otherwise.

### 17. LOW — Probes persist transient 5xx as `unsupported` with probe provenance
- **File:** `src/modelsaar/probes.py:116-117, 161-162, 213-214`
- **What:** a backend 5xx during `probe_tools`/`probe_json_schema`/`probe_vision` becomes a stored
  `unsupported` verdict (priority above source claims) keyed by fingerprint; the deployment is then
  excluded from tool/schema/vision requests until someone re-probes. (By inspection.)
- **Fix:** map `status >= 500` and transport errors to `unknown` (not stored); only 4xx is evidence.

### 18. LOW — `/admin/decisions?limit=` is not validated
- **File:** `src/modelsaar/server.py:470-471`
- **Confirmed by running:** `limit=abc` and `limit=1e3` → 500; `limit=-5` → SQLite `LIMIT -5` =
  unlimited. Admin-only, but still an unhandled exception path.
- **Fix:** parse with try/except, clamp to `1..500`.

### 19. LOW — `ConnectTimeout` is classified as non-retryable
- **File:** `src/modelsaar/adapters/base.py:115-120, 132-135`
- **What:** `httpx.ConnectTimeout` is not a `ConnectError`, so it falls into the generic
  `HTTPError` branch (`retryable=False`, kind `transport`). Nothing was sent, so this is exactly
  the connection-level failure the pre-commit failover is meant for. (By inspection.)
- **Fix:** add `except (httpx.ConnectError, httpx.ConnectTimeout)` → `retryable=True`.

### 20. LOW — Ollama adapter alters the request without recording it
- **File:** `src/modelsaar/adapters/ollama.py:185-220`, `openai_compat.py:120-123`
- **What:** (a) `tool_choice=none` is implemented by deleting the `tools` array; (b) every
  streaming request gets `stream_options.include_usage=true` injected, which adds a final chunk
  with `choices: []` that some older OpenAI-SDK consumers reject. The `notes` returned by
  `translate_chat_body` are discarded (`fwd, _ = …`), so neither change appears in the decision
  record despite "forwards the request unchanged … transparent routing decisions".
- **Confirmed by running:** `tool_choice:"none"` → backend received fields `['messages','model','stream']` only.
- **Fix:** attach the translation notes to `Decision` (e.g. `dec.translation`), and only set
  `include_usage` when the client did not send `stream_options` (or make it configurable).

### 21. LOW — Session affinity is established for the pre-dispatch choice even when dispatch fails over
- **File:** `src/modelsaar/routing/router.py:368-369` vs `server.py:222-226`
- **What:** `affinity.set()` runs inside `route_chat`; if the server then fails over to
  `next_id`, the session stays pinned to the failing deployment and each following turn repeats
  the failover until the circuit opens (threshold 3). (By inspection.)
- **Fix:** set/refresh session affinity from the server after a successful dispatch (as is already
  done for tool-call ids).

### 22. INFO — `security.allowed_backend_hosts` cannot reject anything
- **File:** `src/modelsaar/routing/router.py:41-47`, `adapters/base.py:72-75`
- Every configured backend host is added to the allow-list before the check, so the check is a
  tautology; the real protection is `_url()` + fixed paths + `follow_redirects=False` (which are
  correct). Either drop the option or make it an explicit allow-list that must contain each host.

### 23. INFO — Classifier calls bypass admission and the circuit breaker
- **File:** `src/modelsaar/routing/classifier.py:117-119`
- The classifier request is not reserved against the backend/pool limits, so a burst of ambiguous
  requests can exceed `max_concurrent` on the backend. Bounded by `timeout_s`, so low impact.

### 24. INFO — Missing numeric validation in config
- `ResourcePool.max_concurrent`/`BackendConfig.max_concurrent` accept 0 (every request then waits
  for `queue_timeout_s` and gets 503); `TokenEstimateConfig.chars_per_token` accepts 0
  (ZeroDivisionError on first request); `max_queue` accepts negatives. Add `Field(ge=1)`/`gt=0`.

### 25. INFO — Decision log can carry upstream/model text fragments
- `server.py:173` stores up to 300 chars of an upstream 5xx body in `dec.failover[].error`;
  `classifier.py:142` stores `str(e)[:80]` which for `float("<model output>")` echoes model output.
  Neither is prompt content, but both are backend/model-controlled text in a log documented as
  "metadata only". Consider whitelisting known error shapes.

### 26. INFO — Admin key is also accepted as an inference key
- `security.py:48`. Separation is one-way (inference key → 403 on `/admin`), which is fine, but
  docs/privacy.md's "separate admin key" could be read as two-way. Document it.

### 27. INFO — Client-disconnect accounting depends on uvicorn advertising ASGI spec 2.3
- uvicorn 0.54 advertises `spec_version 2.3`, so Starlette's task-group path cancels `_relay`
  (verified: decision `client_disconnected`, slot marked uncertain). With spec ≥2.4 Starlette
  instead awaits `stream_response` directly and uvicorn's `send` returns silently after
  disconnect; `_relay` would then relay the whole upstream stream to nobody and never mark the
  slot uncertain (no leak, but the admission model documented in architecture.md stops holding).
  Worth a comment/test pin.

### 28. INFO — Minor correctness nits (by inspection)
- `openai_compat.py:57` `discovered=name in names` is always `True` (declared-only models are
  reported as discovered).
- `ollama.py:127-131` `_enrich`: a non-object JSON from `/api/show` raises outside the `try`,
  failing discovery for the whole backend.
- `server.py:169` `upstream.status >= 500 or upstream.status in (502, 503, 504)` is redundant.
- `server.py:250-252` and `:320-322` call `remember_tool_calls` twice for single-id lists (harmless).
- `requirements.py:158-167`: an unrecognised `tool_choice` string leaves `tool_choice_mode="none"`,
  so the `tools` capability check is skipped (Ollama then returns 400 via `unsupported_semantics`;
  a generic backend would receive the invalid value). Validate `tool_choice` ∈ {auto,none,required,object}.

---

## Spec requirements verified as correctly implemented

1. **No silent degradation (within the limits noted above):** unknown top-level fields → 400
   (`protocol/openai.py:150-156`, test); `n>1` rejected; backend-unsupported fields
   (`logit_bias`, `logprobs`, `n`) exclude the Ollama path with a blocker; unknown/unsupported
   capabilities (`tools`, `tool_choice_required`, `parallel_tools`, `json_schema`, `json_object`,
   `streaming`, `vision`, `audio_in`, `continuation`) exclude the deployment with remedy
   (`eligibility.py:29-38`); images are forwarded intact (test); `tool_choice=required/named` on
   Ollama → 400 `unsupported_semantics`, not downgraded; embeddings contracts refuse incompatible
   fallback (test). Oversized Latin-script prompts are rejected (test + probe, 422).
2. **Failover/commitment:** retries only before any header is sent, only on `retryable`
   `AdapterError` (connect failures / 5xx with body discarded), at most `max_failover_attempts`,
   only to deployments already in `dec.candidates` (`server.py:222-226`); after the first byte the
   relay emits an error frame + `[DONE]` and never switches (`_relay`, tests
   `test_stream_failure_after_commit_*`). Non-stream `ReadTimeout` is correctly non-retryable.
3. **Explicit model selection:** goes through `filter_deployments` with the same checks.
   Confirmed by running: explicit `plain:3b`+tools → 422, explicit `cloud:latest` → 422 (local_only),
   explicit `small:1b` + 35k tokens → 422. Path-traversal/URL-like model names → 404, never a path.
4. **Affinity:** session keys only from `modelsaar.session`, configured headers, configured body
   fields; scoped as `sha256(caller‖key)` (`affinity.py:40-41`); API key hash is the *scope*, never
   a session id; cross-caller `prompt_cache_key` collisions don't mix (test). Tool round trips
   refuse handover when the pinned deployment is ineligible (test) — but see finding 3 for which
   deployment gets pinned.
5. **Security:** loopback default with LAN guard in config validation (`config.py:293-297`, test);
   generated keys, no default key, inference key → 403 on `/admin/*`; adapters build only relative
   paths (`_url` rejects `://` and `//`), `follow_redirects=False`, model names only ever appear in
   JSON bodies; lowercase `http(s)://` image URLs rejected and the gateway contains no media-fetch
   code; prompt text absent from decisions and `/admin/status` (test); `modelsaar` body field is
   stripped before forwarding; invalid `modelsaar.profile` falls back to the alias profile; prompt
   injection cannot alter routing (test). Status page escapes all server-provided strings.
6. **Admission:** reservation acquired immediately before dispatch, released on every
   `AdapterError`/non-200 path, marked uncertain on client disconnect and expired after
   `uncertain_hold_s`; queue bounds give 429/503 with `Retry-After`; circuit breaker opens after
   N failures and half-opens after cooldown. 40 concurrent streams with random early disconnects:
   `active=0, uncertain=0` after the hold, follow-up request 200 — no leak observed.
7. **SSE relay:** partial frames, mid-UTF-8 splits, CRLF frames, `[DONE]` pass-through, `model`
   rewrite per chunk, interleaved tool-call deltas (tests); error frame after commit (test).
8. **Classifier:** excerpt bounded by `max_input_chars` and whitespace-normalised; closed-set
   label + `0..1` confidence validation (NaN rejected); `asyncio.wait_for` timeout; every
   failure mode falls back to the deterministic label; calls the configured deployment directly
   (never an alias) and respects `local_only`; can only raise a task label's confidence.
9. **Token accounting:** per-message/tool/image overheads + 5 % margin; `reasoning_allowance`
   added only for deployments with `thinking == supported` (`eligibility.py:58-59`); no truncation
   anywhere in the request path.
10. **Config/keys:** strict (`extra=forbid`) models, version check, unique backend ids,
    pool references validated, alias names must start with `auto` (cannot shadow a deployment id);
    `os.replace`-based atomic writes; `doctor` warns on key-file modes.
11. **Python 3.10:** the full suite passes under CPython 3.10.20; `zip(strict=)` is 3.10+; all
    `X | None` unions are in annotations under `from __future__ import annotations` or in pydantic
    models (PEP 604 is valid at runtime on 3.10); no `match`, `asyncio.timeout`, `StrEnum`,
    `tomllib`, `ExceptionGroup` or `itertools.batched` usage.

## Suggested priority order for fixes
1 (unknown context), 2 (negative max_tokens), 3 (tool-round pin), 7 (URL scheme), 6 (declared
capabilities), 4 (truncated stream), 5 (CJK estimate), 9/10 (file modes, 500 on non-ASCII),
8 (uninstall), 11 (docs), then the LOW items.
