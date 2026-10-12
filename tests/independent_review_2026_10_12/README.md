# Independent correction-review checks (2026-10-12), kept verbatim

The three files are the bounded closure tests from the independent review of the 2026-10-12
correction archive (`ModelSaar_Correction_Review_2026-10-12`, `evidence/hardening/` and `evidence/`),
included byte-for-byte (checksums below). At hardening `5cb7443` they gave 6 failed / 6 passed
(R2-A failed residency observation, R2-B phantom residency after a refused connection, R4-C error
after the terminal marker, R1-C evaluator probes bypassing admission, R7-C routed checkpoints ignoring
changed alternatives); after the alpha closure pass all 12 pass. `test_probe_caller_closure.py` writes
two small JSON observation files next to itself when run; they are ignored by git.

sha256:
    8849e762f097a2210cfac03b924d25d3013f49eaa30abdf1f14c268760f41e9d  test_closure_edges.py
    0c0f57f3c625ada5492b8425aabb9ea535688dd9a8546d1eeb625bedf16dc4ac  test_probe_caller_closure.py
    7a0e7cae2ea62c3eea2bb11fea6ac4cb3d486d43b0374d649a586ed9d476f903  test_checkpoint_closure.py
