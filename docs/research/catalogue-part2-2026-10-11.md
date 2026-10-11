# Model Catalogue Verification — Part 2

Date checked: 2026-10-11 (all URLs fetched on this date unless noted).
Method: WebSearch + WebFetch only (shell network blocked). Seed names were treated as non-authoritative discovery hints; each was resolved to a publisher checkpoint where a primary source (Hugging Face model card, publisher blog/docs, or the ollama.com library page) could be fetched.

Evidence-quality legend: **P** = primary (model card / publisher blog / ollama.com library page), **S** = secondary (news, aggregator). Figures that conflict between sources are called out rather than reconciled.

A cross-cutting finding first, because it affects five of the fifteen seeds:

> **"Decision models" are a new model class (Sept–Oct 2026) and are NOT chat models.** `clef`, `clef-flash`, `nimble`, `tev1` and `laya` are all "System 1" / Jev-API-compatible decision models. They take a `state` (text/JSON/sometimes images) plus up to 64 typed questions (`choice`, `noul` = yes/no probability, `score`) and return **per-option probabilities**, not generated text. In Ollama they are served from a separate endpoint, `POST /v1/systemone` (Ollama ≥ 0.35 / 0.35.1 / 0.40 depending on model), and the ollama.com pages state they "aren't yet supported in the Ollama CLI or the official Python and JavaScript libraries." A router must not send `/v1/chat/completions` traffic to them; they are classifiers/routers/guardrails.

---

## 1. `lfm2.5` — Liquid AI LFM2.5 family

- **Resolved checkpoint(s):** HF org `LiquidAI`; family members verified: `LFM2.5-350M` (+`-Base`), `LFM2.5-1.2B-Base`, `LFM2.5-1.2B-Instruct`, `LFM2.5-1.2B-Thinking`, `LFM2.5-1.2B-JP`, `LFM2.5-VL-1.6B`, `LFM2.5-Audio-1.5B`, `LFM2.5-2.6B` (+`-Base`), `LFM2.5-8B-A1B`. (A 230M size appears only in third-party GGUF repos — `unsloth/LFM2.5-230M-GGUF` — I did not fetch a LiquidAI 230M card, so treat 230M as unverified.) Ollama library name: `lfm2.5` — **but the Ollama entry is only the 8B-A1B MoE**, see below.
- **Availability:** released weights.
- **Publisher:** Liquid AI. **Release:** the 1.2B family + VL + Audio were released 5 Jan 2026 (Gigazine, S, dated 7 Jan 2026, citing Liquid blog "Introducing LFM2.5: the next generation of on-device AI"). 350M followed ~31 Mar 2026 (S). 2.6B and 8B-A1B dates not stated on their cards; the HF collection shows an "Aug 4" update.
- **Architecture:** LFM2 hybrid (double-gated short/LIV convolution blocks + GQA blocks).
  - 350M: dense, 32,768 ctx (P).
  - 1.2B Instruct: 1.17B dense, 16 layers (10 conv + 6 GQA), 32,768 ctx, vocab 65,536, 28T training tokens (P).
  - 2.6B: 2.69B dense, 30 layers (22 conv + 8 GQA), 131,072 ctx, vocab 128k; "pure reasoning model that always thinks before it answers" (P).
  - 8B-A1B: 8.3B total / 1.5B active, 24 layers (18 conv + 6 GQA), 128,000 ctx, tagged `lfm2_moe`, reasoning model with `<think>` (P). Ollama shows 125K ctx.
  - VL-1.6B: LFM2.5-1.2B backbone + SigLIP2 NaFlex 400M vision encoder, 32,768 ctx (unsloth docs, S).
- **Modalities:** text-only for Base/Instruct/Thinking/JP/350M/2.6B/8B-A1B; image+text for VL-1.6B; speech+text in/out for Audio-1.5B.
- **Role:** small on-device chat/instruct; 2.6B and 8B-A1B are reasoning (thinking) models; VL = vision; Audio = speech.
- **Tool calling (P):** Instruct, 350M, 2.6B and 8B-A1B cards all document tool calling. Tools go as a JSON list in the system prompt (or via `apply_chat_template(tools=...)`); default output is **Pythonic** calls between `<|tool_call_start|>`/`<|tool_call_end|>`, switchable to JSON by system prompt. ChatML-like template (`<|im_start|>`/`<|im_end|>`). Recommended: temp 0.1, top_k 50, rep. penalty 1.05.
- **Quantizations:** official GGUF repos: `LiquidAI/LFM2.5-350M-GGUF`, `LiquidAI/LFM2.5-1.2B-Instruct-GGUF`, `LiquidAI/LFM2.5-2.6B-GGUF`, `LiquidAI/LFM2.5-8B-A1B-GGUF`, `LiquidAI/LFM2.5-VL-1.6B-GGUF`; also ONNX, MLX, OpenVINO (350M), and "DSpark" speculative drafters (296M for 1.2B, 328M for 2.6B).
- **Runtimes:** Transformers, vLLM, SGLang, llama.cpp, Docker Model Runner (P). **Ollama:** `ollama.com/library/lfm2.5` exists (193.9K pulls, "updated 4 months ago") but its 5 tags are all `8b-a1b` (q4_K_M 5.2GB = `latest`/`8b`, q8_0 9.0GB, bf16 17GB), capabilities "tools, thinking", text only (P). Smaller LFM2.5 models must be pulled as `ollama run hf.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF` etc. (Liquid docs, P). Liquid docs warn Ollama 0.17.0 fails on `lfm2moe` ("missing tensor output_norm.weight"); needs ≥ 0.17.1-rc0.
- **Licence:** HF tag `lfm1.0` = **LFM Open License v1.0** (Liquid docs, P): free commercial use for companies with **< USD 10M annual revenue**; above that a commercial licence from Liquid AI is required (applies per company, including downstream customers, and to modified models); nonprofits/research exempt; must include licence, notices, NOTICE file, mark modified files. Not OSI-approved. (ScanCode key `lfm-open-1.0`.)
- **Sources (P):** https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct · https://huggingface.co/LiquidAI/LFM2.5-1.2B-Base · https://huggingface.co/LiquidAI/LFM2.5-350M · https://huggingface.co/LiquidAI/LFM2.5-2.6B · https://huggingface.co/LiquidAI/LFM2.5-8B-A1B · https://ollama.com/library/lfm2.5/tags · https://docs.liquid.ai/lfm/inference/ollama · https://docs.liquid.ai/lfm/help/model-license.md. (S): https://gigazine.net/gsc_news/en/20260107-lfm2-5-on-device-ai · https://unsloth.ai/docs/models/tutorials/lfm2.5
- **Caveats:** Ollama name `lfm2.5` ≠ the 1.2B model many users mean. Licence revenue cap matters for commercial deployers.

