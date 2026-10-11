# Model Catalogue Verification — Part 1

Date checked: 2026-10-11. Method: WebSearch + WebFetch only (shell network blocked). Every seed name was treated as a non-authoritative discovery hint. "Primary" = publisher model card / publisher blog / licence file / Ollama library page; "Secondary" = news or aggregator. Caveat on method: WebFetch returns a model-generated extraction of each page, not the raw HTML; figures below are what those extractions reported, and where the extraction flagged an internal inconsistency on the page (e.g. Ollama readme vs sidebar) I note it.

Availability classes used: **released weights** (downloadable today), **announced weights** (promised, not yet downloadable), **API-only**, **unverified**.

---

## 1. `glm-5.3` → `zai-org/GLM-5.3` (plus sibling `zai-org/GLM-5.3-Flash`)

- **Availability:** released weights (verified: HF repo live with BF16/FP8 safetensors; Ollama entry exists but is cloud-only).
- **Publisher / family:** Z.ai (Zhipu), GLM-5 series. GLM-5.3 "uses the same base model as GLM-5.2"; gains are post-training.
- **Release date:** API/subscription access 2026-08-14; open weights published 2026-08-28/29 (secondary: Gigazine, aiunderstanding.org). Model card itself gives no date; collection "Updated Aug 27".
- **Architecture:** MoE (`glm_moe_dsa` architecture tag). HF metadata: 753B params. Active params not stated on the card; secondary (Gigazine) reports "744B total / 40B active" — treat active count as unverified from primary.
- **Variants:** GLM-5.3 (753B); GLM-5.3-Flash (320B total / 18B active per card intro; HF shows 321B), the "first natively multimodal model in the GLM-5 series", open-weighted 2026-08-26 (secondary).
- **Quantizations:** Official weights BF16 + FP8 (F8_E4M3). No official GGUF. Community: 72 quantized repos linked (GLM-5.3), 169 (Flash); Unsloth `unsloth/GLM-5.3-GGUF` reported (secondary, Gigazine).
- **Modalities:** GLM-5.3: text-only (text-generation tag, EN/ZH). GLM-5.3-Flash: image+text → text.
- **Role:** flagship coding / long-horizon agentic reasoning model.
- **Context:** Not stated as a single figure on card; eval notes cite 400K, 1M and 300K settings. Ollama page lists 1M.
- **Runtimes:** Official: SGLang, vLLM, TokenSpeed, Transformers, KTransformers, Unsloth; Ascend via vLLM-Ascend/xLLM/SGLang. llama.cpp/Ollama/LM Studio only via community quantizations. **Ollama library:** `glm-5.3` exists but only tag is `glm-5.3:cloud` (no local pull).
- **Tool calling / structured output (card):** No explicit API claim; agentic benchmarks (Toolathlon, AutomationBench, DeepSWE) reported. Controls: `reasoning_effort` ∈ {low, high, max} (default max); `clear_thinking` (default false; card says pass true for chat). No structured-output claim. Ollama page tags: tools, thinking.
- **Licence:** Custom **"GLM-5.3 License"** (weights + code + docs together). MIT-style grant with copyright/permission-notice retention. Only commercial condition: a "Model as a Service" business with affiliate revenue > **US$10 billion** over any 12 months must pass Z.AI security review before commercial use. No gating. GLM-5.3-Flash is tagged **MIT**.
- **Dependencies:** none (full checkpoint).
- **Sources (primary):** https://huggingface.co/zai-org/GLM-5.3 ; https://huggingface.co/zai-org/GLM-5.3/blob/main/LICENSE ; https://huggingface.co/zai-org/GLM-5.3-Flash ; https://ollama.com/library/glm-5.3. **Secondary:** https://gigazine.net/gsc_news/en/20260829-glm-5-3-open/ ; https://datanorth.ai/news/z-ai-releases-glm-5-3.
- **Evidence quality:** High (model card + licence file read).

---

## 2. `kimi-k2.7-code` → `moonshotai/Kimi-K2.7-Code`

- **Availability:** released weights (HF repo live; Ollama entry cloud-only).
- **Publisher / family:** Moonshot AI, Kimi K2 line; "coding-focused agentic model built upon Kimi K2.6".
- **Release date:** 2026-06-12 (secondary: devops.com). Card gives no date.
- **Architecture:** MoE, 1T total / 32B active; 61 layers (1 dense), 384 experts, 8 routed + 1 shared; MLA attention, 64 heads, hidden 7168; ~160K vocab. Vision encoder MoonViT (400M).
- **Variants:** single checkpoint. Native INT4 quantization (same method as Kimi-K2-Thinking). Hub lists 28 quantized derivatives (llama.cpp/Ollama/LM Studio links); card does not say whether those are GGUF or official.
- **Modalities:** image+text (and video, "experimental, only supported in our official API for now") → text.
- **Role:** code / agentic SWE; "works best with Kimi Code CLI".
- **Context:** 256K (evals at 262,144).
- **Runtimes:** vLLM, SGLang, KTransformers recommended; Transformers >=4.57.1,<5.0; Docker Model Runner. **Ollama:** `kimi-k2.7-code` exists, only `:cloud` tag (1.04T, 256K; vision/tools/thinking).
- **Tool calling / state requirements (card):** interleaved thinking + multi-step tool calling "matches K2 Thinking" design. **Thinking mode forced on; `preserve_thinking` forced on and cannot be disabled; instant mode not supported for third-party deployments.** Multi-turn examples pass prior `reasoning_content` back; card notes some servers (vLLM) may use the field name `reasoning` instead. No structured-output claim. Recommended temp 1.0 / top_p 0.95.
- **Licence:** **"Modified MIT License"** for code and weights (text linked, not reproduced on card; not fetched here — by analogy with other Kimi licences it likely carries MAU/revenue attribution clauses, but that is NOT verified for this file).
- **Dependencies:** none.
- **Sources (primary):** https://huggingface.co/moonshotai/Kimi-K2.7-Code ; https://ollama.com/library/kimi-k2.7-code ; https://recipes.vllm.ai/moonshotai/Kimi-K2.7-Code. **Secondary:** https://www.devops.com/moonshot-ais-kimi-k2-7-code-targets-token-efficiency-in-agentic-coding/.
- **Evidence quality:** High for weights/arch; Medium for licence terms (file not read).

