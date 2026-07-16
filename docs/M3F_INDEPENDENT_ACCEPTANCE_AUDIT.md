# M3F — independent acceptance audit (Milestone 4A §3)

Before Milestone 4A branched, the accepted M3F verification/recovery layer (branch
`claude/m3f-independent-verification-recovery`, head `56360aa`) was independently
re-audited rather than trusting its own terminal report. Three independent auditors
attacked it with a reproduce-before-reporting discipline; every alleged finding was
reproduced personally in a disposable clone, classified, and — for the genuine Class
B/C defects — fixed append-only on the M3F branch, failing-test-first, with proof that
no accepted artifact changed.

## Scope of the audit

Freeze-catalog closure, artifact enumeration, independent-verifier independence, strict
JSON behaviour, honest-state derivation, dependency/workflow inventories, recovery-capsule
determinism, safe extraction, disposable recovery drill, anti-orphan behaviour, source-tree
and git-object binding, path safety, Unicode/case handling, immutable-artifact neutrality,
strategy/backtest and ledger/proposal non-reachability, no-network behaviour, and the CI
contract.

## Auditors

- **Auditor A — common-mode integrity**: forgeries, parser differentials, relabeling,
  missing roots, cycles, orphan insertion, duplicate keys, non-finite numbers, symlink
  substitution, commit relabeling, deep internally-consistent tampering.
- **Auditor B — recovery & distribution**: archive/extraction, partial publication,
  rollback, dirty trees, shallow clones, missing objects, Unicode paths, case collisions,
  dependency inventory, workflow supply-chain.
- **Auditor C — scientific & governance firewall**: reaching strategy evaluation, backtest
  engines, sealed partitions, ledger mutation, M3E activation, proposal publishing, or the
  network through any public M3F entry point.

## Classification

- **A** scientific/financial-integrity · **B** trust-boundary/authorization · **C**
  robustness/compatibility/docs/defense-in-depth · **D** sealed access, immutable-artifact
  drift, activation, prospective mutation, or ledger append.

**No Class A or Class D defect was confirmed.** No hard-stop condition (spec §37) exists:
the accepted immutable artifacts are byte-unchanged, the three sealed ledgers are byte-empty,
M3C is rejected, M3D is 3/365 and evaluation-unauthorized, M3E is inactive with zero
proposals. Auditor C's firewall probe confirmed the `eth_research.m3f` import closure is
exactly `eth_research._json` + the standard library — no strategy/eval/ledger/network module,
no third party — and that `register.py` (the only real-FS writer) is reachable by no verifier
entry point.

## Findings and fixes (all Class C defense-in-depth; A1/A3 initially proposed by the
auditors as Class D/B, re-classified on reproduction — see below)