## 2. `clef` and 3. `clef-flash` — Cloudflare decision models

- **Resolved checkpoints:** `Cloudflare/clef` (27B) and `Cloudflare/clef-flash` (9B) on HF; Ollama `clef` and `clef-flash`.
- **Availability:** released weights (HF, Apache-2.0) + hosted on Cloudflare Workers AI (`@cf/cloudflare/clef`).
- **Publisher:** Cloudflare. **Release:** 1 Oct 2026 (Cloudflare blog, P).
- **Architecture:** frozen Qwen backbone + a "joint schema head" (small transformer head that reads final hidden states and scores all options of all questions jointly). Blog says training used rank-256 LoRA adapters + routing head, label-smoothed CE + Brier loss for calibration, RLCD as secondary objective; **prefill-only, non-autoregressive** inference.
  - Clef: Qwen3.8-27B backbone, 27B (HF shows 28B), with Qwen vision encoder.
  - Clef-flash: Qwen3.5-9B backbone, 9B, with vision encoder.
- **Modalities:** text, JSON, images, video frames in → **per-option logits/probabilities out** (no free text).
- **Role:** decision/classification/routing/guardrail ("decision model"); not chat.
- **Context:** blog says 64K for Clef; HF cards give no model ctx (encoder helper default `max_length` 16,384); Ollama tag table shows 256K but README says 64K — inconsistent, treat 64K as the publisher claim.
- **Input format:** `{model, state, questions:{name:{type: noul|choice|score, instructions, criteria}}}`; up to 64 questions; Jev/SystemOne API compatible. Ollama: `POST /v1/systemone`, requires Ollama ≥ 0.35.1; not supported in CLI or official client libs.
- **Runtimes:** Transformers (torch 2.11 / transformers 5.10.2, uses shipped `joint_schema_model.py`), SGLang (serves `/v1/systemone`), vLLM, Docker Model Runner; llama.cpp/LM Studio only via community quantizations; Ollama library has native entries (`clef` 18GB 27b; `clef-flash` ~11–12GB 9b), both "updated 5 days ago", tags "vision, decision".
- **Licence:** Apache-2.0 (HF + blog, P).
- **Benchmarks/limits (P, self-reported):** Clef trails Jev on some tasks (GPQA Diamond 48.0 vs 78.3; Clef-flash CLINC150+OOS 66.8 vs 97.4); no explicit limitations section.
- **Sources (P):** https://huggingface.co/Cloudflare/clef · https://huggingface.co/Cloudflare/clef-flash · https://blog.cloudflare.com/clef-decision-models/ · https://ollama.com/library/clef · https://ollama.com/library/clef-flash. (S): https://datanorth.ai/news/cloudflare-releases-clef-and-clef-flash

## 4. `nimble` — Bespoke Labs Bespoke-Nimble-9B

- **Resolved checkpoint:** `bespokelabs/Bespoke-Nimble-9B` (LoRA adapter; v2 at `Bespoke-Nimble-9B-v2`, earlier revision `original-2676`); Ollama `nimble` (merged, 9b, ~9.3–9.5GB).
- **Availability:** released weights (adapter on HF; merged GGUF on Ollama).
- **Publisher:** Bespoke Labs. **Release:** original date not stated; HF card update dated 24 Sep 2026 introduced the latest checkpoint; Ollama "updated 1 week ago".
- **Architecture:** **LoRA adapter on `Qwen/Qwen3.5-9B`** (dense 9B; rank-16 per DataCamp S, rank not stated on card). Scores allowed answer tokens directly — "does not generate reasoning or free-form answers".
- **Dependency:** the HF adapter requires downloading `Qwen/Qwen3.5-9B` base separately (PEFT). Ollama entry is self-contained.
- **Modalities:** text in → selected value + per-option probabilities out.
- **Role:** decision/classification (booleans, enums up to 255 choices, rubric score levels).
- **Context:** 8,192 tokens, over-length prompts are rejected not truncated (P). Ollama tag table shows 256K but README says 8,192 — follow the README.
- **Runtimes:** Transformers+PEFT, MLX (GitHub quickstart); Ollama `/v1/systemone` (≥ 0.35). vLLM not mentioned on card.
- **Licence:** Apache 2.0 (HF + Ollama, P).
- **Sources (P):** https://huggingface.co/bespokelabs/Bespoke-Nimble-9B · https://ollama.com/library/nimble. (S): https://www.datacamp.com/blog/top-open-source-jev-alternatives

## 5. `tev1` — Together AI Tev1

