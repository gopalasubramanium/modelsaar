# Release process

1. `python -m pytest` green locally; CI (`ci.yml`) green on `main` (lint, tests on 3.10/3.12/3.13,
   pip-audit of runtime dependencies, gitleaks secret scan, local Docker image build + smoke).
2. Update `CHANGELOG.md`; bump `version` in `pyproject.toml` and `src/modelsaar/__init__.py`
   (the release workflow refuses a tag that does not match the package version).
3. Re-run `modelsaar eval --mode simulated` and, where hardware exists, `--mode live`; attach the JSON
   reports and update `docs/verification-report.md` (NOT RUN items stay labelled).
4. Re-check client documentation dates in `docs/clients/*.md`.
5. One-time setup for publishing (owner action):
   * PyPI: create the project name by configuring a **Trusted Publisher** on pypi.org for
     `gopalasubramanium/modelsaar`, workflow `release.yml`, environment `pypi`; create the `pypi`
     environment in the GitHub repository settings (optionally with required reviewers). Do a dry run
     against TestPyPI first if desired (same workflow with the TestPyPI repository URL).
   * GHCR: nothing to configure; `release.yml` pushes `ghcr.io/gopalasubramanium/modelsaar:<tag>`
     with the workflow's `GITHUB_TOKEN` (`packages: write`). Make the package public in the GitHub
     package settings after the first push.
6. `git tag vX.Y.Z && git push origin vX.Y.Z` → `release.yml` builds, tests, publishes to PyPI and GHCR.
7. Update `docs/installation.md` to mention `pip install modelsaar` and the image once they exist.

Publishing to PyPI/GHCR and creating the public repository are owner decisions; the repository was
made public on 2026-10-11 with the owner's authorization.

## GitHub-only pre-releases (`vX.Y.Z-rc.N`)

A release candidate is a **GitHub prerelease** and nothing else: a tag of the form `vX.Y.Z-rc.N` on a
commit of `main` whose CI is green, plus a GitHub release marked *pre-release* whose notes say what is
being tested and what the evidence does and does not show. It is for testers who install from GitHub.

* **It does not publish anything.** `release.yml` runs only for tags that match `v[0-9]+.[0-9]+.[0-9]+`
  exactly, and every job in it is additionally guarded with `!contains(github.ref_name, '-')`; a tag
  with a `-rc.N` (or any other `-`) suffix therefore never builds, never reaches PyPI and never pushes
  an image. The package version in `pyproject.toml` / `src/modelsaar/__init__.py` is **not** bumped for
  a candidate (`modelsaar --version` keeps printing the base version, `0.1.0` for `v0.1.0-rc.1`); the
  tag is the only marker. Steps 2–7 above are for the stable tag that may follow.
* **The installer pin does not move.** `site/static/install.sh` keeps pinning the stable candidate
  commit; a release candidate is tried from a source install at the tag, in its own directory and with
  its own `MODELSAAR_HOME`, side by side with a stable installation (README, "Release candidate").
* **How it is created** (owner or owner-authorised): on the exact `main` commit, after its push CI is
  green — `git tag -a vX.Y.Z-rc.N <commit>`, push that one tag (never force), confirm that no
  `release` workflow run was triggered, `gh release create vX.Y.Z-rc.N --verify-tag --prerelease
  --notes-file …`. Tags are never moved or deleted; a superseded candidate is followed by `-rc.N+1`.
* **Candidates so far:** `v0.1.0-rc.1` (2026-10-28) — decision-model support (`POST /v1/decisions`,
  classifier `mode: decision`), opt-in and experimental; evidence: fixture tests in CI and one bounded
  live smoke test of three requests (`docs/live-runs/2026-10-28-decision-preview-smoke/`); no quality
  or routing-benefit claim. `v0.1.0-rc.2` (2026-10-29) — rc.1 plus the `continuation` capability probe
  (`modelsaar probe <id> --which continuation`; protocol acceptance, not semantic continuity) and the
  corrected `422` remedy; fixture-tested (294 tests); the probe was run live exactly once from this tag on
  2026-10-29 against `ollama/qwen3.8:latest` (Ollama 0.40.5) and reported `supported` — protocol acceptance of
  `reasoning_content` in the history, not semantic continuity (`docs/live-runs/2026-10-29-rc2-continuation-probe/`).
  rc.1 remains available unchanged.

## Readiness for the first versioned alpha release (checked 2026-10-14)

A list against the steps above. Tagging, PyPI and GHCR publication remain separate owner decisions;
`release.yml` is not triggered by anything in this list.

| step | state | what remains |
|---|---|---|
| 1. CI green on `main` | **ready** — every merged PR (#1–#6) ran lint, tests on 3.10/3.12/3.13, pip-audit, gitleaks, the container build and the installer job (real systemd user unit, x86_64 + arm64) green; the last merge is `56cea65` | re-check the run on the exact commit that will be tagged |
| 2. CHANGELOG and version | **partly** — `CHANGELOG.md` has five dated "Unreleased" entries since 0.1.0; `pyproject.toml` and `src/modelsaar/__init__.py` still say `0.1.0`, the version already used by the untagged 2026-10-11 revision | choose `0.1.1` (or `0.2.0`, the installer and the `session_id`/`cache_prompt` contract are user-visible changes), roll the "Unreleased" entries into that heading, bump both files in one commit |
| 3. Evaluation reports | **partly** — `--mode simulated` runs in CI; the only live report is the 2026-10-11 run at `0f8af84` with scorer `2026.10.11-2`; no live run at the current revision | either release with the report labelled "earlier revision, earlier scorer" (as the site does today) or run the Measured Routing Quality plan first; the release notes must say which |
| 4. Client documentation dates | **partly** — `docs/clients/*.md` are dated 2026-10-11/13; `docs/clients/odysseus.md` records the owner-reported status (2026-10-14) | re-read each client page's date line before tagging |
| 5. One-time publishing setup | **not done** — no Trusted Publisher is configured on pypi.org for `release.yml` / environment `pypi`, and the `pypi` GitHub environment does not exist; GHCR needs nothing before the first push | owner: configure the Trusted Publisher and the `pypi` environment (optionally with a required reviewer); a TestPyPI dry run is optional |
| 6. Tag | **not done** by design | `git tag vX.Y.Z && git push origin vX.Y.Z` after 1–5 |
| 7. Installation docs | **not applicable until published** — `docs/installation.md` and the website describe the pinned-commit installer; `pip install modelsaar` and the image are mentioned nowhere | add them only after the first successful publication |

Also before tagging: the public installer's pin (`site/static/install.sh`, `REF=`) stays on a commit
that exists on `origin`; a release tag does not move it — decide separately whether the installer should
pin the tagged commit. The GX10 and the owner's service are not part of the release process.
