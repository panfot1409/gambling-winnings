# Milestone 3F — Independent Verification, Hermetic Recovery & Supply-Chain Closure

**Infrastructure-only. Verification-only and recovery-only. No new research, no sealed-partition
access, no strategy evaluation.** M3F is a read-only layer over the accepted M2B–M3E stack. Target
package version **0.9.0**. Branch `claude/m3f-independent-verification-recovery`, based on accepted
main `7b75a9813d0658d8d30f8337f7a419d1bf7338f7` (tree `3bc5abb7`).

## 1. Motivation

The accepted stack (M2B dataset, M3A development research, M3B fractional research, M3C rejected
candidate, M3D immature prospective cohort, M3E ready-not-active update automation) is already
individually verified. M3F adds a **single repository-wide verification surface** and a
**deterministic recovery capsule**, answering with independent, reproducible evidence:

1. A fresh clone reconstructs every derived artifact from committed source evidence.
2. A verifier **independent of the production package** detects corruption, omission, duplication,
   path substitution, graph relabeling, and common-mode parser failure.
3. The repository's exact honest state derives from committed bytes — no strategy, no wall clock.
4. A private recovery capsule rebuilds byte-for-byte across supported Python runtimes.
5. A damaged workspace restores in a disposable clone without mutating accepted artifacts.
6. Dependency / workflow / source-code supply-chain boundaries are enumerated and fail closed.
7. All prior invariants check through one strict, anti-orphan surface.
8. Every verifier refuses tampered states before any strategy/backtest/publisher/ledger/network
   path can be reached.

## 2. Architecture

Isolated package `src/eth_research/m3f/` (AST import allow-list; no strategy/engine/metric/network
import; no ledger writer; no publisher):

| module | role |
|---|---|
| `validation.py` | strict JSON/JSONL parsing (dup-key/NaN/Inf/bool-as-int/trailing-data rejection), safe-path normalization, canonical-bytes contract, sha256 helpers |
| `catalog.py` | `FreezeCatalog` model + deterministic generator + strict verifier for `research/m3f/freeze_catalog.json` |
| `graph.py` | artifact graph edges + closure/anti-orphan enumeration |
| `honest_state.py` | derive `honest_state.json` + render `HONEST_STATE.md` from committed bytes |
| `state_machine.py` | read-only governance state machine (derive+verify current state; never transition) |
| `dependency_inventory.py` | derive+verify `dependency_inventory.json` from `uv.lock`/`pyproject.toml` |
| `workflow_inventory.py` | derive+verify `workflow_inventory.json`; YAML-aware permission/action scanner |
| `oracle.py` | independent read-only semantic oracles (M2B–M3E scalar/governance identities) |
| `bundle.py` | deterministic private recovery-capsule builder/verifier (git-object bytes) |
| `recovery.py` | disposable-clone recovery drill + failure drills |
| `audit.py` | `verify_repository_freeze()` — the whole-graph production verifier |
| `replay.py` | byte-exact replay entrypoint (`--check`) |
| `cli.py` | thin argparse wrappers |

Independent verifier **outside** the package: `tools/m3f_independent_verify.py` — stdlib-only, no
`eth_research`, no third-party import, read-only `git` allowlist, its own SHA-256/JSON/path logic.

## 3. Schemas (canonical: UTF-8, sorted-key JSON, 2-space indent, trailing newline, finite only)

- `research/m3f/freeze_catalog.json` — repository-wide catalog: `schema_version`, `catalog_algorithm`,
  `accepted_main_sha`, `accepted_main_tree_sha`, `package_version`, `source_freeze_sha`,
  `source_tree_fingerprint`, `canonical_json_contract`, `milestones`, `artifacts[]`, `ledgers`,
  `registries`, `workflows`, `graph_edges[]`, `expected_repository_state`, `excluded_paths`,
  `bundle_contract`, `verification_contract`. Each artifact binds path/sha256/byte_length/mode/role/
  milestone/schema/classification/commit/predecessor/market-bytes/capsule-permit/semantic-verifier.
- `research/m3f/honest_state.json` + `HONEST_STATE.md` (rendered, byte-reproducible).
- `research/m3f/dependency_inventory.json` (from lock/pyproject).
- `research/m3f/workflow_inventory.json` (all `.yml`/`.yaml`).
- `research/m3f/recovery_capsule_manifest.json` + `RECOVERY_CAPSULE_NOTICE.md`.
- `research/m3f/recovery_drill.json` (deterministic; no execution time).

Generators refuse overwrite by default and support a no-write `--check` mode. Hundreds of hashes are
generated deterministically from verified inputs, then the resulting **bytes** are strictly verified.

## 4. Threat-model summary

Adversary can mutate any committed byte, add/remove files, relabel artifacts/commits, substitute
paths (traversal/absolute/symlink/Unicode/case), truncate/duplicate JSONL, smuggle bool-as-int, forge
multi-file coordinated states, evade YAML permission scanning, introduce a market-URL/write-path in a
workflow, or present a shallow/dirty clone. M3F must fail closed on all of these through **two
independent verifiers** (package + stdlib) to defeat common-mode parser bugs, and must structurally
prevent reaching any strategy/backtest/ledger/publisher/network path. Full model in
`docs/M3F_THREAT_MODEL.md`.

## 5. Test plan (synthetic fixtures unless verifying accepted committed hashes)

