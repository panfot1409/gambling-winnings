# V2E Private Operations Dashboard

Read-only, loopback-first, phone-friendly view of the honest program state. It runs
nothing, mutates nothing, needs no network, no GitHub token, and no credentials.

## Quick start

```bash
python -m eth_research.v2e.dashboard --repo-root .           # http://127.0.0.1:8377/
python -m eth_research.v2e.dashboard --once --repo-root .    # one HTML snapshot to stdout
python -m eth_research.v2e.dashboard --repo-root . \
  --proposal-checkout /path/to/bot-branch-worktree            # show the pending proposal
```

To display the pending DATA-ONLY proposal, give it a local read-only checkout of the bot
branch (`git worktree add --detach /tmp/proposal <bot-branch-sha>`); the dashboard
verifies the checkout's ancestry against the accepted base and refuses stale or
wrong-parent proposals outright.

## Phone use on a trusted LAN (explicit opt-in)

```bash
python -m eth_research.v2e.dashboard --repo-root . --host 0.0.0.0 --allow-lan
```

Then open `http://<machine-LAN-IP>:8377/` from the phone. **Warning (also printed at
startup): LAN mode has NO public-internet security guarantee.** The dashboard is
read-only, but never port-forward it, never expose it to an untrusted network, and never
run it on a machine you do not control. Without `--allow-lan` a non-loopback bind is
refused.

## Endpoints

| Route | Meaning |
| --- | --- |
| `/` | full HTML dashboard |
| `/status.json` | approved status facts (same state model, JSON) |
| `/healthz` | liveness only (`{"ok": true}`), no state build |

Anything else is `404`; POST/PUT/PATCH/DELETE are `405` (there are no mutation
endpoints, so there is nothing for CSRF to target).

## Status-field reference (`/status.json`)

- `identity` — repository, package version, 40-hex commit (resolved textually from
  `.git`, no git execution), `private_local_only`.
- `cohort` — ACCEPTED state on the served checkout only: row count vs 365 target,
  progress %, first/last open, remaining rows, maturity, `evaluation_authorized`
  (always false today), accepted fingerprint.
- `proposal` — pending UNMERGED proposal facts, only when `--proposal-checkout` is
  given and ancestry-verified; never conflated with accepted state.
- `acquisition` — schedule posture, standing workflow, last registry entry, last live
  run/outcome, two-runner agreement, append-only result, next-due status, and the
  standing guarantees (`direct_main_writes=false`, `draft_review_required=true`).
- `integrity` — three sealed ledgers (must be byte-empty or the whole build refuses),
  accepted-base verification, V2A/V2B artifact checks, V2C OQ registry parse, verified
  fable5 paper readiness, V2D anchor validity, source-freeze presence, proposal
  verification. These are committed-artifact checks; the deep numeric replays remain
  the CLI/CI commands listed below.
- `candidate` — nominated candidate (`none`), eligibility, freeze/approval gates,
  `paper_activation_authorized`/`paper_trading_active`/`sell_ready` (all false), and
  the exact `blocking_gates` from the accepted fable5 derivation.
- `paper_engine` — engine `disabled`, mode `no candidate`, zero exposure/positions/
  orders/fills, P&L `UNAVAILABLE` (absence of record, not zero performance), kill
  switch `ENGAGED BY POLICY`, lifecycle resting state, exact blocking requirements.
- `timeline`, `limitations` — accepted milestones and honest limits; no strategy or
  paper events exist.

## Troubleshooting

- **HTTP 500 "dashboard state verification failed"** — a canonical artifact failed a
  strict check (malformed/duplicate-key JSON, symlink, nonempty sealed ledger, forged
  readiness flag, wrong-parent proposal). The dashboard never repairs state: inspect
  the server's stderr for the refusing check, then verify the repository with the
  deep replays below. A refusal is evidence, not a nuisance.
- **`refused: ... allow_lan`** — you asked for a non-loopback bind without
  `--allow-lan`; that is the safety default.
- **Proposal panel says "no proposal checkout configured"** — pass
  `--proposal-checkout`; the draft PR itself remains visible on GitHub.
- Deep verification commands (unchanged by V2E): `python -m eth_research.m3e.replay
  --repo-root . --deep`, `python -m eth_research.m3d.replay --repo-root . --deep`,
  `python -m eth_research.v2c.oq.cli replay --repo-root .`,
  `python -m eth_research.v2.fable5 verify` / `freeze-verify`.

## Threat model (summary)

In scope: a hostile artifact in the working tree (injection via displayed text —
neutralized by escaping + CSP `default-src 'none'`; forged governance flags —
refused by re-derivation), a curious LAN peer in `--allow-lan` mode (read-only fixed
routes, no source/env/path disclosure, no tracebacks, bounded responses), and operator
error (mutation verbs 405, no activation control exists). Out of scope by design:
public-internet exposure (never bind it publicly), OS-level compromise of the host,
and anything requiring credentials (none are read, stored, or required). The paper
gate cannot be weakened from this surface: the dashboard only *consumes* the accepted
fable5 derivation and re-verifies the committed readiness state byte-for-byte.
