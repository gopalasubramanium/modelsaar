# Contributing

* Python 3.10+. `pip install -e .[dev]`, then `pytest` (fixture tests only; nothing downloads models).
* Keep the runtime dependency list minimal; propose additions in an issue first.
* Every behaviour claim in docs must be backed by a test (fixture) or marked NOT RUN.
* Adapters: typed, allow-listed translation; never drop semantics silently; confine URLs to the
  configured host.
* Catalogue entries need a primary-source URL and check date; separate weight/base/adapter/code
  licences; never enable `announced_weights`/`api_only`/`unverified` entries by default.
* Decision records and logs must not contain prompt content.
* Run `ruff check src tests` before submitting.
* Commit messages: imperative subject, reasoning in the body. Record material decisions in
  `docs/progress.md`.
