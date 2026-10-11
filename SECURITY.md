# Security policy

ModelSaar is a local gateway that handles API keys and forwards prompts to inference backends.

**Reporting.** Please report vulnerabilities privately to the maintainer (see `pyproject.toml`
authors) rather than in public issues. Include version, configuration shape (no keys), and
reproduction steps. Expect an acknowledgement within 7 days.

**Scope.** Authentication bypass, admin/inference privilege confusion, backend destination
confusion (SSRF), prompt/secret leakage into logs or decision records, failover that violates hard
constraints, and anything that lets request content control routing policy.

**Defaults** are documented in `docs/privacy.md`. Dependency auditing (`pip-audit`) and secret
scanning run in CI; workflow permissions are read-only and CI contains no credentials or private
prompts.