---

## 3. `north-mini-code-1.0` → `CohereLabs/North-Mini-Code-1.0` (HF id shown as `coherelabs/north-mini-code-1.0`)

- **Availability:** released weights (HF repo live, BF16; Ollama local tags exist).
- **Publisher / family:** Cohere / Cohere Labs, "North" family. Cohere API model id `north-mini-code-1-0`.
- **Release date:** card links an article dated "Jun 9" and collection updated "Jun 18" (year not shown; context implies 2026). Not confirmed from a dated primary source.
- **Architecture:** decoder-only sparse MoE, 30B total / 3B active; 128 experts, 8 active/token, sigmoid router; sliding-window+RoPE interleaved 3:1 with global no-PE attention; one dense layer before sparse layers; SwiGLU.
- **Variants:** single checkpoint (BF16). Hub: 38 quantized derivatives (llama.cpp, LM Studio, Jan, Ollama); 4 finetunes.
- **Modalities:** text → text.
- **Role:** code / agentic software engineering / terminal tasks.
- **Context:** 256K input, 64K max output (card and Cohere docs). Ollama tag listing shows "488K" — inconsistent with the readme's 256K; treat 256K as authoritative.
- **Runtimes:** Transformers (install from source), vLLM (main + `cohere_melody>=0.9.0`), SGLang, Docker Model Runner. **Ollama:** `north-mini-code-1.0` exists with local tags latest/q4_K_M 19GB, q8_0 32GB, bf16 61GB, plus MLX mxfp8/nvfp4/bf16. (`ollama.com/library/north-mini-code` without `-1.0` failed to fetch.)
- **Tool calling / structured output:** card: trained for tool use; JSON-schema tools via Transformers chat template; interleaved thinking "works best when turned on"; recommends passing thinking content and tool calls back in later turns. Cohere docs list Tool Use, Structured Outputs, Reasoning as capabilities (API). Ollama: tools + thinking.
- **Licence:** **Apache-2.0** (HF tag + Cohere docs). Ollama page adds "subject to Cohere Labs' Acceptable Use Policy". No gating observed.
- **Dependencies:** none named.
- **Sources (primary):** https://huggingface.co/coherelabs/north-mini-code-1.0 ; https://docs.cohere.com/docs/north-mini-code-1.0 ; https://ollama.com/library/north-mini-code-1.0. **Secondary:** https://aiweekly.co/alerts/cohere-releases-north-mini-code-beats-120b-models.
- **Evidence quality:** High.

---

## 4. `ornith` → Ornith-1.0 family, `deepreinforce-ai/Ornith-1.0-{9B,31B,35B,397B}`

- **Availability:** released weights.
- **Publisher / family:** DeepReinforce (HF org `deepreinforce-ai`); "self-improving" RL-trained agentic coding family. The 1.5 generation moved to a new org `ornith-ai` / ornith.ai (see §5); DataNorth describes Ornith as "the model line from DeepReinforce".
- **Release date:** June 2026 (secondary: DataNorth). Card: "Today, we are releasing Ornith-1.0", no date.
- **Architecture / sizes (card):** 9B-Dense, 31B-Dense, 35B-MoE, 397B-MoE. 397B tagged `qwen3_5_moe`, BF16; active count not stated (secondary sources say 35B is ~3B active).
- **Base-model dependency:** "post-trained on top of Gemma 4 and Qwen 3.5" (continued pretraining + mid-training + post-training). Card does not say which base each size uses; `qwen3_5_moe` tag on 397B implies Qwen3.5 MoE architecture. Licence implications of the upstream bases (Gemma Terms for any Gemma-4-derived size) are NOT addressed on the card — flag for review.
- **Modalities:** text + image → text (image-text-to-text tags, image example).
- **Role:** agentic coding / reasoning (`<think>` by default), terminal agents.
- **Context:** 262,144 (serve commands); some evals 128K/400K.
- **Runtimes:** Transformers >=5.8.1, vLLM >=0.19.1, SGLang >=0.5.9, Docker Model Runner. No official GGUF in the 397B repo; ~20 community quants. **Ollama:** `ornith` exists: `latest`/`9b` 5.6GB, `35b` 21GB (page says 9 models; 397b tag not visible), 256K, tools+thinking, MIT.
- **Tool calling:** yes — OpenAI-style `tool_calls` via Qwen3 XML / qwen3_coder parsers.
- **Licence:** **MIT** (HF tag + Ollama).
- **Sources (primary):** https://huggingface.co/deepreinforce-ai/Ornith-1.0-397B ; https://huggingface.co/deepreinforce-ai/Ornith-1.0-9B (fetch failed; existence confirmed via search) ; https://ollama.com/library/ornith. **Secondary:** https://datanorth.ai/news/ornith-releases-ornith-1-5 ; https://aiweekly.co/alerts/deepreinforce-ornith-10-learns-to-write-its-own-rl-scaffolds.
- **Evidence quality:** Medium-High (397B card read; per-size base models unverified).

---

## 5. `ornith-1.5` → `ornith-ai/Ornith-1.5-{397B,35B,9B}`

