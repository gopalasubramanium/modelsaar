# Release process

1. `python -m pytest` green locally; CI green (lint, tests, pip-audit, secret scan).
2. Update `CHANGELOG.md`; bump `version` in `pyproject.toml` and `src/modelsaar/__init__.py`.
3. Re-run `modelsaar eval --mode simulated` and, where hardware exists, `--mode live --probe`; attach
   the JSON reports to the release notes and update `docs/verification-report.md` with NOT RUN items.
4. Re-check client documentation dates in `docs/clients/*.md`; re-verify any key that changed.
5. `git tag vX.Y.Z` and push.
6. Publishing to PyPI or a container registry, and creating a public repository, are **separate
   authorization steps** owned by the project owner; the repository does not claim either exists.
