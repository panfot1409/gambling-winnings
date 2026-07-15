# Milestone 3E — Threat Model (review-only update automation)

M3E is a **zero-trust** data-PR facility. Its job is to let the accepted prospective
cohort grow *only* through independently-verified, append-only proposals reviewed by a
human as draft PRs. This document lists the threats it defends against and how.

## Trust boundary

- **Trusted:** the committed accepted base at the M3D HEAD (manifest, segment chain,
  receipts, raw bytes, byte-empty ledgers), the committed M3E code + plan, and the
  trusted trigger (schedule / manual dispatch on the repository's own branch).
- **Untrusted:** any bytes returned from the network; any bytes on a proposal branch or
  in a proposal PR; anything a second party could influence.

## Threats and defenses

| # | Threat | Defense |
|---|--------|---------|
| T1 | A drifted / tampered accepted base is used as the anchor | `AcceptedProspectiveBase` re-derives the manifest + segment chain byte-for-byte, checks the fingerprint `bb6dd392…`, the three byte-empty ledgers, and the rejected M3C verdict; `verify_update_proposal` also runs the full M3D program verifier |
| T2 | The forming (incomplete) candle is proposed | `CompletedDayCutoff` excludes the candle opening at `floor(as_of)`; the window is `[first_missing_open, cutoff)`; a NO-OP when nothing new is due |
| T3 | A single compromised fetch injects bad data | **Two isolated runners** must produce byte-identical canonical content (fingerprint + exact rows) with distinct runner identities; any disagreement is a HARD STOP |
| T4 | A tampered raw byte slips through | Each raw file's SHA-256 is bound to its receipt; the canonical rows re-derive from the raw bytes via the reviewed adapter |
| T5 | A truncated / gapped / overlapping window is accepted | The delivered rows are bound to the pre-registered plan window (exact bucket count, last open reaches `window_end − 1 day`, one-day contiguity); the transition requires a one-interval seam and a byte-identical accepted prefix |
| T6 | The accepted rows are silently rewritten | `ProspectiveUpdateTransition` proves the proposed cohort begins with the accepted rows unchanged and its old fingerprint equals the accepted base |
| T7 | A smuggled strategy/performance field or evaluation artifact rides in the proposal | The 35-check verifier scans every rebuilt proposal document (keys **and** values) for forbidden tokens, restricts the proposal directory to an **exact expected file set** (manifest + comparison + transition + the two runner dirs — any extra `weights.json`/`returns.json`/stray dir is refused), and scans remaining names against the comprehensive strategy/performance vocabulary |
| T8 | The automation auto-merges or applies to the accepted branch | Review policy is draft-only / human-required / no-auto-merge / no-retarget / no-accepted-mutation (exact-dict-equality + `any(bool)` guard); the descriptor builder pins the base to the accepted cohort branch and fails closed otherwise; **no** workflow at HEAD grants a write permission |
| T9 | A workflow exfiltrates data or gains write/network power | The hardened `_no_unsafe_workflow` scanner (and `test_workflow_security.py` / `test_m3e_workflow_security.py`) rejects any workflow that grants a write permission (`contents: write` quoted/whitespaced, `write-all`, or an omitted permissions block), contacts an exchange host (scheme-agnostic), uploads an artifact (incl. `upload-pages-artifact`), references a secret (dotted / index / `inherit`), force-pushes (`--force` / `-f` / `+refspec`), uses the PR-target event, or enables auto-merge (every spelling). A 14-case evasion matrix locks it |
| T10 | Untrusted PR code runs with privilege | The PR-check workflow is read-only and uses the plain `pull_request` event, never `pull_request_target`; it runs no untrusted code in a write-permission job |
| T11 | Overlapping scheduled runs duplicate a proposal | A deterministic, idempotency-keyed proposal branch + a concurrency lease converge on one proposal |
| T12 | The offline runner opens a socket | Repo hygiene forbids `urllib`/`http`/`socket`/`ssl`/`requests`/wallet imports across `src`/`tests`/`examples`; the AST allow-list confines `m3e` to strategy-free utilities; the network boundary is the hardened `curl` step only |

## Residual limitation (documented, by design)

The prospective cohort is self-anchoring: future-only candle bytes are bound to committed
receipts with no external value oracle. The two-runner canonical-equality attestation is
an offline integrity/reproducibility control, not authenticity against an outside source;
the two genuinely-isolated runners are the strongest offline authenticity signal, and
their recorded identities are the external-audit hook.
