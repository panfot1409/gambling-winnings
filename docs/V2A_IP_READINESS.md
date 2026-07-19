# V2A IP-Readiness Notes — PRIVATE DRAFT

> **Status: PRIVATE INTERNAL DRAFT. Not legal advice. Not an IP opinion.**
> Internal planning notes on what would need to be true for the program's intellectual property to be
> "ready" for any commercial step. Not a legal analysis; qualified counsel is required for any real
> IP decision.

## What "IP readiness" would require (checklist, mostly unmet)

| Item | Status today | Note |
| --- | --- | --- |
| Clear ownership of the code and research artifacts | to be confirmed | ownership/authorship must be established with counsel |
| A chosen repository license | **absent (intentional)** | no license is present; this is a deliberate human gate |
| Third-party dependency license review | partial | deps are numpy / pandas / pyarrow; a formal review is pending |
| No embedded third-party proprietary data | holds | only committed raw is offline-acquired public-exchange candles under a size cap |
| Trademark / naming clearance | not started | no product name is claimed |
| Patentability assessment (if any) | not started | no patent is claimed or pursued |
| Trade-secret handling (source, sealed data) | in place structurally | source is never disclosed; sealed partitions are firewalled |
| Contribution provenance | in place | commits are attributed; history is append-only |

## Trade-secret posture

The program treats source code and the sealed partitions as trade secrets: they are never disclosed
at the buyer boundary (enforced by the redaction scanner and the evaluation gateway), and the sealed
access ledgers are byte-empty. This posture is a *precondition* for any future IP conversation, not a
substitute for a formal IP position.

## Dependency-license note

Runtime dependencies are permissively licensed scientific libraries (numpy, pandas, pyarrow). A
formal dependency-license review — including transitive dependencies and build tooling — must be
completed before any distribution beyond the current private channel.

## Explicit non-conclusions

- This document does **not** conclude that the IP is owned, clear, licensable, or valuable.
- It does **not** choose a license (that remains a human decision; none is added).
- It does **not** authorize any transfer, distribution, or commercial use.

## Gate

No IP-dependent commercial step may proceed until every checklist item above is affirmatively
resolved by qualified counsel and a human explicitly authorizes it.
