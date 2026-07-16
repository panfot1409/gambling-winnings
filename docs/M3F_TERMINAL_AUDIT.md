# Milestone 3F — terminal audit

A read-only self-audit of the terminal M3F state. It asserts, from committed bytes,
that the verification/recovery layer is complete and green and that the accepted
stack's forever-invariants hold. It performs no evaluation, activation, promotion,
or fetch.

## Freeze sequence

| Phase | Commit | What |
|---|---|---|
| E (source freeze) | `b7d24e8` | all M3F source frozen (package, independent tool, CI, docs) |
| R (registration) | `e6f5307` | freeze catalog, honest state (JSON + MD), dependency + workflow inventories, recovery capsule manifest + notice, research/m3f README |
| P (drill record) | `6868df3` | recovery drill record |
| (test robustness) | `5eca328` | clone-based tests robust to a registered source repo (test-only) |

The catalog binds `source_freeze_sha = b7d24e8` and `accepted_main_sha = 7b75a98`
(the accepted M2B–M3E merge on main), and its git-provenance fields are recomputed
at verify time.

## Verification (all green on the registered repository)

| Verifier | Result |
|---|---|
| `python -m eth_research.m3f.audit --deep` (whole graph) | **ok**, 10/10 checks, 0 failures |
| `python3 tools/m3f_independent_verify.py` (stdlib-only) | **ok**, 8/8 checks, 0 failures |
| `python -m eth_research.m3f.oracle --check` (semantic oracles) | **ok** |
| `python -m eth_research.m3f.recovery --deep` (recovery drill) | **ok** — reconstruction + all 5 failure drills detected |
| `python -m eth_research.m3f.replay --check` | **ok**, M3E inactive, 0 proposals |

Full local gate at the registered HEAD: ruff, ruff format, `mypy src tests examples`
(+ the independent tool), `uv lock --check`, `git diff --check`, and the complete
pytest suite — all green (baseline 2172 passed / 2 skipped, plus the M3F additions).

## Forever-invariants (asserted fail-closed at derivation)

| Invariant | Value |
|---|---|
| M3C candidate verdict | `rejected_for_development_gate_promotion` |
| M3D cohort | 3 / 365 rows, `immature` |
| M3D evaluation authorized | `false` |
| M3E active | `false` |
| M3E production proposals | `0` |
| Standing workflow can write contents | `false` |
| Sealed access ledgers (m2b/m3a/m3d) | byte-empty (`e3b0c44…7852b855`) |

## Freeze artifacts

- Freeze catalog: **118** accepted artifacts catalogued (the M3F layer excluded); the
  three sealed ledgers recorded byte-empty; git-provenance recomputed.
- Recovery capsule manifest: **118** files, `capsule_digest = d59b2592…`; no
  sealed-partition contents, no secret.
- Recovery drill: reconstruction reproduces byte-for-byte and re-derives the honest
  state; all five failure drills detected.
- Isolation: the `eth_research.m3f` package imports only `eth_research._json` + the
  standard library (no third-party, no strategy/eval logic — enforced statically and
  by a runtime import closure); the independent tool is standard-library-only.

## Red team

Three independent auditors reviewed the layer with a reproduce-first discipline. No
high-severity break; fifteen findings (A1–A4, B1–B6, C1–C5) were fixed
failing-test-first (`docs/M3F_FINDINGS.md`).

## Not done (hard stops honored)

This milestone did **not**: merge or undraft the PR; create, publish, or retry any
tag or release; delete any branch; change repository settings, secrets, or policy;
activate M3E; add a write-capable standing workflow; fetch prospective data; generate
a production M3E proposal; mutate the M3D cohort; evaluate any strategy, gate, or
holdout; append any ledger; promote a candidate; or start M4. The three known-debt
tags (`v0.6.0`/`v0.7.0`/`v0.8.0`) remain unpublished and were not retried.

## Verdict

The Milestone 3F verification and recovery layer is complete, internally consistent,
and green under the package verifier, the genuinely-independent standard-library
verifier, the semantic oracles, and the disaster-recovery drill. The accepted M2B–M3E
stack is intact and M3E remains inactive. **Ready for human review as a draft PR;
M3E remains inactive and nothing is activated.**