- **Availability:** released weights (HF repos live; Ollama local tags for all three sizes).
- **Publisher / family:** "Ornith Team" / Ornith AI (HF org `ornith-ai`, site ornith.ai); successor to DeepReinforce's Ornith-1.0. The org rename is inferred from the two orgs + DataNorth wording; the 1.5 card itself does not mention deepreinforce-ai.
- **Release date:** 2026-08-19 (secondary: DataNorth, Gigazine 2026-08-20). Card: 2026, collection updated ~18–21 days before check.
- **Architecture / sizes:** 397B MoE (HF metadata 403B, ~800GB BF16; active count not stated on card); 35B MoE (Ollama readme "35B-A3B"; HF repo `ornith-ai/Ornith-1.5-35B`); 9B dense (HF shows 10B params, ~19GB BF16); plus "Ornith-1.5-9B-Mobile" quantized edge build mentioned. Collection has 13 items (BF16/FP8/NVFP4/GGUF/MLX per secondary).
- **Base-model dependency:** card says 1.5 "extends Ornith-1.0", which was built on Qwen3.5 + Gemma 4; 9B tagged `qwen3_5`; chat template Qwen-based. Specific base per size still not stated.
- **Modalities:** text + image → text.
- **Role:** reasoning / agentic coding (Terminal-Bench 2.1 86.1, DeepSWE 56.0 self-reported for 397B).
- **Context:** 262,144 native; YaRN ×4 to ~1M (card warns of quality loss on short inputs).
- **Runtimes:** Transformers >=5.8.1, vLLM >=0.19.1, SGLang >=0.5.9, Docker Model Runner, llama.cpp (GGUF), Ollama, LM Studio, Unsloth Studio. GGUF: card references `ornith-ai/Ornith-1.5-397B-GGUF`; 9B card wording ("publish one at …`Ornith-1.5-9B-GGUF`") suggests the official 9B GGUF repo may not exist yet — `unsloth/Ornith-1.5-9B-GGUF` referenced. **Ollama:** `ornith-1.5` exists: `9b` 6.6GB, `35b` 23GB, `397b` 242GB, all 256K, vision tagged.
- **Tool calling:** yes — "emits well-formed function calls" parsed to `tool_calls` (qwen3_xml / qwen3_coder parsers). No structured-output claim.
- **Licence:** **MIT** (HF tag; secondary confirms).
- **Sources (primary):** https://huggingface.co/ornith-ai/Ornith-1.5-397B ; https://huggingface.co/ornith-ai/Ornith-1.5-9B ; https://huggingface.co/ornith-ai/Ornith-1.5-35B (found via search, not fetched) ; https://ollama.com/library/ornith-1.5. **Secondary:** https://datanorth.ai/news/ornith-releases-ornith-1-5 ; https://gigazine.net/gsc_news/en/20260820-ornith-1-5/.
- **Evidence quality:** High for 397B/9B; Medium for 35B (not fetched).

---

## 6. `laguna-s-2.1` → `poolside/Laguna-S-2.1`

- **Availability:** released weights (HF BF16 + official FP8/NVFP4/INT4/GGUF; Ollama local tags).
- **Publisher / family:** poolside, Laguna series (siblings: Laguna XS 2.1 33B-A3B, Laguna M.1 225B-A23B; DFlash draft model for speculative decoding).
- **Release date:** card: benchmarks "as of 21 July 2026", collection updated Aug 3; secondary press (GlobeNewswire via aimagazine) — date not pinned from a primary dated source; late July/early Aug 2026 likely.
- **Architecture:** MoE 118B total / ~8B active; 48 layers (12 global + 36 sliding-window, window 512); 256 routed experts top-10 + 1 shared; GQA 8 KV heads, head dim 128, softplus output gating; vocab 100,352. BF16 ~236GB.
- **Quantizations:** official `poolside/Laguna-S-2.1-GGUF`, FP8, NVFP4, INT4, `-NVFP4-mlx`; 96 quantized repos in tree.
- **Modalities:** text → text.
- **Role:** code / agentic SWE, long-horizon.
- **Context:** 1,048,576 (card). Ollama: 256K on GGUF tags, 1M on MLX tags.
- **Runtimes:** vLLM, SGLang (`poolside_v1` tool parser), Transformers (`trust_remote_code`), TRT-LLM, llama.cpp (poolside fork for full support), Ollama, Docker Model Runner. **Ollama:** `laguna-s-2.1` tags latest/q4_K_M 96GB, q8_0 128GB, f16 235GB, mxfp8 136GB, nvfp4 66GB, dflash-nvfp4 68GB, mlx-bf16 237GB; tools + thinking.
- **Tool calling / state:** tool calling supported (`poolside_v1` parser; Ollama template). Native reasoning with interleaved thinking; `enable_thinking` per request; **"works best with preserved thinking"** — keep `reasoning_content` in history or the model may stop reasoning in follow-up steps. No structured-output claim.
- **Licence:** **OpenMDW-1.1** ("fully permissive … No permission required"). Not gated.
- **Sources (primary):** https://huggingface.co/poolside/Laguna-S-2.1 ; https://huggingface.co/poolside/Laguna-S-2.1-GGUF ; https://ollama.com/library/laguna-s-2.1. **Secondary:** https://aimagazine.com/globenewswire/3330818.
- **Evidence quality:** High.

---

## 7. `laguna-xs-2.1` → `poolside/Laguna-XS-2.1`

