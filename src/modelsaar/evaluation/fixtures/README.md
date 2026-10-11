# Evaluation fixtures

`tasks.jsonl` is an **original, synthetic** task set written for ModelSaar (Apache-2.0, same as the
gateway). It contains no third-party dataset content. Each line:

| field | meaning |
|---|---|
| `id` | stable identifier |
| `category` | expected task label (`conversation`, `coding`, `agent`, `math`, `extraction`, `summarization`, `translation`, `rag`, `decision`, `document_vision`) |
| `split` | `calib` (used to calibrate the fixed-strong baseline and measurements) or `test` (final evaluation). Splits use different templates/phrasings so routing and judging never see the same examples. |
| `messages` / `tools` / `response_format` | the OpenAI-style request |
| `expected` | scorer: `nonempty`, `contains`, `contains_any`, `number` (+ `value`, optional `tol`), `json_schema` (+ `checks`), `tool_call` (+ `name`, optional `args_contains`), `code_exec` (+ `harness`, `stdout`) |

Deliberate coverage: short hard questions (`math-*`), long easy transformations (`long-01`),
follow-ups and tool round trips (`cont-01`), mixed-language (`multi-*`, `trans-03`), and ambiguous
prompts (`ambig-*`). Scoring is executable or exact/semantic-reference based; no LLM judge is used.

Scorer rules (see `scoring.py`, `SCORER_VERSION`):

- `number`: every standalone numeric token (ints, decimals, thousands commas) is extracted and the
  **last** one is compared with `value` within `tol` (default `1e-6`, relative for large values).
  `16` does not satisfy an answer of `6`; `25 - 7 = 18, so x = 6` does.
- `tool_call`: strict. The call must carry a non-empty `id`, the expected function `name`,
  arguments that parse to a JSON object containing every key in the tool's `parameters.required`,
  and, when `args_contains` is given, each listed argument must contain the given substring
  (`{"command": "pytest"}`). This says "the tool was invoked correctly", not "the agent task was
  completed".
- `code_exec`: the model's Python block, the `harness` and a completion sentinel are run in one
  program; success requires exit code 0, the sentinel as the last stdout line (so printing the
  expected text and then raising or exiting fails) and stdout equal to `stdout` after the same
  normalisation on both sides: trailing whitespace per line and trailing blank lines are ignored,
  leading whitespace and internal spacing are significant.

`code_exec` programs never run with host authority. `sandbox.py` uses, in order, bubblewrap
(Linux), `sandbox-exec` (macOS) or Docker (`python:3.12-slim`, `--network none --read-only`),
plus CPU/memory/output limits and a timeout. When none is available the task is **skipped** (not
failed, not passed): the report lists skipped counts, the reason, and computes success over the
scored tasks only. There is no unsandboxed fallback and no flag to enable one.
