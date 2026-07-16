# research/m3e — review-only prospective-update facility (data)

Milestone 3E lets the accepted M3D prospective ETH-USD daily cohort grow **only**
through independently-verified, append-only update **proposals** opened as **draft**
pull requests for human review — never auto-applied, never auto-merged, never pushed
to an accepted branch. The facility is **READY, NOT ACTIVE**: it evaluates no
strategy, computes no metric, and moves no money.

## Committed artifacts

| File | What it is |
|---|---|
| `accepted_base.json` | The trusted anchor: the accepted prospective cohort's identity, boundaries, content fingerprint (`bb6dd392…`), maturity/authorization flags, and the three byte-empty ledgers it binds. Re-derived byte-for-byte from committed M3D evidence by `verify_accepted_base`; stamps the frozen version `0.8.0`. |
| `proposal_registry.jsonl` | The append-only, hash-chained proposal registry (genesis sentinel + an `audit_noop` record for the live audit-mode probe run). No `proposal` record exists yet. Verified by `verify_registry`. |
| `AUDIT_MODE_EVIDENCE.md` | Evidence that the standing read-only probe ran live on GitHub Actions and correctly no-opped (nothing was due). |

## How to inspect (offline, read-only)

```
python -m eth_research.m3e.status --repo-root .    # data-only governance facts
python -m eth_research.m3e.replay --repo-root . --deep   # byte-exact rebuild proof
```

Neither command evaluates anything or mutates a tracked file. A real update
proposal, when one is due, is assembled offline by the `eth_research.m3e` machinery
(two-runner attestation → append-only transition → 35-check verifier) and lands under
`research/m3e/proposals/` as a **draft** PR. See `docs/M3E_PROSPECTIVE_PROTOCOL.md`,
`docs/M3E_THREAT_MODEL.md`, `docs/M3E_BUG_LOG.md`, and `docs/M3E_FINDINGS.md`.
