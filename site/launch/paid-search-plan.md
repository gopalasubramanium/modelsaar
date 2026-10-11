# Optional paid-search plan (not authorised; spend stays at zero)

Verified facts: none of the numbers below are known. Keyword volumes, CPCs and competition for this
niche were **not** available to this session (no Keyword Planner access); every figure is a hypothesis to be
replaced by the planner's data before any spend.

**Campaign (hypothesis):** Search only, English, India + United States + United Kingdom + Germany
(where self-hosted LLM interest is highest in community data — hypothesis), desktop-leaning, 09:00–23:00
local. Daily budget experiment: the smallest amount the account allows for 14 days; success = ≥ 1
install.sh fetch per 20 clicks (proxy) and any GitHub issue from a paid visitor.

| ad group (intent) | keyword themes (phrase/exact) | landing page |
|---|---|---|
| Route between local models | "local llm router", "route requests to local models", "model router ollama" | `/` |
| Ollama with several apps | "ollama multiple apps", "one endpoint for ollama", "openai compatible gateway ollama" | `/get-started/` |
| Capability-aware selection | "choose model by capability", "llm tool calling router", "vision model routing" | `/how-it-works/` |
| Privacy / local-only | "local llm gateway no cloud", "private ai gateway self hosted" | `/privacy/` |

Negatives: cloud, pricing, enterprise, "api key free", openai api key, chatgpt, course, jobs, salary,
router (networking) terms: wifi, tp-link, netgear.

Draft ads (RSA headlines ≤30, descriptions ≤90):
- H: "One address for local AI" · "Route to the right local model" · "Open source, Apache-2.0" · "Works with Ollama today"
- D: "Apps connect once and ask for auto. Verified capabilities, local-only by default, decisions you can inspect." · "Development preview. Python 3.10+ and your own models required. No cloud, no telemetry."

Measurement: landing-page views by ad group, `install.sh` fetch count (server logs), outbound GitHub
clicks (no tracking script; use UTM-free referrer counts from GitHub's traffic page), issues opened.
Stop rule: no install.sh fetch from paid traffic in 7 days → pause.
