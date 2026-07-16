# Milestone 3E — Terminal Independent Acceptance Audit

**Scope.** Milestone 3E is a review-only prospective-update automation: it lets the
accepted M3D prospective ETH-USD daily cohort grow **only** through
independently-verified, append-only update **proposals** that are always opened as
**draft** pull requests for human review — never auto-applied, never auto-merged,
never pushed to an accepted branch. This document is the terminal, read-only
acceptance audit of the delivered facility on branch
`claude/m3e-review-only-prospective-updates` (stacked on the accepted M3D branch
`claude/m3d-prospective-evidence-governance`).

**Method.** Every claim below was re-derived from committed bytes: the accepted base
and the append-only registry rebuild byte-for-byte (`replay --deep`), the isolated
package firewall + workflow-safety scan + 35-check proposal verifier all run and
cannot silently skip, and the three sealed ledgers are asserted byte-empty before and
after. Three independent read-only red teams (security/workflow posture,
data-integrity/attestation, governance/firewall) audited the facility from disjoint
angles; their findings and resolution are in `docs/M3E_FINDINGS.md`.

## 1. What M3E does (the review-only lifecycle)

Trusted schedule / manual trigger → **verify the accepted base** (rebuild manifest +
segment chain byte-for-byte, fingerprint `bb6dd392…`, three byte-empty ledgers, M3C
still rejected, full M3D program intact) → derive the **first missing completed day**
→ mechanically compute the **completed-day cutoff** (the forming candle is always
excluded; a NO-OP when nothing new is due) → fetch the same window on **two isolated
runners** → strictly validate both offline → **require byte-identical canonical
content** (fingerprint + exact rows, distinct runner identities; any disagreement is a
HARD STOP) → assemble an **append-only** proposal offline (transactional write +
readback + rollback) → verify the old→new transition (accepted prefix byte-identical,
one-interval seam, `proposed = old + new`) → create a **new bot branch** → open a
**DRAFT** PR whose base is pinned to the accepted cohort branch → CI replays the
proposed cohort and re-runs the 35-check verifier → **HUMAN REVIEW** → **no
auto-merge**.

The standing `m3e-prospective-update.yml` at HEAD is a strictly **read-only
"update-due probe"** (verify base + compute cutoff + report DUE/NO-OP; no fetch, no
assemble, no artifact upload, no push, no PR), honouring the accepted
no-artifact-upload security invariant. The full automation above is the **offline**
`eth_research.m3e` machinery, proven end-to-end by the disposable-repo rehearsal
(`tests/test_m3e_publisher_e2e.py`) and activated only by a separate, human-reviewed
step. **READY, NOT ACTIVE.**

## 2. Prohibition matrix — M3E never does any of these (verified)

| M3E must never… | How it is prevented |
|---|---|
| Evaluate a strategy / create a candidate / compute a signal, weight, position, fill, fee, turnover, return, P&L, metric, ranking, or promotion | Isolated `m3e` package with an AST import allow-list (relative-resolved) that admits only strategy-free data/governance utilities; the data-only status guard rejects numeric evaluation keys; governance flags pinned all-false with an `any(bool)` guard |
| Move money | No such code or import exists anywhere under `eth_research.m3e` |
| Mutate the accepted branch / auto-merge / retarget | Review policy pinned by exact-dict equality (draft-only / human-required / no-auto-merge / no-retarget / no-accepted-mutation); `assert_draft_only` pins the base to the accepted cohort branch and fails closed |
| Append to any evaluation ledger / access a sealed partition | The three sealed ledgers are asserted byte-empty (exact `sha256 == e3b0c442…855`) before and after every replay; symlink/missing-file safe |
| Re-execute M3A/M3B/M3C | No import of any experiment/executor/decision module; `verify_m3d_program` runs unchanged and green |
| Use a secret / PAT / wallet, add an exchange SDK or network client | No secret/token/network import in `src/eth_research/m3e`; the workflow scanner rejects secrets (dotted/index/inherit) and network egress; the import firewall rejects network/wallet prefixes |
| Use `pull_request_target` / push to main or accepted branches / grant `contents: write` | The hardened `_no_unsafe_workflow` scanner rejects write permissions (incl. `write-all` / omitted block), the PR-target event, force-push (`--force`/`-f`/`+refspec`), artifact uploads, and every auto-merge spelling; all nine workflows at HEAD are `contents: read` |

## 3. Red-team outcome

All three teams concluded **HEAD is clean** — no live prohibition is violated. The
findings were screening-guard robustness gaps (substring/marker heuristics weaker than
the docs' absolute claims) and one replay-hygiene item; none was an exploitable bypass,
because the lifecycle bottoms out at a mandatory draft-PR human review with no
auto-merge. The genuine defects were fixed in commit 23 with tests (hardened workflow
scanner + a 14-case evasion matrix, closed proposal file-set, relative+network import
scan, base-branch pinning, comprehensive status vocabulary, version freeze). Two
residuals are accepted and documented (offline cutoff-vs-clock; single-author
two-runner isolation), both mitigated by the human-review gate. Full detail:
`docs/M3E_FINDINGS.md`.

## 4. Exact honest final state

- Accepted prospective cohort: **3 rows**, last open `2026-07-14`, **immature**,
  `evaluation_authorized = false`, fingerprint `bb6dd392…`.
- Update automation: **ready, not active** — the standing workflow is a read-only
  probe; at the audit date it correctly no-ops (nothing new is due until the current
  day completes).
- Proposals recorded in the append-only registry: **0** (genesis + one `audit_noop`).
- `strategy_evaluated = false`, `performance_metrics_computed = false`,
  `promotion_decision_exists = false`, `money_moved = false`.
- Prospective-evaluation ledger: **0 bytes**. Development-gate and final-holdout
  ledgers: **0 bytes**.
- Development package version frozen at the literal **0.8.0**; every committed M3E
  artifact rebuilds byte-for-byte; `m3e-replay` green on 3.12.3 + 3.12 + 3.13.

## 5. Gates

Full local gate green: `ruff check` + `ruff format --check` + `mypy src tests
examples` (strict, 0 errors) + `uv lock --check` + `pytest` (full suite). Branch CI
green: `CI`, `M3E Replay`, and the M2B/M3A/M3B/M3C/M3D replays. The M3E honest-state CI
gate asserts the exact state in §4.

## Verdict

**MILESTONE 3E COMPLETE — REVIEW-ONLY UPDATE AUTOMATION READY, NOT ACTIVE, NO STRATEGY
EVALUATED.**
