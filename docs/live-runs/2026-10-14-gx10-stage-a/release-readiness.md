# Stage A — first-release readiness snapshot (read from `docs/release.md` at `f18b2f1`; nothing tagged or published)

| release step | status | evidence / what remains |
|---|---|---|
| 1. CI green on `main` | **READY** | every merged PR (#1–#7) ran lint, tests 3.10/3.12/3.13, pip-audit, gitleaks, container build and the installer job (real systemd user unit, x86_64 + arm64) green; post-merge `ci` 38547881022 and `site` 38547881138 on `f18b2f1` succeeded |
| 2. CHANGELOG + version bump | **READY WITH OWNER ACTION** | six dated "Unreleased" entries since 0.1.0; `pyproject.toml` and `src/modelsaar/__init__.py` still `0.1.0` (the version the untagged 2026-10-11 revision already carries). Owner chooses `0.1.1` or `0.2.0`, rolls the entries under it, bumps both files in one commit |
| 3. Evaluation reports | **NOT READY** (for a release that quotes current numbers) / **NOT REQUIRED FOR STAGE B** | the only live report is 2026-10-11 at `0f8af84`, scorer `2026.10.11-2`, Ollama 0.32.13; the runtime is now Ollama 0.40.3 and the scorer `2026.10.12-3`. Either release with the report labelled "earlier revision, scorer and runtime" (as the site does) or complete Stage B first |
| 4. Client documentation dates | **READY WITH OWNER ACTION** | pages dated 2026-10-11/13; `docs/clients/odysseus.md` carries the owner-reported 2026-10-14 status; re-read dates before tagging |
| 5. One-time publishing setup (PyPI Trusted Publisher, `pypi` GitHub environment; GHCR needs nothing before the first push) | **NOT READY** — owner action | no Trusted Publisher configured for `release.yml`/environment `pypi`; the `pypi` environment does not exist |
| 6. Tag `vX.Y.Z` → `release.yml` | **NOT READY** by design | separate owner decision; not triggered |
| 7. Installation docs mention `pip install modelsaar` / image | **NOT REQUIRED FOR STAGE B**; after first publication | |
| Installer pin | **READY** (unchanged) | `site/static/install.sh` pins `cf56cdd3416d8c853b64111b9b40211e5b126031`, which the GX10 runs; a release tag does not move it |

Stage B does not depend on any release step; a release does not depend on Stage B unless the owner
wants current evaluation numbers in the release notes.
