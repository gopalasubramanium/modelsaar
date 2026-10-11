# Installer transcripts — `https://modelsaar.com/install.sh` (site/static/install.sh), 2026-10-11

The installer was executed, not simulated. Because the pinned commit was not yet public on GitHub when
these ran, every run used the testing hook `MODELSAAR_SOURCE=git+file:///…/checkout` with the same
commit the public script pins (source identical to `91f9e6c`: the only later changes are docs/tests). The
fake backend in the Linux runs is the repository's controlled Ollama-protocol fixture on port 11434
(labelled SIMULATED in its `/api/version`); the macOS run used the real GX10 (Ollama 0.32.13, 8 models).
Keys are redacted.

| file | environment | path taken | result |
|---|---|---|---|
| `linux-x86_64-pipx.txt` | Linux x86_64 container, fresh `HOME`, Python 3.13.16, pipx 1.4.3 on PATH, no uv | pipx | installed; `init` discovered 2 deployments; temporary gateway; `modelsaar test` 200 via `auto`; **verification: OK**; exit 0 |
| `linux-x86_64-pipx-repeat.txt` | same `HOME` again, `MODELSAAR_NO_CHECK=1` | pipx (re-install into the existing venv) | "existing configuration kept"; keys unchanged; exit 0 |
| `linux-x86_64-uv.txt` | fresh `HOME`, uv 0.11.32 on PATH | uv (`uv tool install --python 3.12`) | **verification: OK**; exit 0 |
| `linux-x86_64-pip-user.txt` | fresh `HOME`, PATH restricted to python3.13/sh/curl/git/coreutils (no uv, no pipx) | `python3 -m pip install --user` | **verification: OK**; exit 0; `config.yaml` and `keys/api_keys` mode 600 |
| `macos-arm64-uv.txt` | owner's MacBook Air M5, macOS 27.0 arm64, system python3 **3.9.6** (too old — uv fetched CPython 3.12), uv 0.13.0; isolated `UV_TOOL_DIR`/`MODELSAAR_HOME` under `~/.modelsaar-install-test`; backend GX10 via `MODELSAAR_ENDPOINT` | uv | installed; `init` discovered 8 deployments; temporary gateway on 28484; `modelsaar test` 200 from `ollama/qwen3.8:latest` in 1.2 s; **verification: OK**; exit 0; repeat run kept config; files mode 600 |
| `macos-arm64-uv-attempt1-stale-cache.txt` | same Mac, first attempt | uv | **failed**: `ModuleNotFoundError: No module named 'httpcore._backends.mock'` — a corrupt `httpcore` entry in the Mac's existing uv cache (the venv was populated from cache in 7 ms with missing files). Re-running with `UV_NO_CACHE=1` succeeded (next row). Not an installer defect, but a real-world failure mode; the troubleshooting doc now mentions `uv cache clean`. |

Also exercised on Linux (not kept as files): an explicitly unreachable backend (`MODELSAAR_ENDPOINT=http://127.0.0.1:1`)
→ config written, verification reports "the gateway answered but no deployment could serve the request"
with the 422 body; an occupied gateway port held by a non-ModelSaar process → the installer stops with
"port 8484 is in use by something that is not a ModelSaar gateway" and the two remedies.

Not executed: WSL2 (follows the Linux path; untested), native Windows (unsupported), the public URL
`https://modelsaar.com/install.sh` itself (the domain was not yet connected when these ran — re-run
`curl -fsSL https://modelsaar.com/install.sh | sh` on both platforms after deployment and add the
transcripts here).
