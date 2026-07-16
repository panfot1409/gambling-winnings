# M3E Bug / Deviation Log

Every deviation from `docs/M3E_PLAN.md` and every defect found and fixed during
Milestone 3E, recorded honestly. "Any deviation is a defect to be corrected, not a
silent change."

## D1 — Version freeze of the completed M3D milestone

Bumping the running package to 0.8.0 would have broken the M3D replay, because M3D
stamped the *live* package version. Fix (commit 2): freeze `M3D_PACKAGE_VERSION` to the
literal `"0.7.0"` (replay-neutral — every M3D artifact still rebuilds byte-for-byte),
exactly as every prior completed milestone pins its own version.

## D2 — Reuse of the Coinbase inclusive-`start`/`end` convention

The update plan reuses the reviewed M3D window schema, where the Coinbase request
`end` param is the last *completed* bucket open (`window_end − 1 day`) and the parse
window is the half-open `[window_start, window_end)`. Carried over unmodified; the
forming candle is always excluded.

## D3 — Standing workflow corrected to a read-only probe (accepted no-artifact-upload invariant)

`docs/M3E_PLAN.md` §4 described the standing `m3e-prospective-update.yml` as running the
two isolated runner jobs and **uploading** the assembled proposal as a workflow
artifact. That conflicts with an **accepted M2B security invariant**
(`tests/test_workflow_security.py::test_no_artifact_upload`): *no* workflow at HEAD may
upload an artifact (a potential exfiltration channel). Rather than weaken an accepted
security control, the standing workflow was corrected to a strictly **read-only
update-due probe** (verify the accepted base + compute the completed-day cutoff; no
fetch, no artifact upload, no push, no PR). The full acquisition → two-runner-attestation
→ assemble → draft-PR automation is the offline `eth_research.m3e` machinery, proven
end-to-end by the disposable-repo rehearsal, and is activated only by a separate
human-reviewed commit. This is the honest reconciliation of the plan's intent with the
repository's established security posture, and it strengthens rather than weakens the
"READY, NOT ACTIVE" guarantee. The live audit-mode evidence
(`research/m3e/AUDIT_MODE_EVIDENCE.md`) and its wording were updated to match.

## D4 — Strict workflow scan false-positives on comment text

The M3E workflow-security scan (`_no_unsafe_workflow`) matches raw text, so the literal
tokens `--force` and `pull_request_target` written in explanatory workflow *comments*
tripped it. Fix: reworded the comments (no forbidden literal), so the scan reflects the
executable content only.

## D5 — mypy strict test annotations

The repository runs mypy `strict = true` over `tests`. The M3E test suite was brought up
to that bar with full parameter/return type annotations (no logic change); CI's strict
type-check step is green.

## D6 — Screening-guard robustness (three independent red teams, commit 23)

Three independent read-only red teams confirmed HEAD is clean (no live prohibition
violated) and found the *screening* guards were substring/marker heuristics weaker
than the absolute guarantees the docs asserted. Fixed in code with tests, all
documented in `docs/M3E_FINDINGS.md`: the workflow-safety scan now parses permission
values (rejects `write-all` / omitted block / quoted-or-spaced `contents: write`),
matches secrets in index/`inherit` forms, refuses artifact uploads, catches
`-f`/`+refspec` force-push and every auto-merge spelling, and matches a scheme-less
Coinbase host; the proposal directory is restricted to an exact expected file set;
the import firewall resolves relative imports and rejects network/wallet modules; and
`assert_draft_only` pins the PR base to the accepted cohort branch. Two residuals are
accepted and documented (the completed-day cutoff is not re-asserted against a trusted
clock offline; two-runner isolation is a reproducibility control, not external
authenticity) — both mitigated by the mandatory draft-PR human-review gate.

## D7 — Version freeze at milestone completion (commit 23)

`M3E_PACKAGE_VERSION` tracked the live package version, so a later milestone bumping
`eth_research.__version__` would have broken byte-exact replay of the committed M3E
artifacts. Fix: pin the literal `"0.8.0"` (byte-identical to what is already stamped,
so replay stays byte-exact), exactly as M3D pins `"0.7.0"`. Replay-neutral.

## Inherent limitation (by design, not a defect)

Like M3D, the prospective cohort is self-anchoring: future-only candle bytes are bound to
committed receipts with no external value oracle. The two-runner canonical-equality
attestation is an offline integrity/reproducibility control, not a cryptographic
authenticity attestation against an outside source; the two genuinely-isolated runners
(distinct identities) are the strongest offline authenticity signal, and their recorded
identities are the external-audit hook. Documented, not hidden.

## Independent stacked-acceptance audit — §17 findings (post-development)

