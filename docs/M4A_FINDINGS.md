# M4A red-team findings and disposition

Three independent auditors reviewed the Milestone 4A release candidate strictly read-only:

- **Auditor A** — public API + numerical integrity.
- **Auditor B** — packaging + supply-chain.
- **Auditor C** — CLI + security + publication.

Every finding was reproduced with a concrete exploit before disposition. **No Class D finding
was reported** (no auditor touched an accepted artifact, sealed ledger, or the network to inform
research): A and B explicitly recorded "Class D — nothing", and C stayed read-only (its F3
reproduction hit the collision guard *before* any write; the working tree stayed clean). No
finding was an accepted-financial-artifact change. Therefore no HARD STOP was triggered, and the
Class B/C findings were fixed failing-test-first. All fixes are confined to the M4A surface, the
scanner, and the tests.

## Disposition table

| ID | Auditor | Class | Summary | Disposition |
| --- | --- | --- | --- | --- |
| F1 | C | B | symlinked `dataset.file.path` reads outside the config dir | **Fixed** — realpath confinement |
| F2 | C | B | output escapes via a symlinked parent | **Fixed** — publisher + orchestrate confinement |
| F3 | C | B | CLI `--output` bypasses the governed-path guard | **Fixed** — `_reject_governed_output` |
| B1 | B | B | scanner/test admit a non-`.py` data file in the package | **Fixed** — pure-Python allowlist |
| A1 | A | B | `run_id` does not bind the context content | **Fixed** — `context_fingerprint` + full-spec id |
| A3 | A | B | `dataset_manifest_sha256` unbound / unverified | **Fixed** — folded into `run_id` |
| A2 | A | B* | custom strategy bound by name only | **Documented** — honest v1 boundary |
| F4 | C | C | `IsADirectoryError` leaks past the taxonomy | **Fixed** — non-regular-file collision |
| F7 | C | C | verify commands use the base error / exit 1 | **Fixed** — taxonomy exit codes |
| F8 | B/C | C | `doctor` offline check hardcoded `True` | **Fixed** — real in-process check |
| F9 | C | C | config guard is case-sensitive | **Fixed** — casefolded |
| F10 | C | C | config read twice (validate-then-bind TOCTOU) | **Fixed** — single read |
| A-C1 | A | C | dataset interval leaks a bare `ValueError` | **Fixed** — wrapped as `DatasetError` |
| A-C2 | A | C | `StrategySpec` not an object-level fixed point | **Fixed** — sorted in `__post_init__` |
| A-C3 | A | C | `CausalityError` defined but never raised | **Documented** — reserved taxonomy leaf |
| A-C4 | A | C | metrics computed outside the engine `try` | **Fixed** — moved inside `try` |
| F5 | C | C | firewall scan too narrow | **Fixed** — broadened to the offline runtime |
| F6 | C | C | firewall matcher spelling-specific | **Fixed** — alias/`from`-import resolution |
| F11 | C | C | published files are mode `0o600` | **Intentional** — see below |

\* A2 is classed B by the auditor but is "partly documented"; it is a boundary of the identity
model, not a code defect, and is dispositioned as a documentation-honesty fix.

Fixed items are in [M4A_BUG_LOG.md](M4A_BUG_LOG.md). The two documented items and the one
intentional non-change are explained here.

## Documented, not coded

### A2 — a custom strategy is bound in the receipt by name only
A custom `Strategy` passed through the Python API is trusted caller code; its behaviour cannot be
captured deterministically, so the receipt records `custom:<name>` and the `run_id` binds it by
name only. This is now stated explicitly in the receipt module docstring,
[V1_LIMITATIONS.md](V1_LIMITATIONS.md), and [RESULT_AND_RECEIPT_SCHEMAS.md](RESULT_AND_RECEIPT_SCHEMAS.md).
The CLI and config path never accept a custom strategy, so their receipts always bind a fully
specified built-in. Fingerprinting arbitrary caller code is out of scope for v1.

### A-C3 — `CausalityError` is reserved
`CausalityError` is defined and exported so a caller can catch it, but the accepted engines
enforce causality *structurally* (a decision at bar *t* can only see data through *t*), so it is
not raised on the built-in paths. Its docstring now states it is reserved for an engine-detected
look-ahead violation and part of the stable taxonomy.

## Intentional, not a defect

### F11 — published bundle files are mode `0o600`
The auditor flagged the published files inheriting `mkstemp`'s `0o600` (owner-only) mode. For a
privacy-preserving research tool this is **more** restrictive than a umask-respecting `0o644` and
is the safer default; it is kept intentionally. A consumer who wants group/other-readable output
can relax the mode after publication.

## Verified clean (auditors found nothing to fix)

The auditors positively verified — not merely skipped — the following:

- **Scientific / financial integrity (Auditor A, Class A): nothing.** The public metrics are
  scalar-identical to the accepted engines by construction (`api/backtest.py` relabels and coerces
  but reimplements no formula); no input produced a public metric that differed numerically from
  the accepted engine.
- **Canonical-JSON strictness.** Duplicate keys, non-finite numbers, exponent overflow, non-UTF-8,
  string→number coercion, and `bool`-as-`int` are all rejected; the trailing newline and sorted-key
  canonical form are enforced; results and receipts round-trip byte-identically.
- **Transactional publisher.** Forced mid-publish failures restore the previous bytes exactly, the
  completeness marker is written last, every file is read back and byte-verified, and no partial /
  temporary / backup residue remains.
- **Reproducibility.** The wheel and sdist are byte-identical across repeated builds (different
  umask, `TMPDIR`, and build path), and the sdist rebuilds the canonical wheel.
- **Consumer isolation.** The installed wheel runs out-of-tree with only `numpy` / `pandas` /
  `pyarrow` (plus pandas' own deps); re-running is byte-identical; re-publishing over an existing
  bundle is refused with exit 9.
- **No live-trading surface.** No network client, credential, wallet, order routing, leverage,
  shorting, margin, or derivatives anywhere in the shipped runtime; the Coinbase endpoint appears
  only as an inert provenance label.
- **Governance state untouched.** The three sealed ledgers stayed byte-empty and the accepted
  M2B–M3F governance graph still verifies after every change.
