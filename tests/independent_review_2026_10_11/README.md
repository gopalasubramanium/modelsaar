# Independent review checks (2026-10-11), kept verbatim

These two files are the desired-contract tests written by the independent reviewer against
hardening `80276bb` (review pack `ModelSaar_Independent_Review_2026-10-11`, `evidence/hardening/` and
`evidence/`). They are included **byte-for-byte** (checksums below) so the repository's own suite
re-executes the reviewer's assertions, not a paraphrase of them. At `80276bb` they gave
7 failed / 3 passed (gateway) and 4 failed / 3 passed (evaluator); after the 2026-10-12 correction
pass all 17 pass. Author-written regression tests for the same findings, with recovery and
positive-control cases, live in `tests/test_correction_2026_10_12.py`.

The reviewer identifiers (R1–R8 in `REVIEW.txt`, H01–H05 in `HANDOFF.txt`) are kept separate from the
project's F01–F18 table (`docs/review-2026-10-11-findings.md`), which records which F entries were
reopened by them.
sha256:
    6e5182a79101c53c8ae1ffb81cc4b474deeff236e04d4ab4c25b7c4132962514  test_remaining_contracts.py
    26e7e9f37d9e08b0d5c3bd85b7c38f07e393e6cfe42a7c126be5afbb74978ff8  test_evaluator_remaining_contracts.py