An independent three-PR stacked-acceptance audit (see
`docs/M3C_M3E_STACK_ACCEPTANCE_AUDIT.md`) commissioned three read-only auditors
(A: git/history/merge; B: M3E security/operations; C: scientific firewall/provenance).
Every finding was reproduced against the actual source before acceptance. **No auditor
found an active Class A (financial/scientific), Class B (accepted-branch write), or
Class D (sealed access) breach** — every workflow at HEAD is `permissions: contents:
read` and pushes/merges nothing, the three ledgers are byte-empty, and the M3C
candidate stays rejected. The findings below are **defense-in-depth hardening** of the
review-only controls, exploitable only by a hypothetical *future* hostile edit and
already backstopped by branch protection, the repository default-read token, and
mandatory human review. Each fix is append-only on
`claude/m3e-review-only-prospective-updates` and evaluates no strategy, mutates no
accepted data, and appends no ledger.

### A1 — workflow scanner missed a flow-style write / decoy permissions comment (fixed, commit 92e722c + 15e1197)
The line-anchored block scanner did not see a YAML *flow* mapping
`permissions: { contents: write }` (any inner spacing/tab), and the presence gate
`"permissions:" in text` was satisfied by a lone `# permissions:` decoy comment. Fix:
added `_FLOW_WRITE_PERM_RE`; the presence gate now requires a real, non-comment
`^\s*permissions:` line; and (commit 92e722c) a `&anchor write` scalar is rejected. All
9 real workflows still pass; >20 evasion fixtures now fail closed.

### A2 — write-verb denylist missed plain push / merge / undraft / retarget (fixed, commit 15e1197)
`_FORCE_PUSH_RE`/`_AUTO_MERGE_RE` caught only force-push and `--auto`. A plain
`git push` to the default or an accepted milestone branch, an immediate `gh pr merge`,
`gh pr ready` (undraft), `gh pr edit --base` (retarget), and the REST `pulls/N/merge`
all slipped past. Fix: `_PROTECTED_PUSH_RE` + `_MERGE_UNDRAFT_RETARGET_RE`.

### A3 — runner directory was not a closed file-set (fixed, commit d8a13f5)
`load_and_verify_runner` re-derived only the declared files and ignored any extra, so an
innocuously named `runner_a/aux.json` (no strategy marker) rode in unverified at
verify time. Fix: the boundary now enforces the exact
{`update_plan.json`, `acquisition_receipt.json`, declared raws} set and rejects any
other entry, subdirectory, or symlink.

### A4 — proposals root was not a closed set (fixed, commit d8a13f5)
The PR-check filtered to manifest-bearing directories, so a manifest-less sibling (or a
stray top-level file) under `research/m3e/proposals/` was silently skipped by the
35-check verifier. Fix: `verify_proposals_root` requires every child to be a
manifest-bearing proposal directory; the PR-check workflow now calls it first.

### A5 — orchestration seam committed an arbitrary pathspec (fixed, commit d8a13f5)
`prepare_update_proposal` staged whatever `proposal_relpath` named. Fix: it now asserts
the pathspec resolves to exactly the proposal directory before the single git effect.

### Accepted residuals (documented, not fixed — each fully backstopped)
- **Cutoff not re-asserted at verify time (auditor B finding 5).** `verify_update_proposal`
  is offline and clockless; a plan with a future `completed_day_exclusive_end` is not
  re-checked against a trusted clock. Triply backstopped: a complete future/forming
  candle cannot be fetched (row-count mismatch → fail); the immature 365-day floor
  authorizes no evaluation regardless; and the proposal is a draft under mandatory human
  review. The optional future hardening is: have the activated PR-check pass its own
  runner clock and re-assert `end <= floor_to_utc_midnight(now)`.
- **M3D import scanner ignores relative imports (auditor C F1).** `verify_m3d_program.
  _scan_prohibited_imports` only records absolute imports. Latent: no M3D (or M3E)
  module uses any relative import, M3D is frozen (research train exhausted), and a
  resulting artifact would still trip the value-scanning `_scan_forbidden_fields`. Left
  in frozen M3D code to preserve stack separation; recommended for a future M3D-scoped
  change (mirror the M3E `_module_targets` resolver).
- **Status guards scan keys, not string values (auditor C F2).** Backstopped: every
  status input is a byte-rebuilt artifact whose values are hashes/ISO-dates/counts/enums,
  the governance flags are byte-pinned to `False`, and the whole-program
  `_scan_forbidden_fields` already scans values. A naive value-scan would false-positive
  on the legitimate bound M3C fact `rejected_for_development_gate_promotion`, so it is
  documented rather than changed.
- **Exhaustion guard is a policy assertion, not a live interceptor (auditor C F3).**
  Sound by design — M3D contains no candidate-generation runtime to intercept; no fix
  required.
- **Two-runner isolation** is an offline reproducibility/integrity control, not external
  authenticity, and **a regex workflow scanner cannot fully parse arbitrary YAML or
  recurse a remote reusable workflow** — both irreducible residuals carried by branch
  protection + human review.