| ID | Finding (reproduced) | Class | Fix |
|----|----------------------|-------|-----|
| A1 | A stray file committed under `research/m3f/` was neither catalogued nor flagged (the anti-orphan enumeration blanket-excluded the whole layer prefix). | C | Anti-orphan now scopes positively to the accepted-stack roots (m2b–m3e) and separately asserts the `research/m3f/` set contains **no file outside** the known layer allowlist (`08b_m3f_layer_allowlist`). |
| A2 | The independent verifier accepted exponent-overflow non-finite numbers (`1e999`→inf) that the package rejects — a parser differential defeating the two-code-path guarantee. | C | Independent `_loads` now passes `parse_float=_checked_float`, rejecting non-finite numbers exactly as the package does. |
| A3 | A coordinated forgery (tamper an accepted artifact **and** rewrite its catalog entry, capsule manifest, and drill) passed all verifiers: accepted evidence was bound only to the mutable committed catalog, never to immutable history. | B→C | The accepted M2B–M3E evidence is now anchored to the **source-pinned** accepted-main commit (`EXPECTED_ACCEPTED_MAIN_SHA`, `14_accepted_stack_anchored`) via `git diff`, an anchor outside every mutable committed file and independent of the catalog's own `accepted_main_sha` field. Applies wherever the pinned commit is reachable (real repo / full clone / CI); not-applicable in synthetic contexts where checks 12/13 govern. |
| A4 | The independent verifier followed a symlinked catalogued file escaping the repo (the package rejects it). | C | Independent `_read_bytes` now refuses a symlink or a path resolving outside the repo root. |
| A5 | Catalog per-artifact `milestone`/`role` labels were only vocab-checked, so an artifact could be relabelled (e.g. m2b evidence forged as m3f). | C | `verify_catalog` recomputes both labels from the path and compares (`05_milestone_matches_path`, `06_role_matches_path`). |
| B1 | `git -c <key>=<value> push`/`git -c … tag` and `gh pr --repo … merge` evaded the push/merge/tag detectors; subdomained market hosts (`data.binance.com`) evaded the host detector. | C | The push/tag detectors tolerate interposed `-c` config tokens (quoted values included) and `gh pr` flags; `_MARKET_HOST` matches any subdomain. Read-only steps are still not flagged. |
| B2 | The dependency inventory accepted a `registry` package carrying neither a wheel nor an sdist hash, contradicting the hash-pinned claim. | C | A `registry` source with no wheel and no sdist hash is now rejected as non-reproducible. (No real locked package is affected — all carry a hash.) |
| C1 | The runtime import-closure backstop test flagged forbidden modules only by a substring blocklist. | C | The backstop is now structural: any loaded `eth_research.*` outside `{eth_research, eth_research._json, eth_research.m3f.*}` is a breach. |
| — | `bundle.build_manifest` read capsule files without a symlink/escape guard (a dangling tracked symlink crashed the audit with an uncaught `OSError`). | C | Capsule reads go through `safe_repo_path`; a bad path fails closed as a `CapsuleError`. |

Re-classification note: the auditors proposed A1 as Class D and A3 as Class B/D. On
reproduction neither is an *actual* immutable-artifact drift, sealed access, activation,
or ledger event — no existing accepted artifact changed and no sealed/governance state
moved; both are completeness/anchor gaps in the *verifier's* robustness (the layer already
self-describes as "operational tamper-evidence, not cryptographic signature"). They are
therefore Class C defense-in-depth, fixed here rather than triggering a hard stop. As a
bonus, the A1 accepted-stack scoping is also what lets a later governed layer
(`research/m4a/`) stack on top without tripping the frozen M3F anti-orphan or capsule.

## Accepted-artifact neutrality (proof)

All fixes are **verify-time-only** and change no committed research artifact. Regenerating
each M3F registration artifact from the patched code is byte-identical to the committed
bytes: `freeze_catalog.json`, `honest_state.json`, `dependency_inventory.json`,
`workflow_inventory.json`, and `recovery_capsule_manifest.json` all reproduce exactly (the
new checks only affect adversarial inputs not present in the real repo). The recovery
capsule digest is unchanged (`d59b2592…`, 118 files); the three sealed ledgers remain
byte-empty (`e3b0c44…`); the accepted M2B–M3E tree still matches `accepted_main`
`7b75a981…` byte-for-byte (`git diff --quiet 7b75a981… -- research/m2b … research/m3e` →
clean).

## Verification after the fixes

`python -m eth_research.m3f.audit --deep` (ok), `tools/m3f_independent_verify.py` (ok),
`m3f.oracle --check` (ok), `m3f.recovery --deep` (ok), `m3f.replay --check` (ok, M3E
inactive / 0 proposals); the full M3F test suite plus the new
`tests/test_m3f_acceptance_hardening.py` regressions (each written to fail pre-fix); ruff,
ruff-format, mypy, and the complete pytest battery — all green.

## Verdict

The M3F verification/recovery layer is independently accepted. No Class A/D defect exists;
the reproduced Class C defense-in-depth gaps are closed append-only on the M3F branch with
proof of accepted-artifact neutrality. The corrected M3F head is the base for Milestone 4A.
