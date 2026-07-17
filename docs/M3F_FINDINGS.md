# Milestone 3F — red-team findings

Three independent read-team auditors reviewed the M3F verification/recovery layer,
each with a distinct scope and a mandatory *reproduce-before-reporting* discipline:

- **Auditor A** — the verifier graph + common-mode analysis (`audit`, `catalog`,
  `honest_state`, `state_machine`, `validation`, the independent tool).
- **Auditor B** — recovery, supply-chain, and registration (`bundle`, `recovery`,
  `register`, the two inventories, `m3f-replay.yml`).
- **Auditor C** — semantic oracles, the isolation firewall, and governance logic.

Every finding below was reproduced, then fixed failing-test-first; the reproductions
live in `tests/test_m3f_redteam.py`, `tests/test_m3f_independence.py`,
`tests/test_m3f_mutation.py`, and `tests/test_m3f_oracle.py`. No high-severity break
was found; all fixes are fail-closed hardening of the verification layer itself.

The auditors independently confirmed the core guarantees held under reproduction:
the oracle math, the `count_created_proposals` fail-closed semantics (the earlier F1
class), the recovery-drill soundness, byte-determinism, the CI read-only posture,
`validation.py` type-strictness, and the path-safety refusals.

## Findings and fixes

| ID | Sev | Summary | Fix (commit) |
|---|---|---|---|
| **A1 / B2 / C3** | High | All three workflow write-detectors (inventory, honest_state, independent tool) missed a `contents:` grant with extra spaces, a tab, a trailing YAML comment, or a `&anchor write` scalar — a fail-open of the `standing_workflow_can_write_contents` forever-invariant. | Mirror the hardened M3E regexes; one shared `workflow_grants_write`; the independent tool keeps its own stdlib copy. |
| **A2 / B1** | Med | The supply-chain verb scanner missed REST/GraphQL ref-mutation (`git/refs`, `git/tags`) and auto-merge (`enablePullRequestAutoMerge`, `--auto`). | Extend `_MERGE_VERBS`. |
| **B3** | Low-Med | `bash <(curl …)` process substitution bypassed the piped-installer guard. | Extend `_PIPED_INSTALLER`. |
| **B6** | Low | Market-host detection was Coinbase-only. | Broaden `_MARKET_HOST`; document the residual (arbitrary egress). |
| **C4** | Low | `honest_state` coerced `evaluation_authorized` with `bool()` while the independent tool was strict — a verifier divergence on falsy non-bools. | Read it with strict `require_bool`. |
| **B5** | Low | `register._publish_atomically` overwrote pre-existing artifacts in place before a later write could fail, so a failed re-registration corrupted prior state despite the docstring. | Temp-file + `os.replace` + snapshot rollback. |
| **B4** | Low | Lock-source classification matched substrings, so a git source with "registry" in its URL was mislabeled `registry` and slipped the reproducible-source gate. | Classify by the inline-table key; fail closed outside {registry, editable}. |
| **C2** | Med | `oracle_m3e_cohort_window` raised an *uncaught* `TypeError` on a naive/aware timestamp mix, crashing the collector and masking later oracles. | `_parse_utc` requires UTC; `run_oracles` fails closed on any exception. |
| **A3** | Med/Low | `verify_catalog` never validated the catalog's own git-provenance fields (tree SHA, source fingerprint, version) — they were forgeable undetected. | Recompute them from git and compare; the replay CI fetches full history. |
| **C1** | High | The import-firewall test walked only absolute imports, so a relative `from ..evaluation import` (and dynamic `importlib`/`__import__`) was invisible — the guard did not guard. | Resolve relative imports + flag dynamic ones; add a subprocess import-closure backstop. |
| **C5** | Low | The allowlisted `data.provenance` / `m3d.validation` transitively pulled pandas + the data pipeline, so "imports no third-party" was transitively false. | Inline hashing + canonical JSON (stdlib, byte-identical) so the package imports only `_json` + stdlib; allowlist shrinks to `{_json}`. |
| **A4** | Low | The independent verifier silently skipped its catalog/honest-state cross-checks when those files were deleted from an otherwise-registered repo. | Detect registration; require the catalog + honest state to exist when registered. |

## Verified clean (honest negatives)

- **Path safety** — absolute, `..`, backslash, `//`, `./`, non-NFC alias, and
  symlink-component escapes are all refused (`normalize_relpath`/`safe_repo_path`).
- **Whole-graph early return** — only check 01 returns early, and only after
  recording a failure; missing committed artifacts are failures, not passes.
- **Governance invariants** — sealed-ledger emptiness is hash-checked against real
  bytes in four independent places; `count_created_proposals` is strict-parse and
  fail-closed and agrees with the independent tool's own counter.
- **Recovery-drill soundness** — a clean reconstruction trips no detector, so each
  failure drill genuinely requires its corruption; `verify_materialized` re-derives
  the capsule digest and rejects a partial reconstruction.
- **Determinism** — every committed artifact rebuilds byte-identically across
  double-runs and (in CI) across CPython 3.12 and 3.13.
- **Independence** — `tools/m3f_independent_verify.py` imports only the standard
  library; the shared blind spot in A1 was duplicated *logic*, not a shared import.

## Residual risks (carried into the threat model)

A regex scan cannot fully parse arbitrary YAML or a remote reusable workflow; the
market-host list names known hosts rather than proving no egress; and a coordinated
rewrite of an artifact *and* its recorded hash in one accepted commit defeats hash
binding. Each is stated in `docs/M3F_THREAT_MODEL.md` and backstopped by the
`contents: read` default token, branch protection, the independent verifier's
separate recomputation, and mandatory human review.