- **Availability:** released weights.
- **Publisher / family:** poolside, Laguna; "upgraded version of its predecessor, Laguna XS.2".
- **Release date:** not stated on card (mentions "launch-day support"); same window as S 2.1 (Jul/Aug 2026).
- **Architecture:** MoE 33B total / 3B active; 40 layers (10 global + 30 SWA-512); 256 experts + 1 shared; Muon optimizer; sigmoid gating; FP8 KV cache.
- **Quantizations:** official `poolside/Laguna-XS-2.1-GGUF` (BF16, Q4_K_M), FP8, NVFP4, INT4, NVFP4-mlx; 41 community quants.
- **Modalities:** text → text.
- **Role:** local agentic coding.
- **Context:** 262,144.
- **Runtimes:** vLLM >=0.21.0 (parser fix vllm#47311), SGLang (PR), Transformers >=5.7.0, TRT-LLM 1.3.0rc16+, llama.cpp (upstream PR until merged), Ollama (library; **known issue: empty output on Apple Silicon/Metal** pending fix), Docker Model Runner. **Ollama:** `laguna-xs-2.1` tags latest/q4_K_M 20GB, q8_0 36GB, bf16 67GB, mxfp8 40GB, nvfp4 20GB, mlx-bf16 68GB; 256K; tools + thinking.
- **Tool calling / state:** supported (`poolside_v1` parser, `--enable-auto-tool-choice`); reasoning on by default, `enable_thinking:false` to disable; preserved thinking recommended (return `reasoning_content`), not a hard requirement. No structured-output claim.
- **Licence:** **OpenMDW-1.1**.
- **Sources (primary):** https://huggingface.co/poolside/Laguna-XS-2.1 ; https://huggingface.co/poolside/Laguna-XS-2.1-GGUF ; https://ollama.com/library/laguna-xs-2.1.
- **Evidence quality:** High.

---

## 8. `deepseek-v4-pro` → `deepseek-ai/DeepSeek-V4-Pro`

- **Availability:** released weights (HF live, FP4+FP8 mixed; Ollama cloud-only). Note: DeepSeek's hosted V4-Pro was temporarily replaced by V4.1-Flash from 2026-09-14 pending V4.1-Pro (secondary, iThome); weights remain downloadable.
- **Publisher / family:** DeepSeek, V4 family: `DeepSeek-V4-Pro-Base`, `DeepSeek-V4-Pro`, `DeepSeek-V4-Flash-Base`, `DeepSeek-V4-Flash`. "Pro-Max" = max reasoning-effort mode, not a checkpoint.
- **Release date:** 2026-04-24 (secondary, multiple); paper "Published Apr 26".
- **Architecture:** MoE 1.6T total / 49B active (Flash: 284B / 13B); hybrid CSA+HCA attention, mHC, Muon; >32T tokens pretraining.
- **Quantizations:** release checkpoint mixed FP4 (experts) + FP8; Base FP8. Community GGUF for llama.cpp/Ollama/LM Studio linked ("Browse Quantizations"); no official GGUF.
- **Modalities:** text → text.
- **Role:** frontier general / reasoning / agentic coding.
- **Context:** 1M; Think Max recommends >=384K window.
- **Runtimes:** vLLM, SGLang, Transformers, Docker Model Runner; local guide in repo. **No Jinja chat template** — uses `encoding/encode_messages(thinking_mode=...)`. **Ollama:** `deepseek-v4-pro` exists, tags `:cloud` and `:0813-cloud` only (1M, tools/thinking).
- **Tool calling / structured output:** no explicit claim on card; agentic benchmarks (Terminal Bench 2.0, SWE-bench, BrowseComp, MCPAtlas, Toolathlon). Thinking modes: Non-think, Think High, Think Max (special system prompt). Sampling temp 1.0 / top_p 1.0.
- **Licence:** **MIT** ("This repository and the model weights are licensed under the MIT License").
- **Sources (primary):** https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro ; https://ollama.com/library/deepseek-v4-pro. **Secondary:** https://framia.converge.ai/page/en-US/news/deepseek-v4-announcement-april-2026.
- **Evidence quality:** High.

---

## 9. `kimi-k3` → `moonshotai/Kimi-K3`

- **Availability:** released weights (HF live; F32/BF16/U8 tensors; 56 community quants). Ollama cloud-only.
- **Publisher / family:** Moonshot AI, Kimi K3.
- **Release date:** card not dated; footnotes "as of July 23, 2026", collection updated Jul 29 → late July 2026.
- **Architecture:** MoE 2.8T total / 104B active; 93 layers (1 dense); 69 Kimi Delta Attention (KDA) + 24 Gated MLA layers; 96 heads, hidden 7168; 896 experts, 16 routed + 2 shared; SiTU-GLU; 160K vocab; MoonViT-V2 vision encoder (401M). QAT from SFT onward: MXFP4 weights / MXFP8 activations.
- **Variants:** single checkpoint; 2 adapters, 52 finetunes, 56 quants listed on Hub.
- **Modalities:** text + image (card table); intro also says video understanding → text.
- **Role:** frontier agentic / long-horizon coding / knowledge work.
- **Context:** 1,048,576.
- **Runtimes:** vLLM, SGLang, TokenSpeed recommended; Docker Model Runner; Transformers (`trust_remote_code=True`); llama.cpp only via community quants. **Ollama:** `kimi-k3` exists, only `:cloud` (2.81T, 1M, vision/tools/thinking; $3/$15 per M).
- **Continuation requirements (exact card wording as extracted):**
  - "Kimi K3 always has thinking enabled, and will return `reasoning_content`."
  - Effort via top-level `reasoning_effort` ∈ {low, high, max}, default max.
  - Multi-turn / tool calls: "requires the complete assistant message returned by the API to be passed back to `messages` as-is," "including `reasoning_content` and `tool_calls`, not just `content`."
  - Quickstart covers structured output, partial mode, tool choice, dynamic tool loading, context caching (API docs; card gives no local-serving structured-output guarantee).
  - Eval sampling: effort max, temp 1.0, top_p 0.95 (single-step) / 1.0 (agentic).
- **Licence:** **"Kimi K3 License"** (code + weights). MIT-style grant plus: §2 — Model-as-a-Service business with >US$20M revenue over any 12 months must sign a separate agreement with Moonshot before commercial use; §3 — commercial product with >100M MAU **or** >US$20M monthly revenue must display "Kimi K3" prominently in the UI; §4 — exemptions for internal use and for use via Moonshot's official products / certified inference partners. AS-IS warranty. Contact license@moonshot.ai.
- **Dependencies:** none.
- **Sources (primary):** https://huggingface.co/moonshotai/Kimi-K3 ; https://huggingface.co/moonshotai/Kimi-K3/blob/main/LICENSE ; https://ollama.com/library/kimi-k3.
- **Evidence quality:** High.

---

## 10. `mistral-large-4` → no HF checkpoint yet (`mistralai/*Large-4*` absent as of 2026-10-11)

- **Availability:** **announced weights** (currently API-only). Publisher blog (2026-10-06): "We will release the weights by the end of the month" / "Weights drop end of this month." No day given. HF `mistralai` org listing (77 repos, sorted by recent) shows **no** Large-4 repo; newest "Large" is `Mistral-Large-3-675B-Instruct-2512-*`. Ollama `mistral-large-4` exists but only `:cloud`.
- **Publisher / family:** Mistral AI, Mistral Large.
- **Architecture (blog):** ~1T params MoE, 52B active, natively multimodal, "hybrid instruct-and-reasoning". Ollama page: 1.05T total, 52B active (readme says 49B — inconsistent), 1.6B vision encoder.
- **Modalities:** multimodal input (documents, charts, natural images, visual grounding); text out; 160+ languages.
- **Context:** blog not stated; Ollama cloud page 1M.
- **Tool calling:** blog: agentic tool use trained; Ollama tags tools/thinking/vision.
- **Licence:** not named anywhere yet ("open-weight"; self-deploy). **Unknown until weights ship** — do not assume Apache-2.0.
- **API:** public preview via Mistral Studio; $1.36 / $4.18 per M tokens.
- **Sources (primary):** https://mistral.ai/news/mistral-large-4/ ; https://huggingface.co/mistralai ; https://ollama.com/library/mistral-large-4. **Secondary:** https://betanews.com/article/mistral-large-4-preview-open-weights/ ; https://letsdatascience.com/news/mistral-debuts-large-4-open-weight-model-preview-cbf9e0b5.
- **Evidence quality:** High for "not downloadable today"; low for everything about the eventual weights.

---

## 11. `qwen3.8` — ambiguous alias; plausible concrete checkpoints

Open-weight Qwen3.8 checkpoints found (GitHub README QwenLM/Qwen3.8 names exactly two):

**(a) `Qwen/Qwen3.8-27B` — most likely intended for a local gateway** (+ `Qwen/Qwen3.8-27B-FP8`)
- released weights; 2026-08-14 (GitHub README).
- Dense 27B (HF 28B) incl. vision encoder; 64 layers, hidden 5120, Gated DeltaNet:Gated Attention 3:1; MTP-trained.
- Modalities: text + image + video → text. Context 262,144 native, YaRN to 1M.
- Thinking on by default, `enable_thinking: False` to disable; `reasoning_effort` ∈ {xhigh (default), medium, low}; `preserve_thinking` default on (keeps all historical thinking; example appends `reasoning_content` and `reasoning`).
- Tool calling: no explicit protocol claim on card ("broader support for popular harnesses"); Ollama tags tools/thinking/vision.
- Runtimes: Transformers, vLLM, SGLang, TokenSpeed, Docker Model Runner; llama.cpp/Ollama via community quants (1,383 quant repos; no official GGUF). **Ollama:** `qwen3.8` → `latest`/`27b` 18GB, `27b-mlx` 18GB, 256K (12 tags total).
- Licence: **Apache-2.0**.

**(b) `Qwen/Qwen3.8-2.4T-A95B`**
- released weights; 2026-08-12 (GitHub README).
- MoE 2.4T total / 95B active; 92 layers, hidden 8192, 512 experts (10 routed + 1 shared); Gated DeltaNet + Gated Attention; MTP. BF16 safetensors (~4.8TB est.).
- Text-only ("Multimodal inputs are not supported"). Context 262,144 native → 1,010,000.
- **Thinking cannot be disabled**; `reasoning_effort` xhigh/medium/low; `preserve_thinking` default on.
- Runtimes: SGLang, vLLM, TokenSpeed, Transformers, Docker Model Runner; 34 community quants.
- Licence: tagged **"qwen3.8-max"** (custom Qwen3.8-specific licence file; terms not read — secondary calls it "bespoke"). Not Apache.

**(c) Qwen3.8-Max — API-only** (Qwen Cloud; adds vision, non-thinking mode, built-in tools, 1M default). Hosted release 2026-08-03 (secondary). Not downloadable.

- **Sources (primary):** https://github.com/QwenLM/Qwen3.8 ; https://huggingface.co/Qwen/Qwen3.8-27B ; https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B ; https://ollama.com/library/qwen3.8. **Secondary:** https://datanorth.ai/news/alibaba-releases-qwen3-8-27b ; https://runtimewire.com/article/alibaba-qwen38-24t-open-weights-enterprise-license.
- **Evidence quality:** High for (a)/(b) existence; Medium for the 2.4T licence terms.

---

## 12. `qwen3.6` — ambiguous alias; plausible concrete checkpoints

**(a) `Qwen/Qwen3.6-35B-A3B`** — first open Qwen3.6; 2026-04-17 (secondary noze.it; card: April 2026).
- MoE 35B / 3B active; 256 experts (8 routed + 1 shared); 40 layers, hidden 2048; vision encoder. Text+image+video → text. Context 262,144 → 1,010,000 YaRN (card advises >=128K for thinking).
- Tool calling: "excels in tool calling capabilities"; `--tool-call-parser qwen3_coder`; Qwen-Agent/MCP. Thinking on by default, `enable_thinking: False`, `preserve_thinking`; `/think` `/nothink` soft switches NOT supported.
- Runtimes: SGLang >=0.5.10, vLLM >=0.19.0, KTransformers, Transformers, Docker Model Runner; `Qwen3.6-35B-A3B-FP8` exists; 874 community quants, no official GGUF.
- Licence **Apache-2.0**.

**(b) `Qwen/Qwen3.6-27B`** — dense 27B (HF 28B), April 2026 (collection updated Apr 22). Same hybrid Gated DeltaNet/Gated Attention layout, 64 layers, hidden 5120; text+image(+video) → text; 262,144 → 1,010,000; tool calling (qwen3_coder parser); thinking on by default; Apache-2.0; 743 community quants.

**(c) API-only:** Qwen3.6-Plus (2026-04-02, Model Studio, 1M context, thinking+non-thinking) and Qwen3.6-Max-Preview. Not downloadable.

- **Ollama:** `qwen3.6` exists: `latest`=`35b` 23–24GB, `27b` 18–19GB, `27b-mlx`, `35b-mlx`; 256K; vision/tools/thinking (35 tags). → For a local gateway, "qwen3.6" most plausibly means `qwen3.6:35b` (Ollama default) or `Qwen/Qwen3.6-35B-A3B`.
- **Sources (primary):** https://huggingface.co/Qwen/Qwen3.6-35B-A3B ; https://huggingface.co/Qwen/Qwen3.6-27B ; https://ollama.com/library/qwen3.6. **Secondary:** https://www.noze.it/en/insights/qwen-3-6/.
- **Evidence quality:** High.

---

## 13. `deepseek-v4.1-flash` → `deepseek-ai/DeepSeek-V4.1-Flash`

- **Availability:** released weights (HF live; F8_E4M3/BF16/F32/I8 tensors; 108 community quants). Ollama cloud-only.
- **Publisher / family:** DeepSeek; first/smallest model of the new "Causal Encoder-Decoder (CED)" architecture family. V4-Flash and V4-Flash-Vision-Exp retired; stands in for V4-Pro on the API from 2026-09-14 until V4.1-Pro ships (secondary).
- **Release date:** 2026-09-10 (secondary: iThome 2026-09-11). Card: 2026.
- **Architecture:** multimodal MoE, 552B backbone params (HF metadata 763B total incl. vision/others); 40 layers = 20 causal-encoder + 20 decoder; per MoE layer 1 shared + 384 routed experts, 6 active; **8B active during prefill, 16B during decode**; global KV cache 890 B/token (~1/4 of V4-Flash); DeepSeek-ViT vision encoder.
- **Modalities:** text + image → text.
- **Role:** fast agentic / coding general model.
- **Context:** up to 1M.
- **Runtimes:** vLLM, SGLang, Transformers, Docker Model Runner; llama.cpp/Ollama/LM Studio via community quants. **Ollama:** `deepseek-v4.1-flash` only `:cloud` (763B, 1M, vision/tools/thinking).
- **Tool calling / structured output:** no native format described on card; tool calls appear in reference prompt-encoding tests and deepseek-recipe toolkit. Reasoning effort is a **continuous integer 1–100** (instruct evals use 100); thinking can be disabled.
- **Licence:** **MIT**.
- **Sources (primary):** https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash ; https://ollama.com/library/deepseek-v4.1-flash. **Secondary:** https://www.ithome.com.tw/news/178871.
- **Evidence quality:** High.

---

## 14. `nemotron-3.5-lightning` → `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-{BF16,NVFP4}`

- **Availability:** released weights (HF BF16 + NVFP4 + Base; official GGUF via `ggml-org/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF`; Ollama local tags).
- **Publisher / family:** NVIDIA, Nemotron 3.5 ("Lightning" = efficiency tier). GA 2026-08-11 (card + secondary). Training data Dec 2025–May 2026.
- **Architecture:** hybrid Mamba-2 + MoE + select attention; 30B total / ~3B active; 52 layers, hidden 2688, 128 routed experts (6 active) + 1 shared; MTP layers. Draft models: `-NVFP4-DSpark`, `-NVFP4-DFlash`.
- **Modalities:** text → text (EN + code; ES/FR/DE/IT/JA, secondary adds ZH).
- **Role:** general reasoning + chat; always-on agents (Ollama page explicitly names OpenClaw and Hermes Agent harnesses).
- **Context:** up to 1M (BF16 config 262,144; NVFP4 config 1,048,576; "for single H100 we use 256K"). Ollama: 1M default, 256K MLX.
- **Runtimes:** vLLM v0.27.1 (`--tool-call-parser qwen3_coder`, reasoning parser `nemotron_v3`), TRT-LLM 1.3.0rc24, SGLang dev container, llama.cpp (official GGUF), Ollama, LM Studio, Docker Model Runner, NVIDIA NIM. **Ollama:** `nemotron-3.5-lightning` → `latest`/`30b` 25GB, `30b-mlx` 23GB (11 tags); tools + thinking.
- **Tool calling / structured output:** tool calling supported (OpenAI-compatible example; `force_nonempty_content: True` recommended for coding agents); training data includes tool calling and structured outputs (no separate inference-time structured-output guarantee). Thinking on by default, `enable_thinking` via `chat_template_kwargs`.
- **Licence:** **OpenMDW-1.1** ("ready for commercial use"; distinct from Apache-2.0 and NVIDIA Open Model License).
- **Sources (primary):** https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 ; https://ollama.com/library/nemotron-3.5-lightning ; https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b. **Secondary:** https://www.digitalapplied.com/blog/nvidia-nemotron-3-5-lightning-30b-a3b-efficiency-tier-2026 ; https://unsloth.ai/docs/models/nemotron-3.5.
- **Evidence quality:** High.

---

## 15. `muse-glimmer` → `meta-models/Muse-Glimmer-30B`

- **Availability:** released weights (HF BF16 + two official 4-bit "K-Quant" variants + drafter; Ollama local tags).
- **Publisher / family:** Meta (HF org `meta-models`, Meta Superintelligence Lab); "Muse" family — Glimmer is **distilled from the closed Muse Spark** and "generally less capable" than it. Meta promised Muse Spark 1.2 weights later (secondary, implicator.ai) — not verified as released.
- **Release date:** 2026-08-10 (secondary; collection updated Aug 10).
- **Architecture:** **dense** causal transformer, ~29.6B total incl. ~1.8B ViT-G/14 perception encoder (50 layers, width 1536, patch 14, up to 4,096 visual tokens/image); LM 52 layers, hidden 6656, GQA 32Q/2KV, head dim 128, SwiGLU 19,968, local/global attention with 2048 sliding window. DFlash-based speculative drafter (5 layers, block 16).
- **Quantizations:** official BF16, "K-Quant-Dynamic" (32GB VRAM) and "K-Quant-17GB" (24GB VRAM); collection mentions GGUF k-quants + ExecuTorch builds; ~177 community quants.
- **Modalities:** text + image → text; no audio; video as frames.
- **Role:** local autonomous agents on consumer hardware; coding agents, tool use, multimodal reasoning, synthetic data, LLM-as-judge.
- **Context:** 131,072+ (card); Ollama 128K.
- **Runtimes:** Transformers (`AutoModelForMultimodalLM`), vLLM, SGLang, Docker Model Runner, llama.cpp (used for RTX 5090 benchmark); Ollama/LM Studio via listed quants. **Ollama:** `muse-glimmer` → `latest`/`30b` 18GB, `30b-mlx` 19GB (15 tags); 128K; vision/tools/thinking.
- **Tool calling / structured output:** card claims "reliable tool use" with schema-following function calls across multi-step workflows; MCP Atlas 75.5 (self-reported). No separate structured-output claim. **No thinking toggle**: effort set by system-prompt line `Reasoning strength: <low|medium|high|xhigh>`.
- **Licence:** **Apache-2.0** for all artifacts (weights, quants, drafter, perception encoder); training data/code private. Not gated; Usage Policy linked; not for users under 18.
- **Sources (primary):** https://huggingface.co/meta-models/Muse-Glimmer-30B ; https://ollama.com/library/muse-glimmer. **Secondary:** https://www.implicator.ai/meta-releases-30b-open-weight-muse-glimmer-and-promises-spark-1-2-weights/ ; https://campustechnology.com/articles/2026/08/26/meta-releases-muse-glimmer-an-open-weight-ai-model-designed-to-run-on-consumer-hardware.aspx.
- **Evidence quality:** High.

---

## Cross-cutting notes for the router

1. **Reasoning-state continuation requirements** (must be preserved across tool-call turns by the gateway): Kimi K3 (hard requirement: pass full assistant message incl. `reasoning_content` + `tool_calls`), Kimi K2.7 Code (forced on; `reasoning_content`/`reasoning` field), Laguna S/XS 2.1 (strongly recommended; model may stop reasoning otherwise), Qwen3.6/3.8 (`preserve_thinking` default on), North Mini Code (recommended), GLM-5.3 (`clear_thinking` default false — i.e., keeps thinking).
2. **Thinking cannot be disabled:** Kimi K3, Kimi K2.7 Code, Qwen3.8-2.4T-A95B. Can be disabled: Qwen3.8-27B, Qwen3.6-*, Laguna, Nemotron 3.5 Lightning, DeepSeek V4/V4.1 (modes), GLM-5.3 (effort levels), Muse Glimmer (system-prompt effort, no off switch described).
3. **Effort parameter shapes differ:** `reasoning_effort` low/high/max (Kimi K3, GLM-5.3); xhigh/medium/low (Qwen3.6/3.8); integer 1–100 (DeepSeek V4.1-Flash); system-prompt string (Muse Glimmer); `enable_thinking` boolean (Laguna, Nemotron, Qwen).
4. **Ollama "cloud" entries are not local models:** glm-5.3, kimi-k3, kimi-k2.7-code, deepseek-v4-pro, deepseek-v4.1-flash, mistral-large-4 expose only `:cloud` tags. Only north-mini-code-1.0, ornith, ornith-1.5, laguna-s-2.1, laguna-xs-2.1, qwen3.8, qwen3.6, nemotron-3.5-lightning, muse-glimmer have pullable local weights.
5. **Licence buckets:** Apache-2.0 (North Mini Code, Qwen3.8-27B, Qwen3.6-27B/35B-A3B, Muse Glimmer); MIT (DeepSeek V4-Pro, V4.1-Flash, Ornith 1.0/1.5, GLM-5.3-Flash); OpenMDW-1.1 (Laguna S/XS 2.1, Nemotron 3.5 Lightning); custom MIT-derived with revenue/MAU clauses (Kimi K3 — $20M MaaS / 100M MAU attribution; GLM-5.3 — $10B MaaS security review); Modified MIT, terms unread (Kimi K2.7 Code); custom "qwen3.8-max" (Qwen3.8-2.4T-A95B, unread); unknown (Mistral Large 4, weights not shipped).
6. **Upstream-base caveats:** Ornith 1.0/1.5 are post-trained on Gemma 4 and Qwen 3.5; the cards claim MIT but do not discuss Gemma Terms of Use inheritance for any Gemma-derived size — legal review item.

---

## Summary table

| Seed | Resolved checkpoint | Availability | Licence | Role | Modalities (in→out) | Context (card) | Ollama local / GGUF | Evidence |
|---|---|---|---|---|---|---|---|---|
| glm-5.3 | zai-org/GLM-5.3 (753B MoE; sibling GLM-5.3-Flash 320B/18B) | released weights (2026-08-28/29) | GLM-5.3 License (custom; $10B MaaS review); Flash: MIT | coding / agentic reasoning | text→text (Flash: image+text→text) | not stated; evals to 1M; Ollama 1M | Ollama cloud-only; community GGUF (unsloth) | High |
| kimi-k2.7-code | moonshotai/Kimi-K2.7-Code (1T/32B MoE) | released weights (2026-06-12) | Modified MIT (terms unread) | code / agentic SWE | image(+video API)+text→text | 256K | Ollama cloud-only; 28 community quants | High / licence Med |
| north-mini-code-1.0 | CohereLabs/North-Mini-Code-1.0 (30B/3B MoE) | released weights (~Jun 2026) | Apache-2.0 (+Cohere Labs AUP per Ollama) | code / agentic SWE | text→text | 256K in / 64K out | Ollama local (q4_K_M 19GB…bf16 61GB, MLX); community GGUF | High |
| ornith | deepreinforce-ai/Ornith-1.0-{9B,31B,35B,397B} | released weights (Jun 2026) | MIT (built on Gemma 4 + Qwen 3.5) | agentic coding / reasoning | text+image→text | 262,144 | Ollama local `ornith` 9b/35b; community GGUF | Med-High |
| ornith-1.5 | ornith-ai/Ornith-1.5-{9B,35B(-A3B),397B} | released weights (2026-08-19) | MIT (extends Ornith-1.0) | agentic coding / reasoning | text+image→text | 262,144 (YaRN ~1M) | Ollama local 9b/35b/397b; official 397B GGUF ref; unsloth 9B GGUF | High |
| laguna-s-2.1 | poolside/Laguna-S-2.1 (118B/8B MoE) | released weights (Jul/Aug 2026) | OpenMDW-1.1 | code / long-horizon agentic | text→text | 1,048,576 | Ollama local (q4_K_M 96GB…); official GGUF | High |
| laguna-xs-2.1 | poolside/Laguna-XS-2.1 (33B/3B MoE) | released weights (Jul/Aug 2026) | OpenMDW-1.1 | local agentic coding | text→text | 262,144 | Ollama local (q4_K_M 20GB…; Metal bug); official GGUF | High |
| deepseek-v4-pro | deepseek-ai/DeepSeek-V4-Pro (1.6T/49B MoE) | released weights (2026-04-24) | MIT | frontier general / reasoning | text→text | 1M (Think Max ≥384K) | Ollama cloud-only; community GGUF | High |
| kimi-k3 | moonshotai/Kimi-K3 (2.8T/104B MoE) | released weights (late Jul 2026) | Kimi K3 License ($20M MaaS agreement; 100M MAU/$20M-mo UI attribution) | frontier agentic / coding | text+image(+video)→text | 1,048,576 | Ollama cloud-only; 56 community quants | High |
| mistral-large-4 | none on HF yet (mistralai org has no Large-4) | **announced weights** / API-only today (weights "by end of month" per 2026-10-06 blog) | not named | general multimodal agentic | multimodal in→text | not stated (Ollama cloud 1M) | Ollama cloud-only; no GGUF | High (absence) |
| qwen3.8 | ambiguous → most likely Qwen/Qwen3.8-27B (dense); also Qwen/Qwen3.8-2.4T-A95B; Qwen3.8-Max API-only | released weights (27B 2026-08-14; 2.4T 2026-08-12) | 27B: Apache-2.0; 2.4T: "qwen3.8-max" custom | general / coding / agentic | 27B: text+image+video→text; 2.4T: text→text | 262,144 (YaRN 1M) | Ollama local `qwen3.8:27b` 18GB; community GGUF only | High |
| qwen3.6 | ambiguous → Qwen/Qwen3.6-35B-A3B (Ollama default) or Qwen/Qwen3.6-27B; Plus/Max-Preview API-only | released weights (Apr 2026) | Apache-2.0 | general / coding / tool use | text+image+video→text | 262,144 (YaRN 1.01M) | Ollama local 27b/35b; community GGUF only | High |
| deepseek-v4.1-flash | deepseek-ai/DeepSeek-V4.1-Flash (552B backbone; 8B prefill/16B decode active) | released weights (2026-09-10) | MIT | fast agentic / coding | text+image→text | 1M | Ollama cloud-only; community GGUF | High |
| nemotron-3.5-lightning | nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-{BF16,NVFP4} | released weights (2026-08-11) | OpenMDW-1.1 | general reasoning / always-on agents | text→text | up to 1M (256K single-H100) | Ollama local 30b 25GB; official ggml-org GGUF | High |
| muse-glimmer | meta-models/Muse-Glimmer-30B (dense ~29.6B incl. 1.8B ViT) | released weights (2026-08-10) | Apache-2.0 | local agents / tool use / multimodal | text+image→text | 131,072+ | Ollama local 30b 18GB; official 4-bit quants, GGUF k-quants | High |

No seed in this part resolved to "unverified": every name mapped to at least one live primary page. The only non-downloadable items are Mistral Large 4 (announced weights) and the hosted-only variants Qwen3.8-Max, Qwen3.6-Plus and Qwen3.6-Max-Preview.
