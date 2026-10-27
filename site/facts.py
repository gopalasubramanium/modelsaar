"""Facts the website states about ModelSaar — kept in one place and, where possible, read from the
repository so the site cannot drift from the product.

Edit here, not in the page fragments. ``python site/build.py`` embeds these values.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPO_URL = "https://github.com/gopalasubramanium/modelsaar"
CREATOR_NAME = "Gopala Subramanium"
CREATOR_URL = "https://me.sgopala.com"
PAYPAL_EMAIL = "gopalasubramanium@gmail.com"
LICENSE = "Apache-2.0"
STATUS = "public alpha"  # clearly labelled alpha; no git tag, no PyPI package, no container image published
VERSION_STRING = "0.1.0 (unreleased public alpha)"

# The revision the public installer pins. Must be a commit that is PUBLIC on GitHub and whose CI checks
# passed. Update this together with install.sh after each verified hardening-branch update.
INSTALL_SHA = "cf56cdd3416d8c853b64111b9b40211e5b126031"  # main: Odysseus session_id/cache_prompt compatibility (PR #4); build.py embeds it in install.sh
INSTALL_BRANCH = "main"

HOSTING_NOTE = ("The site is published as static files from the project repository through GitHub Pages (GitHub, Inc.), whose "
    "servers keep the access logs described above. The domain's DNS is managed at Cloudflare; no Cloudflare proxy "
    "or analytics feature is enabled for this site.")

TAGLINE = "One address for your local AI."
TAGLINE_LONG = (
    "ModelSaar is an open-source gateway that connects the AI apps you already use to the models you "
    "already run. Each request goes to a suitable available model, chosen from the task, verified "
    "model capabilities and the limits you set — with a decision you can inspect."
)

# ---- commands shown on the site (tested by site/check_site.py against the real CLI) --------------
INSTALL_ONE_LINER = "curl -fsSL https://modelsaar.com/install.sh | sh"
INSTALL_INSPECT = "curl -fsSL https://modelsaar.com/install.sh -o install.sh && less install.sh && sh install.sh"
INSTALL_UV = f"uv tool install git+{REPO_URL}@{{sha}}"
INSTALL_PIPX = f"pipx install git+{REPO_URL}@{{sha}}"
INSTALL_PIP = f"python3 -m venv ~/modelsaar-env && ~/modelsaar-env/bin/pip install git+{REPO_URL}@{{sha}}"
INSTALL_SOURCE = f"git clone {REPO_URL} && cd modelsaar && git checkout {{sha}} && python3 -m venv .venv && . .venv/bin/activate && pip install -e ."
# After the one-line installer `init` has already run (it wrote config + keys and discovered models), so
# the next command is `serve`; `init` belongs to the manual-install path only (it refuses to overwrite
# an existing config).
FIRST_USE = "modelsaar serve"
FIRST_USE_MANUAL = "modelsaar init\nmodelsaar serve"
FIRST_USE_CHECK = "modelsaar test"
GATEWAY_URL = "http://127.0.0.1:8484/v1"
# Terminal command that PRINTS the key; the printed line (starts with msk_) is what goes into a GUI field.
KEY_COMMAND = "head -1 ~/.modelsaar/keys/api_keys"
KEY_PLACEHOLDER = "msk_…  (the line printed by the command above)"
CLIENT_CONFIG_COMMANDS = {
    "Open WebUI": "modelsaar client-config open-webui",
    "OpenCode": "modelsaar client-config opencode",
    "OpenCode (V2 config)": "modelsaar client-config opencode-v2",
    "OpenClaw": "modelsaar client-config openclaw",
    "Hermes Agent": "modelsaar client-config hermes",
}


def client_config_list_html() -> str:
    """One command per client (separate commands, never a shell pipeline)."""
    return "<ul>" + "".join(f"<li>{name}: <code>{cmd}</code></li>" for name, cmd in CLIENT_CONFIG_COMMANDS.items()) + "</ul>"


def install_cmds() -> dict[str, str]:
    return {
        "uv": INSTALL_UV.format(sha=INSTALL_SHA),
        "pipx": INSTALL_PIPX.format(sha=INSTALL_SHA),
        "pip": INSTALL_PIP.format(sha=INSTALL_SHA),
        "source": INSTALL_SOURCE.format(sha=INSTALL_SHA),
    }


# ---- test counts quoted on the site (filled from the executed runs recorded in docs/verification-report.md;
#      check_site.py verifies they match the number of test functions collected at the pinned revision) ----
class _Counts(dict):
    __getattr__ = dict.__getitem__


TEST_COUNTS = _Counts(total=285, reviewer=29, sandbox=6)  # pytest --collect-only -m 'not live' at the built revision (/v1/decisions endpoint + request-size tests, 2026-10-28)


# ---- support matrix: one row per claim, with the kind of evidence behind it ------------------------
# evidence: "fixture" = automated tests against the controlled fake backend (the repository's test suite,
#                       run locally by the author; CI runs the same suite on push once the branch is public —
#                       a CI *definition* is not a CI *run*);
#           "live"    = exercised against a real backend (see docs/verification-report.md);
#           "docs"    = configuration documented from the client's primary documentation, not run;
#           "not-run" = nothing executed.
SUPPORT = [
    {"kind": "Interface", "item": "OpenAI-compatible Chat Completions (`/v1/chat/completions`, streaming SSE), `/v1/models`, `/healthz`, `/readyz`", "evidence": "fixture, live", "note": "Responses API and Anthropic Messages return an explicit 501."},
    {"kind": "Interface", "item": "`/v1/embeddings` with identity-anchored alias contracts", "evidence": "fixture", "note": "Real-model embeddings NOT RUN; contract, identity anchoring, deadlines and output validation are fixture-tested only."},
    {"kind": "Backend", "item": "Ollama (discovery via `/api/tags`, `/api/show`, `/api/ps`; inference via its OpenAI-compatible layer)", "evidence": "fixture, live", "note": "Ollama 0.40.3 and 0.40.5 with 8–11 models on an ASUS GX10, 2026-10-14 to 2026-10-24 (earlier: 0.32.13, 2026-10-11)."},
    {"kind": "Backend", "item": "Generic OpenAI-compatible server (vLLM, llama.cpp server, LM Studio, …) with declared models; vLLM `/tokenize` used for token counts", "evidence": "fixture", "note": "Not run against a real vLLM/llama.cpp server yet."},
    {"kind": "Client", "item": "Open WebUI", "evidence": "docs", "note": "Configuration generated by `modelsaar client-config open-webui`; real client workflow not run."},
    {"kind": "Client", "item": "OpenClaw", "evidence": "docs", "note": "`modelsaar client-config openclaw`; real client workflow not run."},
    {"kind": "Client", "item": "OpenCode (V1 and V2 config schemas)", "evidence": "docs", "note": "`modelsaar client-config opencode` (V1) or `modelsaar client-config opencode-v2` (V2); real client workflow not run."},
    {"kind": "Client", "item": "Hermes Agent", "evidence": "docs", "note": "`modelsaar client-config hermes`; real client workflow not run."},
    {"kind": "Client", "item": "Odysseus (plain OpenAI endpoint; its `session_id` / `cache_prompt` hints are consumed by the gateway)", "evidence": "fixture, owner", "note": "Request shape from Odysseus's `_apply_local_cache_affinity` is fixture-tested (`tests/test_client_compat_odysseus.py`). Odysseus chat through ModelSaar on the GX10 is working, reported by the owner on 2026-10-14 (gateway `cf56cdd`); not executed or recorded by the project, and tool, vision, streaming and agent workflows through Odysseus were not reported."},
    {"kind": "Behaviour", "item": "Tool calls and tool-result continuation on the same deployment; session pinning via `X-ModelSaar-Session` / `X-OpenWebUI-Chat-Id`", "evidence": "fixture, live", "note": "Live: direct HTTP checks (`scripts/live_client_checks.py`), not a client's own workflow."},
    {"kind": "Behaviour", "item": "Strict JSON schema, image input and context-size routing; unsupported media rejected before dispatch", "evidence": "fixture, live", "note": ""},
    {"kind": "Behaviour", "item": "Pool memory budgets (incl. assumed residency between polls), uncertain-occupancy holds on stream/probe/embedding timeouts, probes under gateway admission", "evidence": "fixture", "note": "Not exercised on real hardware; the live run predates the 2026-10-12 corrections."},
    {"kind": "Platform", "item": "macOS (arm64) and Linux (x86_64): source install, gateway, probes, evaluation", "evidence": "live", "note": "Windows: use WSL2; native Windows is untested."},
    {"kind": "Platform", "item": "Docker Compose (gateway only; models stay with your runtime)", "evidence": "fixture", "note": "Fresh-volume start is checked by `scripts/compose-smoke.sh` (defined in CI; no CI run exists yet for the current revision)."},
]


# ---- benchmark numbers: read from the committed live-run reports -----------------------------------
# Every number the site quotes about routing quality comes from these report files at build time. The
# runs are listed newest-last; "pass1b" is the owner-accepted Stage B Pass 1 result. Comparisons between
# runs that used different Ollama versions are cross-runtime and the site says so; no run isolates the
# effect of a single added model.
LIVE_RUNS = {
    "pass1b": {
        "dir": "docs/live-runs/2026-10-15-gx10-stage-b-pass1", "report": "stage-b-pass1b.json", "records": "stage-b-pass1b.records.jsonl",
        "label": "Stage B Pass 1 (accepted result, run “Pass 1b”)", "date": "2026-10-15", "ollama": "0.40.3", "models": "four models",
    },
    "pass2": {
        "dir": "docs/live-runs/2026-10-16-gx10-stage-b-pass2", "report": "stage-b-pass2.json", "records": "stage-b-pass2.records.jsonl",
        "label": "Stage B Pass 2 (qwen3-coder-next added; cross-runtime)", "date": "2026-10-16", "ollama": "0.40.5", "models": "five models",
    },
    "stagec": {
        "dir": "docs/live-runs/2026-10-24-gx10-stage-c", "report": "stage-c.json", "records": "stage-c.records.jsonl",
        "label": "Stage C (all eight roadmap models)", "date": "2026-10-24", "ollama": "0.40.5", "models": "eight models",
    },
}
HISTORICAL_RUN_DIR = "docs/live-runs/2026-10-11-gx10-hardening"  # three models, scorer 2026.10.11-2, Ollama 0.32.13; superseded, kept as history
LIVE_RUN_DIR = ROOT / LIVE_RUNS["pass1b"]["dir"]


def live_eval(run: str = "pass1b") -> dict:
    meta = LIVE_RUNS[run]
    rdir = ROOT / meta["dir"]
    rep = json.loads((rdir / meta["report"]).read_text(encoding="utf-8"))
    rows = []
    for name, v in rep["results"].items():
        rows.append(
            {
                "policy": name,
                "success": v["success"],
                "ci": v["ci95"],
                "completion": v["completion_rate"],
                "violations": v["capability_violations"],
                "p50": v["p50_ms"],
                "p95": v["p95_ms"],
                "n": v["n_scored"],
            }
        )
    # auto's selection distribution and the paired auto-vs-fixed-strong outcome, from the per-request records
    strong = rep["calibration"]["fixed_strong"]
    auto: dict[str, dict] = {}
    fixed: dict[str, dict] = {}
    for line in (rdir / meta["records"]).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("policy") == "auto":
            auto[r["task"]] = r
        elif r.get("policy") == f"test:{strong}":
            fixed[r["task"]] = r
    selection: dict[str, int] = {}
    for r in auto.values():
        key = (r.get("deployment") or r["model"]).split("/", 1)[1]
        selection[key] = selection.get(key, 0) + 1
    tasks = sorted(auto)
    auto_only = [t for t in tasks if auto[t].get("ok") and not fixed.get(t, {}).get("ok")]
    strong_only = [t for t in tasks if fixed.get(t, {}).get("ok") and not auto[t].get("ok")]
    return {
        "run": run,
        "label": meta["label"],
        "date": meta["date"],
        "ollama": meta["ollama"],
        "models": meta["models"],
        "dir": meta["dir"],
        "generated_at": rep["generated_at"],
        "deployments": rep["deployments"],
        "n_calib": rep["n_calib"],
        "n_test": rep["n_test"],
        "conditions": rep["conditions"],
        "sandbox": rep["sandbox"],
        "rows": rows,
        "routing": rep["routing"],
        "per_deployment": rep["per_deployment_test"],
        "calibration": rep["calibration"],
        "fixed_strong": strong.split("/", 1)[1],
        "fixed_fast": rep["calibration"]["fixed_fast"].split("/", 1)[1],
        "auto_successes": sum(1 for r in auto.values() if r.get("ok")),
        "strong_successes": sum(1 for r in fixed.values() if r.get("ok")),
        "auto_only": auto_only,
        "strong_only": strong_only,
        "selection": dict(sorted(selection.items(), key=lambda kv: -kv[1])),
        "auto_row": next(r for r in rows if r["policy"].startswith("auto")),
        "strong_row": next(r for r in rows if r["policy"].startswith("fixed-strong")),
        "fast_row": next(r for r in rows if r["policy"].startswith("fixed-fast")),
    }


CLASSIFIER_RUN_DIR = "docs/live-runs/2026-10-25-gx10-classifier-comparison"  # classifier OFF/ON comparison, 2026-10-25, Ollama 0.40.5


def classifier_comparison() -> dict:
    """Numbers of the classifier OFF/ON comparison, read from its derived files (comparison.json, acceptance.json)."""
    rdir = ROOT / CLASSIFIER_RUN_DIR
    cmp = json.loads((rdir / "comparison.json").read_text(encoding="utf-8"))
    acc = json.loads((rdir / "acceptance.json").read_text(encoding="utf-8"))
    on = cmp["on"]
    counters = on["gateway_classifier_counters"]["last"]
    twin = cmp["off_twin_compromised"]["record_status_counts"]
    return {
        "dir": CLASSIFIER_RUN_DIR,
        "date": on["generated_at"][:10],
        "model": cmp["classifier_config"]["model"],
        "timeout_ms": int(cmp["classifier_config"]["timeout_s"] * 1000),
        "calls": counters["calls"],
        "timeouts": counters["timeouts"],
        "auto_consulted": len(cmp["classifier_consulted_tasks_auto"]),
        "auto_timeouts": on["report_classifier"]["timeouts"],
        "overhead_p95_ms": on["report_overhead"]["p95"],
        "overhead_median_ms": on["overhead_ms"]["median"],
        "auto_successes": on["auto_successes"],
        "reference_successes": cmp["off_reference_pass1b"]["auto_successes"],
        "gain": cmp["decision_rule"]["success_gain_on_minus_off"],
        "twin_422": twin.get("422", 0),
        "twin_200": twin.get("200", 0),
        "failed_targets": [c["target"] for c in acc["checks"] if c["result"].startswith("FAIL")],
    }


def seconds(ms: float) -> str:
    return f"{ms / 1000:.2f} s"


# ---- structured data -------------------------------------------------------------------------------
def jsonld_home(site_url: str, commit: str) -> list[dict]:
    return [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "ModelSaar",
            "url": site_url,
            "description": TAGLINE_LONG,
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareSourceCode",
            "name": "ModelSaar",
            "description": TAGLINE_LONG,
            "codeRepository": REPO_URL,
            "author": {"@type": "Person", "name": CREATOR_NAME, "url": CREATOR_URL},
            "programmingLanguage": "Python",
            "runtimePlatform": "Python 3.10+",
            "license": "https://www.apache.org/licenses/LICENSE-2.0",
            "url": site_url,
            "version": VERSION_STRING,
        },
    ]


def jsonld_page(site_url: str, path: str, title: str, desc: str) -> list[dict]:
    crumbs = [{"@type": "ListItem", "position": 1, "name": "Home", "item": site_url + "/"}]
    parts = [p for p in path.strip("/").split("/") if p]
    acc = ""
    for i, p in enumerate(parts, start=2):
        acc += "/" + p
        crumbs.append({"@type": "ListItem", "position": i, "name": title if i == len(parts) + 1 else p.replace("-", " "), "item": site_url + acc + "/"})
    return [
        {"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": desc, "url": site_url + path, "isPartOf": {"@type": "WebSite", "name": "ModelSaar", "url": site_url}},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs},
    ]


def llms_txt(site_url: str, pages: list[tuple[str, str, str]]) -> str:
    lines = [
        "# ModelSaar",
        "",
        f"> {TAGLINE_LONG}",
        "",
        f"ModelSaar is {LICENSE}-licensed open source ({REPO_URL}). Status: {STATUS}; no release has been tagged and no package is published. "
        "It is an OpenAI-compatible HTTP gateway (Chat Completions incl. streaming, /v1/models, /v1/embeddings) that routes each request to one of the "
        "model deployments you run (Ollama first; any OpenAI-compatible server with declared models) using the request's requirements, verified "
        "capability evidence, locality/privacy policy, health and capacity, and records a decision you can inspect. It never downloads models and "
        "never executes a client's tools.",
        "",
        "## Pages",
        "",
    ]
    for path, title, desc in pages:
        lines.append(f"- [{title}]({site_url}{path}): {desc}")
    lines += [
        "",
        "## Source documentation (authoritative)",
        "",
        f"- [README]({REPO_URL}#readme)",
        f"- [docs/]({REPO_URL}/tree/main/docs)",
        f"- [Verification report]({REPO_URL}/blob/main/docs/verification-report.md)",
        "",
    ]
    return "\n".join(lines)
