"""Derive structural requirements and a cheap deterministic task classification.

Nothing here reads model outputs or follows instructions found in prompts; the
analysis is purely structural/lexical and its result is data for the router.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import TokenEstimateConfig
from .tokens import TokenBudget, _text_of, estimate_chat_tokens

TASKS = (
    "conversation",
    "coding",
    "agent",
    "math",
    "extraction",
    "document_vision",
    "translation",
    "summarization",
    "rag",
    "decision",
)


@dataclass
class Requirements:
    role: str = "generative"
    needs_tools: bool = False
    tool_choice_mode: str = "none"  # none | auto | required | named
    needs_parallel_tools: bool = False
    needs_json_schema: bool = False
    needs_json_object: bool = False
    needs_streaming: bool = False
    needs_vision: bool = False
    needs_audio: bool = False
    has_remote_image_url: bool = False
    needs_continuation: bool = False  # reasoning_content present in history
    outstanding_tool_call_ids: list[str] = field(default_factory=list)
    is_tool_result_turn: bool = False
    tokens: TokenBudget | None = None
    tasks: dict[str, float] = field(default_factory=dict)  # label -> confidence 0..1
    primary_task: str = "conversation"
    ambiguous: bool = False
    multilingual: bool = False
    languages: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    unsupported_fields_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = {
            "role": self.role,
            "needs_tools": self.needs_tools,
            "tool_choice_mode": self.tool_choice_mode,
            "needs_parallel_tools": self.needs_parallel_tools,
            "needs_json_schema": self.needs_json_schema,
            "needs_json_object": self.needs_json_object,
            "needs_streaming": self.needs_streaming,
            "needs_vision": self.needs_vision,
            "needs_audio": self.needs_audio,
            "has_remote_image_url": self.has_remote_image_url,
            "needs_continuation": self.needs_continuation,
            "outstanding_tool_call_ids": self.outstanding_tool_call_ids,
            "is_tool_result_turn": self.is_tool_result_turn,
            "tasks": self.tasks,
            "primary_task": self.primary_task,
            "ambiguous": self.ambiguous,
            "multilingual": self.multilingual,
            "languages": self.languages,
            "signals": self.signals,
        }
        if self.tokens:
            d["tokens"] = {
                "input_estimate": self.tokens.input_estimate,
                "output_allowance": self.tokens.output_allowance,
                "reasoning_allowance": self.tokens.reasoning_allowance,
                "images": self.tokens.images,
                "method": self.tokens.method,
                "total": self.tokens.total,
            }
        return d


# --------------------------------------------------------------------------- #
# Lexical signals (deterministic). Short lists on purpose: clear cases only.
# --------------------------------------------------------------------------- #
_CODE_FENCE = re.compile(r"```")
_CODE_WORDS = re.compile(
    r"\b(def |class |import |#include|function\s*\(|=>|console\.log|print\(|SELECT .* FROM|"
    r"traceback|stack ?trace|exception|compile|refactor|unit test|pytest|npm|pip install|git |"
    r"regex|typescript|python|javascript|rust|golang|\bjava\b|c\+\+|bash script|shell script|sql|undefined is not|"
    r"null pointer|segfault|syntax error|TypeError|ValueError|NameError|npm ERR|ModuleNotFound)\b",
    re.IGNORECASE,
)
_AGENT_TOOLS = re.compile(
    r"\b(bash|shell|execute_command|run_command|read_file|write_file|edit_file|list_dir|grep|glob|search_files|"
    r"apply_patch|str_replace|terminal|repo|repository)\b",
    re.IGNORECASE,
)
_AGENT_SYS = re.compile(r"\b(coding agent|software engineer|repository|codebase|workspace|terminal)\b", re.IGNORECASE)
_MATH = re.compile(
    r"(\\frac|\\int|\\sum|\^\d|\b\d+\s*[\+\-\*/×÷]\s*\d+\b|\bsolve\b|\bequation|\bintegral|\bderivative|\btheorem|"
    r"\bprove\b|\bprobability\b|\bcalculate\b|\bcompute\b|\bsum of\b|\bproduct of\b|\bprime\b|\barea\b|"
    r"\bperimeter\b|\bpercent|\baverage\b|\bhow many\b|\bsolve for\b|\d+\s*[×÷])",
    re.IGNORECASE,
)
_TRANSLATE = re.compile(r"\b(translate|translation|traduis|traducir|übersetze|翻译|翻訳)\b", re.IGNORECASE)
_SUMMARIZE = re.compile(r"\b(summari[sz]e|summary|tl;dr|tldr|condense|key points|abstract)\b", re.IGNORECASE)
_EXTRACT = re.compile(r"\b(extract|parse|structured|json|fields?|schema|csv|table of)\b", re.IGNORECASE)
_RAG = re.compile(r"(\bcontext:|\bdocument:|<context>|<document>|according to the (provided|following)|based on the (text|passage|document))", re.IGNORECASE)
_DECISION = re.compile(r"\b(classify|categori[sz]e|which of the following|yes or no|choose (one|between)|label)\b", re.IGNORECASE)
def _is_inline_data_url(url: str) -> bool:
    """Only base64 data: URLs are inline media; every other reference (http, HTTP, //, file, ftp, ...)
    is external and must not be fetched by the gateway or the backend on our behalf."""
    u = url.strip()
    return u[:5].lower() == "data:" and ";base64," in u[:120]


_GREETING = re.compile(r"\b(hi|hello|hey|thanks|thank you|good (morning|evening|afternoon)|bye|ok|okay|yes|no|sure)\b", re.IGNORECASE)
_NON_LATIN = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ஀-௿぀-ヿ一-鿿가-힯]")
_LATIN_HINTS = {
    "fr": re.compile(r"\b(le|la|les|des|est|avec|pour|vous|nous)\b", re.IGNORECASE),
    "es": re.compile(r"\b(el|los|las|está|para|usted|nosotros|gracias)\b", re.IGNORECASE),
    "de": re.compile(r"\b(der|die|das|und|nicht|ist|mit|für|Sie)\b"),
}


def _detect_languages(text: str) -> list[str]:
    langs: list[str] = []
    if _NON_LATIN.search(text):
        if re.search(r"[一-鿿]", text):
            langs.append("zh/ja")
        if re.search(r"[぀-ヿ]", text):
            langs.append("ja")
        if re.search(r"[가-힯]", text):
            langs.append("ko")
        if re.search(r"[Ѐ-ӿ]", text):
            langs.append("ru")
        if re.search(r"[؀-ۿ]", text):
            langs.append("ar")
        if re.search(r"[ऀ-ॿ]", text):
            langs.append("hi")
        if re.search(r"[஀-௿]", text):
            langs.append("ta")
        if re.search(r"[֐-׿]", text):
            langs.append("he")
    for code, rx in _LATIN_HINTS.items():
        if len(rx.findall(text)) >= 4:
            langs.append(code)
    if re.search(r"\b(the|and|is|are|you|please|what|how)\b", text, re.IGNORECASE):
        langs.append("en")
    return list(dict.fromkeys(langs))


def analyze_chat(body: dict[str, Any], cfg: TokenEstimateConfig, thinking_possible: bool = True) -> Requirements:
    req = Requirements()
    msgs = body.get("messages") or []
    tools = body.get("tools") or []
    req.needs_streaming = bool(body.get("stream"))
    req.needs_tools = bool(tools)
    tc = body.get("tool_choice")
    if tools:
        if tc is None or tc == "auto":
            req.tool_choice_mode = "auto"
        elif tc == "none":
            req.tool_choice_mode = "none"
        elif tc == "required":
            req.tool_choice_mode = "required"
        elif isinstance(tc, dict):
            req.tool_choice_mode = "named"
    if body.get("parallel_tool_calls") is True:
        req.needs_parallel_tools = True
    rf = body.get("response_format")
    if isinstance(rf, dict):
        if rf.get("type") == "json_schema":
            req.needs_json_schema = True
        elif rf.get("type") == "json_object":
            req.needs_json_object = True

    # Walk the history: modalities, tool continuity, continuation data.
    user_text_parts: list[str] = []
    system_text = ""
    last_user_text = ""
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        text, _ = _text_of(content)
        if isinstance(content, list):
            for p in content:
                if not isinstance(p, dict):
                    continue
                t = p.get("type")
                if t in ("image_url", "input_image", "image"):
                    req.needs_vision = True
                    url = ""
                    iu = p.get("image_url")
                    if isinstance(iu, dict):
                        url = str(iu.get("url", ""))
                    elif isinstance(iu, str):
                        url = iu
                    if not _is_inline_data_url(url):
                        req.has_remote_image_url = True
                elif t in ("input_audio", "audio"):
                    req.needs_audio = True
        if role in ("system", "developer"):
            system_text += text + "\n"
        elif role == "user":
            user_text_parts.append(text)
            last_user_text = text
        if role == "assistant":
            if m.get("reasoning_content"):
                req.needs_continuation = True
    last = msgs[-1] if msgs and isinstance(msgs[-1], dict) else {}
    req.is_tool_result_turn = last.get("role") == "tool"
    # The current round trip = tool messages at the tail answering the tool_calls of the assistant
    # message immediately before them. Older, already-answered calls do not pin anything.
    tail_ids: list[str] = []
    i = len(msgs) - 1
    while i >= 0 and isinstance(msgs[i], dict) and msgs[i].get("role") == "tool":
        if msgs[i].get("tool_call_id"):
            tail_ids.append(str(msgs[i]["tool_call_id"]))
        i -= 1
    issued: list[str] = []
    if i >= 0 and isinstance(msgs[i], dict) and msgs[i].get("role") == "assistant":
        issued = [str(c["id"]) for c in msgs[i].get("tool_calls") or [] if isinstance(c, dict) and c.get("id")]
    req.outstanding_tool_call_ids = [cid for cid in issued if cid in set(tail_ids)] if req.is_tool_result_turn else []

    # Task classification uses the *original* user intent, not just the last tool result.
    full_user = "\n".join(user_text_parts)
    scores: dict[str, float] = {t: 0.0 for t in TASKS}
    sig = req.signals

    def add(task: str, w: float, why: str) -> None:
        scores[task] = min(1.0, scores[task] + w)
        sig.append(f"{task}:{why}")

    if req.needs_tools:
        tool_names = " ".join(str((t.get("function") or {}).get("name", "")) for t in tools if isinstance(t, dict))
        if _AGENT_TOOLS.search(tool_names) or _AGENT_SYS.search(system_text):
            add("agent", 0.8, "agent-style tools/system prompt")
            add("coding", 0.5, "agent tools imply code work")
        else:
            add("agent", 0.4, "tools present")
    if _CODE_FENCE.search(full_user) or len(_CODE_WORDS.findall(full_user)) >= 2:
        add("coding", 0.7, "code fences or >=2 code keywords")
    elif _CODE_WORDS.search(full_user):
        add("coding", 0.35, "one code keyword")
    if _MATH.search(last_user_text or full_user):
        add("math", 0.5, "math symbols/keywords")
    if req.needs_json_schema or req.needs_json_object:
        add("extraction", 0.8, "structured output requested")
    elif _EXTRACT.search(last_user_text):
        add("extraction", 0.35, "extraction keywords")
    if req.needs_vision:
        add("document_vision", 0.9, "image input present")
    if _TRANSLATE.search(last_user_text):
        add("translation", 0.7, "translate keyword")
    if _SUMMARIZE.search(last_user_text):
        add("summarization", 0.6, "summarize keyword")
    if _RAG.search(full_user) or _RAG.search(system_text):
        add("rag", 0.6, "context/document framing")
    if _DECISION.search(last_user_text):
        add("decision", 0.4, "classification phrasing")
    langs = _detect_languages(full_user)
    req.languages = langs
    req.multilingual = len([lang for lang in langs if lang != "en"]) >= 1
    if req.multilingual:
        sig.append("multilingual:" + ",".join(langs))
    if max(scores.values()) == 0.0:
        words = last_user_text.split()
        vague = len(words) <= 3 and not _GREETING.search(last_user_text) and not req.needs_tools
        scores["conversation"] = 0.4 if vague else 0.6
        sig.append("conversation:default (no structural signals" + ("; very short/vague" if vague else "") + ")")
    req.tasks = {k: round(v, 2) for k, v in scores.items() if v > 0}
    req.primary_task = max(req.tasks.items(), key=lambda kv: kv[1])[0]
    top = sorted(req.tasks.values(), reverse=True)
    # Ambiguous when the best label is weak or two labels compete.
    req.ambiguous = top[0] < 0.5 or (len(top) > 1 and top[0] - top[1] < 0.2 and top[0] < 0.8)
    req.tokens = estimate_chat_tokens(body, cfg, thinking_possible)
    return req