- **Resolved checkpoint:** `togethercomputer/Tev1-4B-experimental` (HF); Ollama `tev1` with tags `4b` (=latest, ~4.4GB) and `0.8b` (~800MB). The 0.8B exists on Ollama/OpenRouter (`togethercomputer/tev1-0.8b-experimental`) but I did not fetch a separate HF card for it.
- **Availability:** released weights — **but weight licence not finalized**: card says the licence "is being finalized before public conversion"; base Qwen3.5-4B is Apache-2.0. Ollama page says only that dataset builders/training scripts are MIT. Treat as "released weights, licence pending".
- **Publisher:** Together AI. **Release:** 30 Sep 2026 (OpenRouter, S); HF card has no date.
- **Architecture:** supervised fine-tune of Qwen3.5-4B (HF metadata 5B) that **keeps the standard next-token head** — "a Jev-inspired experiment, not a non-autoregressive Jev runtime". Output is exactly one option letter (max_tokens 8, temp 0, thinking off).
- **Modalities:** text (structured JSON state) in → single option letter out.
- **Role:** decision/classification/routing/policy checks; "generic chat is not the intended interface."
- **Context:** not stated on card; OpenRouter says 33K; Ollama notes "~2,000 tokens" working context vs 256K in the tag table — inconsistent.
- **Runtimes:** Transformers, vLLM, SGLang, Docker Model Runner, Together API; GGUF quantizations exist for llama.cpp/Ollama/LM Studio; Ollama `/v1/systemone` (≥ 0.35).
- **Limitations (P):** not for sole authority on high-impact decisions; prompt injection, multilingual, calibration and OOD robustness not comprehensively evaluated; 88% dev-set result not independent.
- **Sources (P):** https://huggingface.co/togethercomputer/Tev1-4B-experimental · https://ollama.com/library/tev1. (S): https://openrouter.ai/togethercomputer/tev1-4b-experimental

## 6. `laya` — ConvAI Innovations Laya

- **Resolved checkpoint:** `convaiinnovations/laya` (root, English, 421M); sibling checkpoints `laya-multilingual` (322M) and `laya-typed-decisions` (421M) per card; Ollama `laya` (tags: `latest` 846MB/512 ctx; `421m-english-mlx-fp16`, `322m-multilingual-mlx-fp16` 1K ctx, `421m-typed-decisions-mlx-fp16` 1K ctx).
- **Availability:** released weights.
- **Publisher:** ConvAI Innovations. **Release:** Sept 2026 (llmreference, S); Ollama "updated 1 week ago".
- **Architecture:** **non-autoregressive encoder** — ModernBERT-large (395M) backbone + decision head trained from scratch (English/typed); mmBERT-base for multilingual. Trained with "RLCD". Single forward pass → calibrated probabilities.
- **Modalities:** text in → typed answers + probabilities out. No generation.
- **Role:** decision/guardrail/triage classifier.
- **Context:** 512 tokens (English), 1,024 (multilingual/typed; multilingual can read to 8,192 with degraded accuracy past ~4k). Per-question 512-token budget in Ollama.
- **Runtimes:** `pip install laya` (ONNX Runtime, TileLang GPU, MCP, LangChain extras), Transformers `text-classification` pipeline; Ollama `/v1/systemone` (requires **Ollama ≥ 0.40.0**); MLX builds on Ollama.
- **Licence:** Apache-2.0 (HF + Ollama, P).
- **Limitations (P, unusually candid card):** near-chance zero-shot on typed-decisions (0.362 vs 0.461 majority baseline) — fine-tuning needed; poor on high-cardinality choices (Banking77 0.425); ordinal `score` weakest; ships over-confident (recommend temperature refit); root checkpoint English-only.
- **Sources (P):** https://huggingface.co/convaiinnovations/laya · https://ollama.com/library/laya. (S): https://www.llmreference.com/model-family/laya

## 7. `granite4.1` — IBM Granite 4.1

- **Resolved checkpoints:** `ibm-granite/granite-4.1-3b`, `-8b`, `-30b` (+ `-base` variants) — 6 repos in HF collection "granite-41-language-models"; Ollama `granite4.1` (3b 2.1GB, 8b 5.3GB, 30b 17GB; 48 tags incl. q8_0).
- **Availability:** released weights. **Release:** 29 Apr 2026 (HF card, P; Ollama README says 28 Apr).
- **Architecture:** decoder-only **dense** transformer (8B: 40 layers, 4096 hidden, 32 heads / 8 KV heads). HF metadata shows 9B for the "8B".
- **Context:** 131,072 (P). Ollama shows 128K; README mentions long-context extension to 512K.
- **Modalities:** text only. **Role:** general instruct / enterprise assistant / agents, code (FIM), RAG, structured JSON.
- **Tool calling (P):** yes, OpenAI function schema; BFCL v3 68.27 (8B), 60.80 (3B). **Thinking:** not mentioned (4.1 is non-reasoning; see 4.2).
- **Languages:** EN, DE, ES, FR, JA, PT, AR, CS, IT, KO, NL, ZH.
- **Runtimes:** Transformers, vLLM, SGLang, Docker Model Runner; GGUF via community quantizations for llama.cpp/Ollama/LM Studio; Ollama library entry native (tags "tools").
- **Licence:** Apache 2.0 (P).
- **Sources (P):** https://huggingface.co/ibm-granite/granite-4.1-8b · https://huggingface.co/ibm-granite/granite-4.1-3b · https://huggingface.co/collections/ibm-granite/granite-41-language-models · https://ollama.com/library/granite4.1

## 8. `granite4.2` — IBM Granite 4.2

