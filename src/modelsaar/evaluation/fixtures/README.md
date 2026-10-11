# Evaluation fixtures

`tasks.jsonl` is an **original, synthetic** task set written for ModelSaar (Apache-2.0, same as the
gateway). It contains no third-party dataset content. Each line:

| field | meaning |
|---|---|
| `id` | stable identifier |
| `category` | expected task label (`conversation`, `coding`, `agent`, `math`, `extraction`, `summarization`, `translation`, `rag`, `decision`, `document_vision`) |
| `split` | `calib` (used to calibrate the fixed-strong baseline and measurements) or `test` (final evaluation). Splits use different templates/phrasings so routing and judging never see the same examples. |
| `messages` / `tools` / `response_format` | the OpenAI-style request |
| `expected` | scorer: `nonempty`, `contains`, `contains_any`, `json_schema` (+ `checks`), `tool_call` (+ `name`), `code_exec` (+ `harness`, `stdout`) |

Deliberate coverage: short hard questions (`math-*`), long easy transformations (`long-01`),
follow-ups and tool round trips (`cont-01`), mixed-language (`multi-*`, `trans-03`), and ambiguous
prompts (`ambig-*`). Scoring is executable or exact/semantic-reference based; no LLM judge is used.

`code_exec` tasks run the model's Python in a disposable subprocess (`python -I`, temp dir, 10 s
timeout, address-space limit). This is a *basic* sandbox: it is not a security boundary against
hostile code and must only be used with models you trust on your own machine.