Catalog model/generation/verification/canonical-bytes; graph closure + anti-orphan; independent
verifier + its import-graph purity; honest-state model; state machine (valid + impossible combos);
dependency + workflow inventory + evasion matrix (≥20 fixtures); source-scope firewall; semantic
oracles (M2B–M3E); capsule creation/byte-reproducibility/safe-extraction/corruption; recovery drill +
failure drills; transactional publication + rollback; mutation matrix (≥40 families × verifiers);
shallow-clone/dirty-tree/symlink/hardlink/path-normalization/Unicode-case; strict JSON/JSONL; git
binding; runtime compat; no-strategy/backtest/ledger/proposal/network reachability; all accepted
replays; terminal hygiene.

## 6. Recovery drill (disposable directories only)

Fresh full clone → shallow clone (explicit insufficient-history handling) → locked sync → drop ignored
derived data → reconstruct M2B → replay M2B–M3E → verify catalog + honest state → build capsule twice
(compare bytes) → extract into empty temp → independent capsule verify → reconstruct from capsule →
verify all accepted hashes → ledgers empty → 0 proposals → no writes outside disposable clone → source
tracked-tree digest unchanged → temp removed. Plus the enumerated failure drills, each failing for its
**intended** reason. Runbook in `docs/M3F_RECOVERY_RUNBOOK.md`.

## 7. Commit plan (small, append-only, never amend)

1. `docs/M3F_PLAN.md` (this).
2. version 0.9.0 (pyproject/`__init__`/uv.lock/drift test) + prove accepted replays unmutated.
3. `m3f.validation` strict parsing + tests.
4. `m3f.catalog` model + generator + verifier + tests.
5. `m3f.graph` + anti-orphan + tests.
6. `m3f.honest_state` + renderer + tests.
7. `m3f.state_machine` + tests.
8. `m3f.dependency_inventory` + tests.
9. `m3f.workflow_inventory` + evasion matrix.
10. source-scope firewall extension + tests.
11. `m3f.oracle` semantic checks + tests.
12. `m3f.bundle` capsule + `m3f.recovery` drill + transactional publication + tests.
13. `m3f.audit` (`verify_repository_freeze`) + `m3f.replay` + `m3f.cli`.
14. `tools/m3f_independent_verify.py` + purity test.
15. mutation matrix.
16. **E** source freeze (all gates green).
17. **R** catalog registration (generate committed artifacts; E..R diff = research/docs only).
18. `.github/workflows/m3f-replay.yml` (read-only) + push, CI green.
19. **P** recovery proof (`recovery_drill.json`).
20. three red-team audits + fixes.
21. **Q** terminal docs + findings + bug log + README.
22. draft PR #9.

## 8. CI plan

`.github/workflows/m3f-replay.yml`, `permissions: contents: read`, every `uses:` full-SHA-pinned, no
secrets/market-host/artifact-upload/schedule-mutation. Jobs: **authoritative-recovery** (3.12.3:
package verifier + independent verifier + honest-state + inventories + all accepted replays + capsule
built twice + drill check + ledgers/0-proposals/clean-tree before&after); **compat-recovery** matrix
(3.12, 3.13: byte-reproducibility + capsule digest compare + independent verifier); **independent-verifier**
(isolated `python -I`, package not required). All jobs must be terminal-success; skipped/cancelled/
neutral/queued ≠ success.

## 9. Hard stops (preserve read-only evidence; never "repair" evidence of sealed access)

Accepted main ≠ expected SHA before branching; a sealed ledger nonempty/changed; a strategy evaluated
on gate/holdout; a new strategy evaluation; an accepted immutable artifact changed without an accepted
erratum; M3C verdict changed; M3D data changed or falsely mature; M3E active; a production proposal
exists/created; a write-capable workflow; prospective data fetched; a Class D defect; recovery would
require mutating accepted evidence; the only way forward is force-push/history-rewrite/protection-
bypass/secret/tag-workaround; private raw-data scope unmaintainable without upload; a verifier passes
only by weakening an accepted financial/governance/sealing invariant. Ordinary bugs/CI/type/format/
slow-test/shallow-clone/deterministic-archive/doc issues are **not** hard stops — fix and continue.

## 10. Exclusions (not authorized)

Merge/undraft; tag/Release/tag-retry; branch delete; history rewrite; repo-settings/secret changes;
M3E activation; write-capable standing workflow; prospective fetch; production proposal; cohort
mutation; strategy evaluation; gate/holdout evaluation; ledger append; candidate promotion; strategy
add/tune; M4/unrelated milestone; exchange-auth/wallets/signing/order-routing/leverage/borrowing/
shorting/derivatives/optimization/grid/Bayesian/ML.

## 11. Terminal acceptance criteria

Package verifier + independent stdlib verifier agree on the accepted state and on every mutation;
recovery drill passes in disposable clones; capsule byte-reproducible on 3.12.3/3.12/3.13; honest
state derived from bytes (`evaluation_authorized=false`, `m3e_active=false`, `production_proposal_count=0`,
3 ledgers empty); dependency+workflow inventories fail closed; three red teams complete with all
findings fixed or honestly documented; full local battery + branch CI + M3F Replay green on final
HEAD; accepted artifacts byte-unchanged vs baseline; M3C rejected, M3D 3/365 immature, M3E inactive;
draft PR #9 open (not merged, not tagged). Baseline: main `7b75a98`, 2172 passed / 2 skipped.
