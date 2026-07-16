# M3C–M3E Stacked Acceptance, Merge-Simulation & Activation-Readiness Audit — Plan

This is the plan for an independent, read-only acceptance audit of the complete
three-PR stack (PR #6 M3C, PR #7 M3D, PR #8 M3E) to determine whether it is safe for a
human stacked merge. The audit **does not** merge, undraft, retarget, tag, activate,
mutate prospective data, evaluate a strategy, access a sealed partition, or append a
ledger. Any remediation lands as append-only commits on
`claude/m3e-review-only-prospective-updates` (never history rewrite).

## §0 Preflight — VERIFIED CLEAN (no HARD STOP)

Captured live at audit start (branch `claude/m3e-review-only-prospective-updates`,
HEAD `334ba28`):

| Check | Expected | Observed |
|---|---|---|
| main | `a7640e3` | `a7640e35c861e72413c9a0154e2ae3af0a075889` ✓ |
| PR #6 head (M3C) | `c508724` | local == remote `c50872431534f199dd0ba78ef86967bcd0b94e4c` ✓ |
| PR #7 head (M3D) | `2e5192b` | local == remote `2e5192bde24094d575f32d0cf1ec16afeaf7d92b` ✓ |
| PR #8 head (M3E) | `334ba28` | local == remote `334ba28a3cac3d4132b53a099370788b4d31c3da` ✓ |
| Ancestry | main→C→D→E | all `--is-ancestor` true; merge-bases = main, C, D exactly ✓ |
| Versions | 0.5.0 / 0.6.0 / 0.7.0 / 0.8.0 | main 0.5.0, C 0.6.0, D 0.7.0, E 0.8.0 ✓ |
| PR states | all open / draft / not merged | #6 clean, #7 clean, #8 unstable→CI success ✓ |
| PR #8 final-head CI | `29447269916` success | completed / success (pull_request) ✓ |
| PR #8 final-head M3E Replay | `29447270099` success | completed / success ✓ |
| Other 5 replays | success | listed success (29447269914/818/923/819/860) |
| Ledgers byte-empty | `e3b0c442…855` | m2b/m3a/m3d ledgers all 0 bytes, sha matches ✓ |
| Cohort | 3 rows through 2026-07-14 | first 2026-07-12, last 2026-07-14, immature, eval_auth false ✓ |
| M3C decision | rejected | `rejected_for_development_gate_promotion` ✓ |
| Research train | exhausted | `exhausted_for_new_candidate_research` ✓ |
| Proposal registry | 0 proposals | 2 records (genesis + audit_noop), 0 proposal ✓ |
| Tags | no v0.6/0.7/0.8 | only `v0.1.0` on remote ✓ |
| Production prospective-update PR | none | open PRs are exactly #6/#7/#8 ✓ |
| Worktree | clean | clean ✓ |
| Baseline gates | green | ruff / ruff-format / mypy(0) / uv-lock / `git diff --check` all green ✓ |
| Replays | reproduce | M2B (3702 rows), fractional M3A/M3B, M3C (financial-exact + verdict), M3D (25-check), M3E (deep) all reproduce ✓ |

## Sections

- **§2–3** Exact stack-delta audit (M0..C, C..D, D..E: no duplication/omission, no
  forbidden file types, stable patch digests) + machine-readable immutable freeze
  table + verifier.
- **§4–5** M3C final scientific acceptance (one candidate, executed once, rejected, no
  gate/holdout access, P1–P7 reproduced) and M3D final data/governance acceptance
  (exhaustion, immature cohort, empty ledgers, no strategy path), replayed under
  3.12/3.13.
- **§6–8** M3E claim-to-code traceability matrix; "ready, not active" semantic audit
  from workflow syntax + live job log; offline-publisher reachability via one coherent
  orchestration seam (disposable-repo E2E incl. idempotency / stale-base / orphan).
- **§9–16** Deep audits: workflow security (25+ evasion fixtures), proposal file-set
  closure, strict parsing, clock/cutoff limitation, two-runner independence, status
  vocabulary exhaustiveness, import/capability, transaction/recovery failure matrix.
- **§17** Three independent read-only auditors (git/history, M3E security/ops,
  scientific firewall); every finding reproduced by me before accept/fix; accepted
  fixes land failing-test-first in separate commits. HARD STOP on Class A/B/D.
- **§18–21** Disposable three-merge `--no-ff` simulation (tree equality + patch
  identity + full gates at simulated ME); future retarget plan; future tag plan (no
  tags created); `docs/M3E_ACTIVATION_READINESS.md`.
- **§22–25** Documentation/PR-body honesty corrections; full final gate battery at the
  audit head; push and wait for PR #8 workflows terminal-green;
  `docs/M3C_M3E_STACK_ACCEPTANCE_AUDIT.md` with the verdict; then STOP.

## Absolute prohibitions (restated)

No merge / undraft / retarget / tag / release / branch-delete / force-push / rebase /
reset / amend / squash; no M3E activation; no write-capable scheduled workflow; no
production proposal; no prospective-data mutation; no strategy execution; no candidate
creation; no M3C re-execution; no gate/holdout access; no ledger append; no financial
or parameter change; no optimization/ML/wallet/exchange-auth/leverage/shorting/trading.

## Required terminal verdict

`ACCEPTED FOR HUMAN STACKED-MERGE REVIEW — M3E REMAINS INACTIVE`, or
`REJECTED — REMEDIATION REQUIRED`, or
`HARD STOP — SEALED/FINANCIAL/PROVENANCE INVARIANT VIOLATED`.
