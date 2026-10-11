# Model catalogue: evidence and extension

The catalogue (`src/modelsaar/catalogue/starter.yaml`) is **evidence, not routing rules**. It
supplies priors (labelled `catalogue`), tags, roles and intended-use notes for discovered deployments
whose names match. It never marks a capability as locally verified. Verification happened on
**2026-10-11** against model cards, publisher posts and ollama.com library pages; the full per-seed
write-ups with URLs are in [research/catalogue-part1-2026-10-11.md](research/catalogue-part1-2026-10-11.md)
and [research/catalogue-part2-2026-10-11.md](research/catalogue-part2-2026-10-11.md).

Three layers are kept apart everywhere in ModelSaar:

1. **Model-card claims** (this catalogue, Ollama `/api/show` capabilities) → `source_claim` provenance.
2. **Local probes** (`modelsaar probe`) → `probe` provenance, keyed by deployment fingerprint.
3. **Measured task performance** (`modelsaar eval --mode live --save-measurements`) → `measured:<n>` evidence.

Benchmarks are never transferred across size, quantization, runtime, template or harness.

## Seed verification summary (30 user-supplied names)

| seed | resolved | availability (2026-10-11) | licence | role | local on Ollama? | catalogue status |
|---|---|---|---|---|---|---|
| glm-5.3 | zai-org/GLM-5.3 (753B MoE) | released weights | GLM-5.3 License (custom) | generative | cloud-only | evidence only (disabled) |
| kimi-k2.7-code | moonshotai/Kimi-K2.7-Code (1T/32B) | released weights | Modified MIT | code | cloud-only | evidence only |
| north-mini-code-1.0 | CohereLabs/North-Mini-Code-1.0 (30B/3B) | released weights | Apache-2.0 + AUP | code | yes | enabled |
| ornith / ornith-1.5 | deepreinforce-ai/Ornith-1.0-*, ornith-ai/Ornith-1.5-* | released weights | MIT (inherits Gemma/Qwen bases) | code/agent, vision | yes (9b/35b) | enabled |
| laguna-s-2.1 | poolside/Laguna-S-2.1 (118B/8B) | released weights | OpenMDW-1.1 | code | yes (≈96 GB q4) | enabled (memory follows total params) |
| laguna-xs-2.1 | poolside/Laguna-XS-2.1 (33B/3B) | released weights | OpenMDW-1.1 | code | yes | enabled (Metal empty-output bug noted) |
| deepseek-v4-pro | deepseek-ai/DeepSeek-V4-Pro | released weights | MIT | general | cloud-only | evidence only |
| kimi-k3 | moonshotai/Kimi-K3 (2.8T/104B) | released weights | Kimi K3 License | general | cloud-only | evidence only; **requires reasoning_content round-trip** |
| mistral-large-4 | none on HF | **announced weights** (blog 2026-10-06: "by end of month"); API preview | not named | general | cloud-only | disabled |
| qwen3.8 | Qwen/Qwen3.8-27B most likely (also 2.4T-A95B; Max is API-only) | released weights | Apache-2.0 (27B) | general/code/vision | yes (`qwen3.8:27b`) | enabled |
| qwen3.6 | Qwen/Qwen3.6-35B-A3B or -27B | released weights | Apache-2.0 | general/code/vision | yes | enabled |
| deepseek-v4.1-flash | deepseek-ai/DeepSeek-V4.1-Flash | released weights | MIT | general | cloud-only | evidence only |
| nemotron-3.5-lightning | nvidia/…-30B-A3B | released weights | OpenMDW-1.1 | general/agent | yes | enabled |
| muse-glimmer | meta-models/Muse-Glimmer-30B | released weights | Apache-2.0 | agent/vision | yes | enabled |
| lfm2.5 | LiquidAI/LFM2.5-8B-A1B (Ollama tag) and siblings | released weights | LFM Open License v1.0 (revenue cap) | general | yes | enabled (licence note) |
| clef / clef-flash | Cloudflare/clef, clef-flash | released weights | Apache-2.0 | **decision** (`/v1/systemone`) | yes | role=decision → never chat |
| nimble | bespokelabs/Bespoke-Nimble-9B (LoRA on Qwen3.5-9B) | released weights (adapter) | Apache-2.0 | decision | yes | role=decision; base dependency recorded |
| tev1 | togethercomputer/Tev1-4B-experimental | released weights | **licence being finalized** | decision | yes | disabled (unresolved licence) |
| laya | convaiinnovations/laya (ModernBERT/mmBERT) | released weights | Apache-2.0 | decision (encoder) | yes | role=decision |
| granite4.1 / granite4.2 | ibm-granite/granite-4.{1,2}-{3b,8b,30b} | released weights | Apache-2.0 | general (+thinking in 4.2) | yes | enabled |
| granite4.1-guardian | ibm-granite/granite-guardian-4.1-8b | released weights | Apache-2.0 | **guardrail** | yes | role=guardrail → never chat |
| glm-ocr | zai-org/GLM-OCR (0.9B VLM) | released weights | MIT | **ocr** | yes | role=ocr → never chat (pipeline not implemented) |
| medgemma / medgemma1.5 | google/medgemma-*, medgemma-1.5-4b-it | released weights, **gated** | Health AI Developer Foundations terms | medical (vision) | yes | enabled with intended-use restriction note |
| minicpm-v4.5 / v4.6 | openbmb/MiniCPM-V-4_5, -4.6 | released weights | Apache-2.0 | vision chat | yes | enabled |
| embeddinggemma-2 | google/embeddinggemma-2 | released weights (2026-10-06) | Apache-2.0 | **embedding** (multimodal; text-only exposed) | yes | role=embedding |