- **Resolved checkpoints:** `ibm-granite/granite-4.2-3b`, `-8b`, `-30b`; collection "granite-42-language-models" has 24 repos incl. **official GGUF** (`granite-4.2-{3b,8b,30b}-GGUF`), fp8, nvfp4, mxfp4, MLX bf16/q8/q4. Ollama `granite4.2` (3b 2.2GB, 8b 5.3GB = latest, 30b 18GB; 49 tags).
- **Availability:** released weights. **Release:** 25 Aug 2026 (HF 8B card, P). Ollama "updated 1 month ago".
- **Architecture:** dense decoder-only (`GraniteForCausalLM`), GQA 32/8, RoPE, SwiGLU; post-trained from Granite-4.1-8B-Base. 3B/8B/30B.
- **Context:** 128K native, extendable to 512K (30B explicitly per IBM docs).
- **Modalities:** text only.
- **Role:** general + **reasoning** (what's new vs 4.1: native thinking), code, tool calling, agentic.
- **Thinking controls (P):** `enable_thinking=True` default (`<think>`), `False` for direct answer, `low_effort=True` for short reasoning; Ollama exposes `/set think` levels. Recommended temp 1.0, top_p 0.95.
- **Tool calling (P):** yes, OpenAI-style schema, reasoning before calls; vLLM `--tool-call-parser qwen3_coder` (vLLM ≥ 0.20 for Granite reasoning parser; SGLang ≥ 0.5.18).
- **Runtimes:** Transformers, vLLM, SGLang, Docker Model Runner, llama.cpp/Ollama/LM Studio (official GGUF), OpenCode/Pi/OpenHands harnesses named.
- **Licence:** Apache 2.0 (P).
- **Sources (P):** https://huggingface.co/ibm-granite/granite-4.2-8b · https://huggingface.co/collections/ibm-granite/granite-42-language-models · https://www.ibm.com/granite/docs/models/granite4-2 (docs site notes it is no longer updated) · https://ollama.com/library/granite4.2

## 9. `granite4.1-guardian` — IBM Granite Guardian 4.1 8B

- **Resolved checkpoint:** `ibm-granite/granite-guardian-4.1-8b`; Ollama `granite4.1-guardian` (single size tag `8b`, 6.9GB; 16 tags). No 3B Guardian 4.1 found on the card (older Guardian 3.2 was 5B; a 38M HAP classifier exists separately).
- **Availability:** released weights. **Release:** April 2026 (P).
- **Architecture:** fine-tune of `ibm-granite/granite-4.1-8b` (dense 8B).
- **Role:** **safety / judge classifier — not a general chat model.** Card: "use only in the prescribed yes/no scoring mode; other uses may produce unexpected or unsafe output."
- **Prompt format (P, confirmed):** a `<guardian>` block appended as the **final user message**, containing a mode instruction (`<think>` or `<no-think>`), `### Criteria:` (pre-baked risk such as jailbreak, groundedness, or BYOC natural-language criterion), and the fixed line `### Scoring Schema: If the last assistant's text meets the criteria, return 'yes'; otherwise, return 'no'.` Optional `available_tools` / `documents` passed via `apply_chat_template`.
- **Output format (P):** `<score>yes</score>` or `<score>no</score>`; in think mode preceded by `<think>...</think>`. No probability/confidence output documented.
- **Risk categories (P):** harm (social_bias, jailbreak, violence, profanity, sexual_content, unethical_behavior, general harm); RAG hallucination (context_relevance, groundedness, answer_relevance); agentic function-call hallucination; BYOC custom criteria.
- **Context:** not stated on card (examples use 8192); Ollama shows 128K.
- **Limitations:** English only; reasoning traces may be unsafe/unfaithful; test BYOC before production.
- **Runtimes:** Transformers, vLLM, SGLang, Docker Model Runner; Ollama native entry (`--think=false` to disable reasoning); community GGUF.
- **Licence:** Apache 2.0 (P).
- **Sources (P):** https://huggingface.co/ibm-granite/granite-guardian-4.1-8b · https://ollama.com/library/granite4.1-guardian

## 10. `glm-ocr` — Z.ai GLM-OCR

- **Resolved checkpoint:** `zai-org/GLM-OCR` (HF); Ollama `glm-ocr` (tags `latest`/`bf16` 2.2GB, `q8_0` 1.6GB; 8.2M pulls, "updated 8 months ago"). Transformers class `GlmOcrForConditionalGeneration` (contributed 2026-01-27).
- **Availability:** released weights. **Release:** late Jan / early Feb 2026 (Gigazine S dated 4 Feb 2026; Transformers integration 27 Jan 2026); tech report arXiv 2603.10910 (Mar 2026).
- **Architecture:** 0.9B **vision-language model** built on GLM-V encoder–decoder design: CogViT visual encoder (24 layers, 1024 hidden, patch 14, image 336, spatial merge 2) + lightweight cross-modal connector with token downsampling + GLM-0.5B decoder (16 layers, GQA 16/8, vocab 59,392, max positions 131,072). MTP loss in training.
- **Modalities:** image (+PDF via SDK) + text prompt in → text out.
- **Role:** OCR / document parsing (text, formula, table recognition; information extraction to JSON).
- **Exact input format (P):** chat message with an `image` entry and a `text` entry; task prefixes `"Text Recognition:"`, `"Formula Recognition:"`, `"Table Recognition:"`; information extraction uses a free-form instruction (example in Chinese: "请按下列JSON格式输出图中信息:" followed by a JSON schema) and must "strictly adhere to the defined JSON schema". Ollama README uses `Text Recognition:` / `Table Recognition:` / `Figure Recognition:` + image path.
- **Preprocessing:** the official pipeline is two-stage — layout analysis with **PP-DocLayout-V3** (Apache-2.0) then parallel recognition; the SDK (github.com/zai-org/GLM-OCR) is recommended for document parsing; for raw model use, images must be supplied per the chat template. No explicit resolution requirements stated.
- **Context:** not stated on card; Ollama shows 128K (config max positions 131,072).
- **Runtimes:** Transformers, vLLM (recipes.vllm.ai), SGLang, Ollama (named in the card's intro and native library entry). llama.cpp GGUF not mentioned on the HF card (Ollama ships bf16/q8_0 builds).
- **Tool calling:** none claimed (Ollama page shows a "vision tools" tag — treat with caution; not on the card).
- **Licence:** **MIT** (model weights, P); PP-DocLayoutV3 component Apache-2.0.
- **Sources (P):** https://huggingface.co/zai-org/GLM-OCR · https://huggingface.co/docs/transformers/main/en/model_doc/glm_ocr · https://ollama.com/library/glm-ocr. (S): https://gigazine.net/gsc_news/en/20260204-z-ai-glm-ocr

## 11. `medgemma` — Google MedGemma 1 (4B, 27B)

- **Resolved checkpoints:** `google/medgemma-4b-it`, `google/medgemma-4b-pt`, `google/medgemma-27b-text-it`, `google/medgemma-27b-it` (27B-it card fetched; the 4B/27B-text ids are inferred from the naming pattern on the card and the HF collection — mark as "likely, not individually fetched"). Ollama `medgemma` (4b 3.3GB = latest, 27b 17GB; q4_K_M/q8_0/bf16 tags, 128K ctx, "vision").
- **Availability:** released weights, **gated** (must accept Health AI Developer Foundations terms; "processed immediately").
- **Publisher:** Google (Health AI Developer Foundations). **Release:** 27B-it created 9 Jul 2025, v1.0.0; tech report 7 Jul 2025 (P).
- **Architecture:** Gemma 3 decoder-only; 4B (multimodal) and 27B (text-only and multimodal; HF metadata 29B).
- **Modalities:** text + image in (4B and 27B-it), text in (27B-text-it); text out.
- **Context:** ≥128K in, up to 8,192 out (P).
- **Role:** medical text/image comprehension — developer starting point.
- **Licence:** **Health AI Developer Foundations terms of use** (not Gemma ToU, not Apache). Separate prohibited-use policy.
- **Restrictions (P):** "requires appropriate validation, adaptation and/or making meaningful modification"; outputs "not intended to directly inform clinical diagnosis… or treatment decisions"; evaluated mainly single-image, not multi-turn; more prompt-sensitive than Gemma 3.
- **Runtimes:** Transformers ≥ 4.50, vLLM, SGLang, Docker Model Runner, Google Cloud Model Garden; quantized builds for llama.cpp/Ollama/LM Studio; Ollama native entry.
- **Sources (P):** https://huggingface.co/google/medgemma-27b-it · https://developers.google.com/health-ai-developer-foundations/medgemma · https://ollama.com/library/medgemma/tags

## 12. `medgemma1.5` — Google MedGemma 1.5 4B

- **Resolved checkpoint:** `google/medgemma-1.5-4b-it`; Ollama `medgemma1.5` (tags `latest`/`4b`, 3.3GB, 128K, "vision"; 210.6K pulls). No 27B 1.5 variant found.
- **Availability:** released weights, gated (HAI-DEF terms).
- **Release:** 13 Jan 2026 (P); 23 Jan 2026 update made greedy decoding the default; tech report arXiv 2604.05081 (6 Apr 2026).
- **Architecture:** Gemma 3 4B decoder-only. Images normalized to 896×896 → 256 tokens each.
- **Modalities:** text + image in; text out. New vs 1.0: 3D CT/MRI volume interpretation (volumes need preprocessing per notebooks), whole-slide histopathology patches, longitudinal CXR comparison, anatomical localization with bounding boxes, lab-report structured extraction, text EHR interpretation.
- **Context:** ≥128K in, 8,192 out.
- **Licence / restrictions:** Health AI Developer Foundations terms; same non-clinical, validate-before-use limitations as MedGemma 1.
- **Runtimes:** Transformers ≥ 4.50, vLLM, SGLang, Docker Model Runner; quantized builds for llama.cpp/Ollama/LM Studio/Jan; Ollama native entry.
- **Sources (P):** https://huggingface.co/google/medgemma-1.5-4b-it · https://ollama.com/library/medgemma1.5 · https://developers.google.com/health-ai-developer-foundations/medgemma

## 13. `minicpm-v4.5` — OpenBMB MiniCPM-V 4.5

- **Resolved checkpoint:** `openbmb/MiniCPM-V-4_5`; GGUF `openbmb/MiniCPM-V-4_5-gguf`; Ollama `minicpm-v4.5` (tags `latest`/`8b` 6.1GB, 40K ctx, "vision", 13 tags, 52K pulls).
- **Availability:** released weights. **Release:** Aug 2025 (llama.cpp support 26 Aug 2025 / b6282; vLLM v0.10.2 27 Aug 2025; paper arXiv 2509.18154).
- **Architecture:** Qwen3-8B LLM + SigLIP2-400M vision encoder; ~8.7B total (HF 9B).
- **Modalities:** text, single/multi-image, high-FPS video in; text out. 30+ languages.
- **Context:** not stated on card; Ollama 40K.
- **Role:** vision-language chat. **Tool calling:** none claimed.
- **Runtimes:** llama.cpp (GGUF), vLLM; SGLang and Ollama were listed as "merging / waiting for official release" on the HF card, but the ollama.com entry now exists natively.
- **Licence:** **Apache-2.0** for weights and code (P). Card asks users to optionally fill a registration questionnaire; no additional commercial conditions stated (earlier MiniCPM models used a separate "MiniCPM Model License" — not the case here).
- **Sources (P):** https://huggingface.co/openbmb/MiniCPM-V-4_5 · https://ollama.com/library/minicpm-v4.5

## 14. `minicpm-v4.6` — OpenBMB MiniCPM-V 4.6

- **Resolved checkpoint:** `openbmb/MiniCPM-V-4.6` (note dot, not underscore); Ollama `minicpm-v4.6` (tags `latest`/`1b` 1.6GB, 256K ctx, "vision", 13 tags, 63.8K pulls).
- **Availability:** released weights. **Release:** ~May 2026 (Artificial Analysis S dated 11 May 2026; card mentions an API-service announcement 2026-05-17).
- **Architecture:** **Qwen3.5-0.8B** LLM + SigLIP2-400M; ~1.3B (HF metadata ~1B). "Pocket-sized MLLM" for phones.
- **Modalities:** image (single/multi) + video + text in; text out.
- **Context:** not stated on card; Ollama 256K.
- **Tool calling (P):** example shown via `transformers serve` and vLLM `--enable-auto-tool-choice --tool-call-parser qwen3_coder`; no dedicated transformers parser yet (regex extraction).
- **Runtimes:** vLLM (`vllm serve openbmb/MiniCPM-V-4.6`), SGLang (Docker images), llama.cpp GGUF (`MiniCPM-V-4.6-Q4_K_M.gguf` example; no official GGUF repo id given), Ollama (`ollama run minicpm-v-4.6` on card; actual library name is `minicpm-v4.6`).
- **Licence:** Apache-2.0 (P).
- **Sources (P):** https://huggingface.co/OpenBMB/MiniCPM-V-4.6 · https://ollama.com/library/minicpm-v4.6. (S): https://artificialanalysis.ai/articles/openbmb-launches-minicpm-v-4-6-1-3b-instruct

## 15. `embeddinggemma-2` — Google EmbeddingGemma 2

- **Resolved checkpoint:** `google/embeddinggemma-2` (single checkpoint, modular loading); Ollama `embeddinggemma-2` (17 tags: `270m` 378MB text; `440m` 714MB text+image; `570m` 990MB text(+audio); `740m` 1.3GB = latest text+image; 24.6–25.7K pulls, "updated 4 days ago").
- **Availability:** released weights. **Release:** 6 Oct 2026 (Google Developers Blog, P).
- **Publisher:** Google DeepMind. Based on **Gemma 4** architecture.
- **Architecture/params:** 740M total = 130M backbone + 140M embedder (270M text core) + 170M vision encoder + 300M audio encoder; encoders can be disabled via `config_kwargs` (`vision_config`/`audio_config` = None). All configs share one vector space (270M text query can match 740M-embedded docs).
- **Multimodal: YES** — text (incl. code), images, video (1 fps default), audio (16 kHz mono) → one shared 768-d space. (Ollama tags expose text and image inputs; audio/video not shown in Ollama tag table.)
- **Dimensions:** native 768; **Matryoshka truncation 512 / 256 / 128** (`truncate_dim`). Quality: 256d keeps most text/code quality and ~95% for image/video/speech retrieval; 128d ~90% text/code but ~75% for multimodal — validate.
- **Normalization:** truncated vectors **must be re-L2-normalized** before cosine similarity ("ranking quality degrades silently"); use `normalize_embeddings=True`. Query and document must use same dimension. Use bf16/fp32 — fp16 can produce NaNs.
- **Prompt prefixes (text only, recommended):** query `task: search result | query: {query}`; document `title: {title} | text: {content}` (`title: none` if no title); also `task: question answering | query: …`, `task: classification | query: …`, `task: clustering | query: …`. Images/video/audio take no prefix. sentence-transformers prompt names `SearchQuery` / `Document`.
- **Context:** 8,192 tokens shared across modalities (P). Ollama tag table shows 256K — inconsistent; follow the model card (8K).
- **Languages:** 100+ (trained on 140+).
- **Role:** embedding/retrieval/classification/clustering — **NOT generative, not chat.** Card: pre-trained without safety tuning.
- **Runtimes:** sentence-transformers ≥ 6.1.0, Transformers, vLLM, SGLang, MLX, Ollama, LM Studio, LiteRT, Unsloth. 57 quantized variants in the HF model tree (formats not specified on card).
- **Licence:** **Apache 2.0** (HF tag + model card + blog; the linked "gemma_4_license" page points to Apache 2.0 text). This differs from EmbeddingGemma 1 / Gemma 3 which used the Gemma Terms of Use — verified on three primary pages, but worth re-checking the actual LICENSE file before relying on it.
- **Sources (P):** https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/ · https://huggingface.co/google/embeddinggemma-2 · https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2 · https://ollama.com/library/embeddinggemma-2

---

## Verified starter catalogue (local Ollama / llama.cpp, Oct 2026)

All entries verified today from the HF model card and/or ollama.com library page. Licence is for the weights. Fit estimate uses the Ollama default (q4_K_M) size.

| # | Slot | Model | Ollama | HF repo | Licence | Context | Capabilities | Fit | Sources (2026-10-11) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Small fast general chat (+vision/audio) | Gemma 4 E4B-it | `gemma4:e4b` (=latest; 6.6–9.5GB) | `google/gemma-4-E4B-it` (4.5B effective / 8B w/ embeddings) | Apache 2.0 | 128K | tools (native structured tool use), thinking (`<\|think\|>` / `enable_thinking`), vision, audio; 35+ languages | <10 GB | https://huggingface.co/google/gemma-4-E4B-it · https://ollama.com/library/gemma4 |
| 2 | Small fast general chat (text-only, tiny) | Granite 4.2 3B | `granite4.2:3b` (2.2GB) | `ibm-granite/granite-4.2-3b` (+ official `-GGUF`) | Apache 2.0 | 128K | tools, thinking (on by default, `low_effort`), JSON output, FIM code; 12 languages | <4 GB | https://huggingface.co/collections/ibm-granite/granite-42-language-models · https://ollama.com/library/granite4.2 |
| 3 | Strong general/reasoning, 16–32 GB | Qwen3.8-27B | `qwen3.8:27b` (=latest; 18GB) | `Qwen/Qwen3.8-27B` (dense 27B, Gated DeltaNet + Gated Attention) | Apache 2.0 | 262,144 native (1M YaRN) | thinking on by default (`reasoning_effort` xhigh/medium/low, `preserve_thinking`), tools (Ollama tag), vision (image+video) | ~18 GB → fits 24–32 GB | https://huggingface.co/Qwen/Qwen3.8-27B · https://ollama.com/library/qwen3.8 |
| 4 | Strong general/reasoning, 16–32 GB (enterprise, text) | Granite 4.2 8B / 30B | `granite4.2:8b` (5.3GB) / `granite4.2:30b` (18GB) | `ibm-granite/granite-4.2-8b`, `-30b` (dense; official GGUF) | Apache 2.0 | 128K native, 512K extended | tools (OpenAI schema, reasoning-before-call), thinking modes, structured JSON | 8B <8 GB; 30B ~18 GB | https://huggingface.co/ibm-granite/granite-4.2-8b · https://ollama.com/library/granite4.2 |
| 5 | Code-focused | Qwen3-Coder-30B-A3B-Instruct | `qwen3-coder:30b` (19GB) | `Qwen/Qwen3-Coder-30B-A3B-Instruct` (MoE 30.5B total / 3.3B active) | Apache 2.0 | 262,144 native (1M YaRN) | tools (special function-call format, OpenAI `tools` param); **non-thinking only**; text-only | ~19 GB | https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct · https://ollama.com/library/qwen3-coder |
| 6 | Code-focused (agentic, with vision) | Devstral Small 2 (24B) | `devstral-small-2:24b` (15GB) | Mistral AI (Ollama page verified; HF card not fetched today — mark HF id unverified) | Apache 2.0 (Ollama page) | 384K (Ollama) | tools, vision; SWE-Bench Verified 65.8% (self-reported) | ~15 GB | https://ollama.com/library/devstral-small-2 |
| 7 | Vision-language (mid) | Qwen3.5-9B | `qwen3.5:9b` (=latest; 6.6–7.6GB) | `Qwen/Qwen3.5-9B` | Apache 2.0 | 262,144 native (~1M YaRN) | vision (image+video), tools (`qwen3_coder` parser), thinking on by default (`enable_thinking: False` to disable; no `/think` soft switch) | <8 GB | https://huggingface.co/Qwen/Qwen3.5-9B · https://ollama.com/library/qwen3.5 |
| 8 | Vision-language (tiny/edge) | MiniCPM-V 4.6 | `minicpm-v4.6:1b` (1.6GB) | `openbmb/MiniCPM-V-4.6` (Qwen3.5-0.8B + SigLIP2-400M) | Apache 2.0 | n/s on card; 256K Ollama | vision (image, multi-image, video); tool calling via qwen3_coder parser (vLLM) | <2 GB | https://huggingface.co/OpenBMB/MiniCPM-V-4.6 · https://ollama.com/library/minicpm-v4.6 |
| 9 | Text embedding (text-only, multilingual, MRL) | Qwen3-Embedding-0.6B | `qwen3-embedding:0.6b` (639MB) | `Qwen/Qwen3-Embedding-0.6B` | Apache 2.0 | 32K | embedding only; dims 32–1024 (MRL); query prefix `Instruct: {task}\nQuery:{query}`; 100+ languages | <1 GB | https://huggingface.co/Qwen/Qwen3-Embedding-0.6B · https://ollama.com/library/qwen3-embedding |
| 10 | Multimodal embedding | EmbeddingGemma 2 | `embeddinggemma-2` (270m–740m; 378MB–1.3GB) | `google/embeddinggemma-2` | Apache 2.0 | 8,192 | embedding only; text+image+video+audio; 768d with MRL 512/256/128; must L2-normalize truncations; prefixes above | <1.5 GB | see §15 |

Notes for the catalogue:
- Not included because not verified today: Llama 4 / Meta "muse-glimmer" (Ollama landing page lists it as Meta's Apache-2.0 30B local agent model but I did not fetch its card), GLM local models (Ollama's `glm-5.3`/`glm-5.3-flash` are **cloud-only** entries; no local GLM chat model verified), DeepSeek (`deepseek-v4.1-flash` is cloud-only on Ollama), `nomic-embed-text` (Ollama entry is v1.5, 2K ctx, "updated 2 years ago"; licence/dims not on the page).
- Ollama tag tables frequently show a 256K "context window" that contradicts the model card (EmbeddingGemma 2 = 8K, Nimble = 8K, Laya = 512/1K, Clef = 64K). A router should take context limits from the model card, not the Ollama tag table.
- Guardian / decision / OCR / embedding entries are **non-chat** and must be routed by role, not by `/v1/chat/completions` capability probing.

---

## Summary table

| Seed | Resolved checkpoint | Availability | Licence | Role | Modalities | Context | Ollama / GGUF | Evidence |
|---|---|---|---|---|---|---|---|---|
| `lfm2.5` | `LiquidAI/LFM2.5-*` (350M, 1.2B Base/Instruct/Thinking/JP, 2.6B, 8B-A1B, VL-1.6B, Audio-1.5B) | released weights | LFM Open License v1.0 (`lfm1.0`; free < $10M revenue) | chat/instruct; 2.6B & 8B-A1B reasoning; VL vision; Audio speech | text (VL: +image; Audio: speech↔text) | 32K (350M/1.2B/VL); 128K (2.6B, 8B-A1B) | Ollama `lfm2.5` = 8B-A1B only; official GGUF for all sizes (`hf.co/LiquidAI/...-GGUF`) | P (HF cards, Liquid docs, ollama.com) |
| `clef` | `Cloudflare/clef` (27B, Qwen3.8-27B backbone) | released weights + Workers AI | Apache-2.0 | decision model (classification/routing/guardrail) — not chat | text/JSON/image/video → probabilities | 64K (blog) | Ollama `clef` 18GB (`/v1/systemone`, ≥0.35.1); community GGUF | P (HF, Cloudflare blog, ollama.com) |
| `clef-flash` | `Cloudflare/clef-flash` (9B, Qwen3.5-9B backbone) | released weights + Workers AI | Apache-2.0 | decision model — not chat | text/JSON/image/video → probabilities | 64K (Ollama highlights) | Ollama `clef-flash` ~11GB; community GGUF | P |
| `nimble` | `bespokelabs/Bespoke-Nimble-9B` (LoRA on Qwen3.5-9B; v2 sibling) | released weights (adapter; needs Qwen3.5-9B base) | Apache 2.0 | decision/classification — not chat | text → selected value + probabilities | 8,192 (hard limit) | Ollama `nimble:9b` ~9.5GB (`/v1/systemone`) | P (HF, ollama.com); S DataCamp |
| `tev1` | `togethercomputer/Tev1-4B-experimental` (SFT of Qwen3.5-4B; 0.8B on Ollama) | released weights; **weight licence "being finalized"** | pending (base Qwen3.5 Apache-2.0; scripts MIT) | decision/classification — "not for generic chat" | text (JSON state) → one option letter | n/s (33K per OpenRouter; ~2K practical per Ollama) | Ollama `tev1:4b`/`0.8b`; GGUF quants exist | P (HF, ollama.com); S OpenRouter |
| `laya` | `convaiinnovations/laya` (ModernBERT-large 421M; multilingual mmBERT 322M; typed-decisions) | released weights | Apache-2.0 | non-autoregressive decision classifier/guardrail — not generative | text → typed answers + probabilities | 512 (EN) / 1,024 (multilingual, typed) | Ollama `laya` 846MB + MLX tags (≥0.40.0, `/v1/systemone`); no GGUF (encoder) | P (HF, ollama.com); S llmreference |
| `granite4.1` | `ibm-granite/granite-4.1-{3b,8b,30b}` (+base) | released weights (29 Apr 2026) | Apache 2.0 | general instruct, agents, code, RAG | text | 131,072 | Ollama `granite4.1` 3b/8b/30b; community GGUF | P |
| `granite4.2` | `ibm-granite/granite-4.2-{3b,8b,30b}` (+fp8/nvfp4/mxfp4/MLX/official GGUF) | released weights (25 Aug 2026) | Apache 2.0 | general + reasoning (thinking), tools, code | text | 128K native / 512K ext. | Ollama `granite4.2` 3b/8b/30b; official GGUF | P |
| `granite4.1-guardian` | `ibm-granite/granite-guardian-4.1-8b` | released weights (Apr 2026) | Apache 2.0 | safety/judge classifier — yes/no `<score>` format, not chat | text | n/s on card (128K Ollama) | Ollama `granite4.1-guardian:8b` 6.9GB; community GGUF | P |
| `glm-ocr` | `zai-org/GLM-OCR` (0.9B VLM: CogViT + GLM-0.5B) | released weights (Jan/Feb 2026) | MIT (PP-DocLayoutV3 dep. Apache-2.0) | OCR / document parsing (VLM with task-prefix prompts) | image(+PDF via SDK)+text → text | n/s (128K Ollama; 131,072 max positions) | Ollama `glm-ocr` bf16/q8_0; GGUF not on HF card | P (HF, Transformers docs, ollama.com); S Gigazine |
| `medgemma` | `google/medgemma-{4b-it,4b-pt,27b-text-it,27b-it}` (27b-it card fetched; others inferred) | released weights, **gated** (Jul 2025) | Health AI Developer Foundations terms | medical text/image — developer model, not clinical | text+image (27b-text: text) → text | ≥128K in / 8,192 out | Ollama `medgemma` 4b/27b; community quants | P |
| `medgemma1.5` | `google/medgemma-1.5-4b-it` | released weights, **gated** (13 Jan 2026) | Health AI Developer Foundations terms | medical text/image incl. 3D CT/MRI, WSI, EHR — not clinical | text+image → text | ≥128K in / 8,192 out | Ollama `medgemma1.5:4b` 3.3GB; community quants | P |
| `minicpm-v4.5` | `openbmb/MiniCPM-V-4_5` (Qwen3-8B + SigLIP2-400M) | released weights (Aug 2025) | Apache-2.0 | vision-language chat | image/multi-image/video+text → text | n/s (40K Ollama) | Ollama `minicpm-v4.5:8b` 6.1GB; official `openbmb/MiniCPM-V-4_5-gguf` | P |
| `minicpm-v4.6` | `openbmb/MiniCPM-V-4.6` (Qwen3.5-0.8B + SigLIP2-400M, ~1.3B) | released weights (~May 2026) | Apache-2.0 | edge vision-language chat (+tool calling via qwen3_coder parser) | image/multi-image/video+text → text | n/s (256K Ollama) | Ollama `minicpm-v4.6:1b` 1.6GB; GGUF (community; no official repo id on card) | P; S Artificial Analysis |
| `embeddinggemma-2` | `google/embeddinggemma-2` (270M/440M/570M/740M modular) | released weights (6 Oct 2026) | Apache 2.0 (per HF, model card, blog) | multimodal embedding/retrieval — not chat | text/code, image, video, audio → 768d (MRL 512/256/128) | 8,192 | Ollama `embeddinggemma-2` (270m–740m); 57 quantized variants on HF | P |

No seed was left "unverified": every name resolved to a fetchable primary source. Residual uncertainties: 230M LFM2.5 size (only third-party GGUFs seen), Tev1 weight licence (pending per card), MedGemma 1.0 4B/27B-text repo ids (inferred from naming), Devstral Small 2 HF id (not fetched), and the Ollama-vs-model-card context-length conflicts noted above.
