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