Cross-cutting findings: several models require `reasoning_content` to be passed back across tool
turns (Kimi K3 hard requirement; Laguna strongly recommended; Qwen3.6/3.8 `preserve_thinking` on by
default) — ModelSaar forwards assistant messages verbatim and flags `needs_continuation` when
`reasoning_content` is present; some cannot disable thinking (Kimi K3, K2.7 Code, Qwen3.8-2.4T);
Ollama tag tables often show context values that contradict the model card (EmbeddingGemma 2 = 8K,
Nimble = 8K, Laya = 512/1K, Clef = 64K) — card values are used for catalogue context, served context
comes from the runtime.

## Verified starter picks (local, Oct 2026)

Small fast chat: `gemma4:e4b` (Apache-2.0, 128K, tools/vision/audio, <10 GB); tiny text:
`granite4.2:3b`; strong general/reasoning for 24–32 GB: `qwen3.8:27b` (18 GB) or `granite4.2:30b`;
code: `qwen3-coder:30b` (MoE, 19 GB, non-thinking) or `devstral-small-2:24b`; vision:
`qwen3.5:9b`, `minicpm-v4.6:1b`; text embeddings: `qwen3-embedding:0.6b`, `embeddinggemma-2`.
Memory figures are Ollama download sizes; actual residency adds KV cache for the served context.

## Adding a deployment

1. Pull/serve the model in your runtime. For Ollama nothing else is needed: `modelsaar discover`
   shows it with the runtime's capability claims.
2. For a generic OpenAI-compatible server, declare it under `backends[].models` with
   `context_length`, `capabilities` and `tags` (operator provenance).
3. `modelsaar probe <backend>/<model>` to turn claims into probe evidence.
4. Optionally add a catalogue entry (see below) or an override under `deployments[]`.

## Adding a catalogue entry

Append to `starter.yaml` or ship an extra YAML passed to `load_catalogue(extra_paths=[...])`:

```yaml
- id: my-model
  publisher: Someone
  hf: someone/my-model
  match: { ollama: ["my-model:*"], names: ["my-model*"] }
  availability: released_weights        # announced_weights | api_only | unverified never enable defaults
  licence: Apache-2.0
  role: generative                      # embedding | decision | ocr | rerank | guardrail
  modalities_in: [text]
  context_length: 32768                 # model-card value
  tags: [code]
  quality_prior: { coding: 0.7 }        # hypothesis, labelled "catalogue" in decisions
  intended_use_note: ""
  sources: ["https://…"]                # required: URL(s) checked, with the file's `checked` date
```

Entries must separate weight licence from base-model/adapter/code licences and record dependencies
(e.g. a LoRA's base). Do not add an entry you have not verified from a primary source.

## Adding an adapter

Subclass `modelsaar.adapters.base.BaseAdapter` (implement `health`, `discover`, `chat`,
`embeddings`, optionally `loaded_models`, `tokenize`, `translate_chat_body`, `unsupported_fields`,
`adapter_capabilities`) and call `modelsaar.adapters.register_adapter("my_runtime", MyAdapter)`.
Backends with `type: my_runtime` then work without touching the router. Keep translations typed and
allow-listed; reject what the runtime cannot honour instead of dropping it.
