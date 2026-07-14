# Milestone 3A — merge-readiness audit (read-only handoff)

The read-only audit of the merge-readiness milestone that followed run-003's
terminal completion. It makes the existing M3A history, artifacts, tests,
documentation, and PR #4 truthful, standing, and independently verifiable. It
authorizes **no** development-gate or final-holdout access, promotes no
candidate, mutates no immutable artifact, and creates no tag.

## 0. Checkpoint semantics (honest by construction)

This document distinguishes four commit roles and never claims to embed its own
final commit SHA:

- **Starting checkpoint** — the branch head this milestone began from:
  `dcf65f259a482d14648853494f4ad5eb40cfc58a`.
- **Implementation / artifact-correction checkpoint** — the commit at which all
  code and test changes had landed (erratum layer, standing E2E, red-team
  fixes): `98b59b9` (`Harden the archive/registry/file verifiers`).
- **Docs / PR-only closure commit** — the commit that added/updated this and the
  other Markdown records. It is a documentation commit; a Markdown file cannot
  honestly contain its own commit hash, so it is not embedded here.
- **Externally-reported branch head** — the actual pushed HEAD is reported in the
  session handoff message and on PR #4 after the push, not inside a tracked file.

## 1. Sealed invariants (held throughout)

- Both access ledgers are **byte-empty** (`e3b0c442…`):
  `research/m3a/development_gate_access.jsonl`,
  `research/m2b/test_evaluations.jsonl`.
- The append-only experiment registry is unchanged: **9 lines**, six-line v1
  prefix `7920d9fd…e9af67`. No experiment event was appended in this milestone.
- The immutable run-003 archive is byte-identical:
  `development_report.md` `d6e92076…`, `development_results.json` `5f6377b6…`,
  `return_evidence.json` `b593a03c…`, `artifact_manifest.json` `1ea0ade8…`.
- run-003 financials remain bit-identical to run-002 (60 fold cells + 12/12/12).

## 2. K1–K4 known discrepancies — resolved

| id | discrepancy | resolution |
| --- | --- | --- |
| K1 | PR #4 body stale (run-002 terminal; "every interval straddles zero"; "no statistics defects") | PR #4 body rewritten to the true terminal state (Phase 7); repository truth asserted by `tests/test_m3a_merge_readiness_defects.py::TestK1PrBodyIsStale` |
| K2 | immutable run-003 report Section 5 says "every fold-aware bootstrap interval … straddles zero", but the three cash primary intervals exclude zero | append-only machine-verified erratum (the immutable bytes are preserved) |
| K3 | the successful E2E lifecycle skipped once run-003 was completed | made standing (runtime-gated skip only) + a dedicated authoritative-CI step that fails if it is skipped |
| K4 | terminal audit named a stale "Final HEAD" | honest four-role checkpoint semantics (§0); the prior audit is bannered as superseded |

## 3. The append-only report erratum (K2)

- Module `src/eth_research/artifact_errata.py`; index
  `research/m3a/artifact_errata.jsonl`; documents under `research/m3a/errata/`.
- Erratum id `m3a-run003-report-zero-inclusion-v1`
  (JSON `f7a027cc…`, Markdown `35f2242d…`, genesis chain).
- The corrected statement: the primary fold-stratified intervals for `sma_20_50`
  and `donchian_55_20` straddle zero; the three **cash primary** intervals are
  strictly below zero and exclude zero on the underperformance side; the
  hierarchical sensitivity intervals straddle zero for every strategy; the
  original report's rounded `-0.00%` display does not make zero part of the
  interval; **no financial value changed**.
- Affected cells (full precision, re-derived from the committed results):

  | cell | ci_lower | ci_upper | contains 0 |
  | --- | --- | --- | --- |
  | cash / base | `-0.005063937422795938` | `-1.220168774754618e-05` | no |
  | cash / stressed | `-0.005063904789164851` | `-1.1503664325654388e-05` | no |
  | cash / severe | `-0.005062567013459328` | `-1.0358783751154005e-05` | no |

- `verify_artifact_errata` proves, from the committed bytes alone: the target
  report/results still hash to the completed registry event; the erroneous
  statement is present verbatim; the affected cells are exactly the
  zero-excluding intervals; the cash primaries exclude zero while every other
  primary and every sensitivity interval contain it; no financial scalar
  changed; the rendered Markdown equals the model; both ledgers are byte-empty.
  It runs in `develop_m3a --check`, `verify_m3a_registry.py`, M3A Replay CI, and
  the hygiene suite. 38 adversarial cases in `tests/test_artifact_errata.py`.

