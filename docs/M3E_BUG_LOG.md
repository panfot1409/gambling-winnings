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

## Inherent limitation (by design, not a defect)

Like M3D, the prospective cohort is self-anchoring: future-only candle bytes are bound to
committed receipts with no external value oracle. The two-runner canonical-equality
attestation is an offline integrity/reproducibility control, not a cryptographic
authenticity attestation against an outside source; the two genuinely-isolated runners
(distinct identities) are the strongest offline authenticity signal, and their recorded
identities are the external-audit hook. Documented, not hidden.
