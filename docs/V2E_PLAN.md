# V2E Plan — Private Operations Dashboard and Paper-Activation Harness

Authoritative base: `main` @ `ba2dcc1d63f29a009d3660be2d960388a9615da0` (V2D active, package
`2.0.0.dev2`, accepted cohort 3/365, pending DATA-ONLY proposal `779df6bb` unmerged as draft
PR #22, three sealed ledgers byte-empty, no eligible candidate, paper blocked, not sell-ready).

Deliverables (all read-only with respect to research/governance state):

1. **Phase 1 (done first, outside this branch):** the pending proposal branch surfaced as ONE
   draft PR (#22) via the standard review channel — no re-acquisition, left unmerged.
2. **`eth_research.v2e` package** — smallest robust private dashboard:
   - `state.py`: one strict immutable `DashboardState` derived exclusively from the existing
     canonical parsers (`verify_accepted_base`, `load_activation_anchor`,
     `derive/verify_paper_readiness`, m3e `build_status`, m3f strict loaders). Fail-closed on
     malformed/duplicate-key JSON, symlinks, unexpected ledger bytes, accepted/proposed
     conflation, wrong-parent or stale proposal checkouts, missing files. Never repairs state.
   - `paper.py`: paper-execution lifecycle `disabled → eligible → frozen → approved → active →
     paused → stopped` with a 17-requirement fail-closed activation gate; every requirement is
     derived from committed evidence; no flag/env/subclass/constructor bypass. Resting state
     derivation can never yield `active`; `active` needs an activation token issued only when
     every requirement holds, plus the human-approval artifact gate. Current state: `disabled`.
   - `render.py`: server-rendered, phone-first HTML; all artifact-derived text escaped; honest
     language (proposed ≠ accepted; P&L "unavailable", never fake zeros; no charts, no trades).
   - `server.py`: stdlib `ThreadingHTTPServer`; GET/HEAD only; exact routes `/`, `/status.json`,
     `/healthz`; binds `127.0.0.1` by default; LAN binding requires an explicit flag and prints
     a warning; CSP + defensive headers; no tracebacks in responses; bounded response sizes; no
     filesystem/source/env exposure; no mutation endpoints; no GitHub token needed.
   - `dashboard.py`: CLI (`python -m eth_research.v2e.dashboard`), `--once` snapshot mode,
     optional `--proposal-checkout` for pending-proposal visibility with ancestry verification.
3. **Zero-exposure UI rehearsal** labeled `UI/OPERATIONS REHEARSAL — NOT PAPER TRADING`,
   proving no candidate/strategy instantiation, no market data read, zero exposure, no
   registry/ledger append.
4. **Security & adversarial tests**, five-auditor review, documentation set, full verification
   battery, ONE draft PR (left draft).

Out of scope / forbidden: strategy creation or evaluation, candidate nomination, paper/shadow/
live trading, sealed-partition access, order routing, credentials, public deployment, tags,
LICENSE, history rewrites, weakening the accepted fable5 paper-readiness gate.