## 4. Standing end-to-end lifecycle (K3)

`tests/test_m3a_orchestrator_e2e.py` now restores a disposable clone's
`research/m3a` subtree to the recorded execution-source commit E
(`b27f5d9`, asserted an ancestor of the clone HEAD) — six-line v1 prefix, run-002
aliases, no run-003 archive, no errata — then registers and runs run-003 with the
current production package, driving `registered → started → publish → readback →
completed → replay → single-use refusal`. The skip is runtime-gated only (off the
frozen CPython 3.12.3 runtime the orchestrator fail-closes). A dedicated
`authoritative-runtime` CI step runs the exact node and fails if pytest reports it
skipped/deselected/xfailed. Locally: **2 passed, ~38 s**, both ledgers byte-empty.

## 5. Independent red team (three read-only auditors) + primary reproduction

**No class-D (results-affecting) defect was found.** run-003 financials are
byte-reproducible. Findings, all reproduced by the primary agent and fixed
forward:

| id | class | finding | resolution |
| --- | --- | --- | --- |
| 4.1-1 | A + C | the frozen-M2B-dossier verification (run on every `load_development_dataset`) re-runs the engine over the 740 development-gate-dated rows (the M2 validation segment); the absolute firewall prose overstated the guarantee | firewall docstring scoped to the M3A walk-forward + the benign M2B re-derivation disclosed; a regression test pins that it reaches the gate end but **never** the holdout and leaves both ledgers byte-empty. Not results-affecting; user-authorized fix-forward |
| F-4.7-1 | C | `verify_experiment_archive` trusted the index and never enumerated the on-disk tree, so a stray file or a rogue experiment directory passed | the verifier now enumerates `research/m3a/experiments/` and rejects any stray file, rogue directory, symlink, or undeclared file |
| F-4.7-2 | C | the six-line v1 prefix immutability lived only in a unit test | the CI verifier byte-pins the prefix, catching a monotonic-preserving v1 edit the append-chain does not bind |
| A6-1 | C | file-backed models accepted a de-newlined file (not a serialize fixed point) | the file-load boundary requires the canonical trailing newline; `from_json_bytes` stays a lenient parser and every artifact is additionally SHA-256-bound |
| A6-2 | accepted | `require_finite_float` accepts an int for a float, re-serialized as a float | documented, intended behavior; every committed file already uses the float form and is SHA-256-bound |

Other dimensions — accounting (4.4), walk-forward protocol (4.2), strategy
causality (4.3), bootstrap/statistics v1+v2 (4.5), publication & **calculation-free
recovery** (4.8, dynamically confirmed), replay & fresh clones (4.9), CI &
supply chain (4.10) — all passed on independent reproduction.

## 6. Reproduction commands

```
uv run --no-sync pytest
uv run --no-sync python -m eth_research.develop_m3a --repo-root . --check
uv run --no-sync python .github/scripts/verify_m3a_registry.py
uv run --no-sync python -c "from eth_research.artifact_errata import verify_artifact_errata; print(verify_artifact_errata('.'))"
```

`develop_m3a --check` prints `reproducible (v2 …, 1 verified bound erratum)`;
`verify_m3a_registry.py` prints `verified (v2): … 1 bound erratum verified` with
both ledgers byte-empty; the standing E2E runs on the authoritative runtime.

## 7. Remaining limitations (unchanged, honest)

Five folds; in-sample research-train diagnostics (not live, not test); a single
venue / instrument / daily frequency; operational, hash-bound, **not
cryptographic** sealing; unsigned commits; `v0.4.0` release-tag debt (no tag is
created here); `v0.3.0` annotated-tag push remains blocked by org egress policy.

## 8. Absolute stop

No development-gate evaluation; no final-holdout evaluation; no signals on either
sealed partition; no ledger append; no run-003 rerun; no run-004; no immutable
artifact mutated; no strategy/cost/fold/seed/convention change; no optimization
or ML; no live/paper trading, auth, wallet, signing, leverage, shorting, or
fractional exposure; no history rewrite; **no merge; no undraft; no tag; no
branch delete.** PR #4 stays open and draft for independent human acceptance.
