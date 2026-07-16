# Milestone 3E — Review-Only Prospective Update Protocol

This document describes how the accepted prospective ETH-USD daily cohort is allowed
to grow under Milestone 3E: only through independently-verified, append-only update
**proposals** that are always opened as **draft** pull requests for **human** review,
never auto-applied and never auto-merged. M3E evaluates no strategy, declares no
candidate, computes no performance quantity, and moves no money.

## Lifecycle

1. **Trigger (trusted).** A schedule (`m3e-prospective-update.yml`, Mondays 02:17 UTC)
   or a manual dispatch — never untrusted PR content.
2. **Verify the accepted base.** Re-derive the accepted M3D cohort from committed bytes
   (`AcceptedProspectiveBase`): the manifest and segment chain rebuild byte-for-byte,
   the canonical fingerprint is `bb6dd392…`, the three ledgers are byte-empty, the M3C
   candidate is still rejected, and the cohort is immature / unauthorized.
3. **Compute the completed-day cutoff.** From an explicit `as_of` (never a wall clock
   in the library), derive the first missing open (`accepted_last_open + 1 day`) and the
   completed-day cutoff (`floor_to_utc_midnight(as_of)`; the forming candle is excluded).
   If nothing new is due, it is a **NO-OP** and the facility proposes nothing.
4. **Two-runner acquisition (isolated).** When a new completed day is due, two isolated
   runners independently fetch the same window over a hardened, read-only `curl` boundary
   (endpoint read from the committed plan) and validate it **offline** (strict schema,
   half-open window bounds, completed-day, contiguity, receipt SHA-256 binding).
5. **Canonical-equality attestation.** The proposal proceeds only if the two runners
   produce **byte-identical canonical content** (fingerprint + exact rows) and are
   genuinely isolated (distinct runner identities). Any disagreement is a HARD STOP.
6. **Append-only transition.** The proposed cohort is exactly `old_rows + new_rows`,
   beginning with the accepted rows unchanged; the seam is one-interval contiguous; the
   old fingerprint equals the accepted base.
7. **Assemble + verify offline.** The proposal bundle (comparison + transition +
   manifest) is assembled transactionally and passes the 35-check whole-proposal
   verifier (`verify_update_proposal`).
8. **Propose as a DRAFT PR.** A new, uniquely-named bot branch
   (`bot/m3e-prospective-update/<window>-<key>`) carries the proposal; a **draft** PR is
   opened onto the accepted cohort branch. CI (`m3e-update-pr-check.yml`) replays the
   complete proposed cohort and re-runs the 35-check verifier.
9. **Human review — no automatic merge.** A human decides. Nothing is auto-merged,
   undrafted, retargeted, or applied to the accepted branch.

## Standing posture at the final HEAD: READY, NOT ACTIVE

At the final HEAD the standing workflow `m3e-prospective-update.yml` is a strictly
**read-only update-due probe** (steps 1–3 only): it verifies the accepted base and
reports whether an update is due. It does **not** fetch, assemble, upload an artifact,
push, or open a PR — consistent with the repository's accepted no-artifact-upload and
no-write security invariants (`tests/test_workflow_security.py`). Steps 4–8 are the
offline `eth_research.m3e` machinery (`acquire_runner`, `runner_boundary`, `comparison`,
`transition`, `assembly`, `publisher`), proven end-to-end by the disposable-repo
rehearsal (`tests/test_m3e_publisher_e2e.py`).

**Activation** of the full live automation — the single privileged step that fetches
public candles across two isolated runner jobs and opens a draft review PR — requires a
separate, human-reviewed commit on the default branch that adds the write/artifact-
capable jobs and, at that time, is reviewed against the security invariants. It is
intentionally not wired to run unattended. The live audit-mode rehearsal (run
`29441490761`, 2026-07-15) exercised the base-verification + cutoff logic and correctly
produced a no-op (`research/m3e/AUDIT_MODE_EVIDENCE.md`).

## What M3E never does

M3E never evaluates a strategy, creates a candidate, computes a signal/weight/position/
fill/fee/turnover/return/P&L/metric/ranking/promotion decision, moves money, mutates an
accepted branch, auto-merges, accesses a sealed partition, appends an evaluation ledger,
or re-executes M3A/M3B/M3C. The final M3E code is research-only and holds no key.
