# V2 Fable 5 Synthetic Catastrophe Rehearsal

A **disposable, zero-exposure** rehearsal of how the merged V2 platform (`main` = `09fc9c0`, the V2C
merge MV2C) behaves under catastrophic conditions, performed as part of the Fable 5 full-system audit
(branch `claude/v2-fable5-full-system-audit`).

**Zero-exposure contract.** Every scenario runs against a throwaway `tmp_path` tree or an in-memory
pandas frame. **No scenario touches the real repository, opens a sealed value, performs any network
I/O, connects to a broker, or routes any order.** This is emphatically **not** paper trading, shadow
trading, or prospective collection — it is a fail-closed drill. The rehearsal harness is standing
regression code at `tests/test_v2_fable5_catastrophe.py`; it is deterministic, offline, and part of
the normal test suite.

**The single invariant.** Across every catastrophe, the platform must **degrade to a refusal, never
to an activation**: paper activation stays OFF, prospective collection stays OFF, sealed state stays
untouched, and derivation/verification fails closed. A catastrophe must never be a path to turning a
safety flag true.

## Why rehearse catastrophes when nothing is live?

The V2 platform already carries deep recovery machinery — the V2C operational-qualification campaign
exercised fault schedules, transactional publication, crash/recovery, and an immutable archive, all
under virtual time. This rehearsal is complementary and narrower: it targets the **paper-activation
boundary** — the newest and most safety-critical surface, added by this audit
(`eth_research.v2.fable5.paper_readiness`) — and asks a single adversarial question: *under
catastrophe, can the system be tricked or degraded into authorizing paper trading?* The answer,
demonstrated below, is no.

## Scenarios and outcomes

| # | Catastrophe (synthetic) | Expected fail-closed behavior | Result |
|---|-------------------------|-------------------------------|--------|
| 1 | Platform fully hardened (audit complete, zero unresolved Class A/B/D, sealed ledgers empty, repo private) but **no candidate** | Platform gates green, yet `eligible_paper_candidate_present` blocks; nothing authorizes | PASS |
| 2 | Adversary **injects a fabricated nominated candidate** into the committed decisions and supplies every other gate's evidence **except** the on-file human approval | Eligibility flips true in the bytes, but the **human-approval gate** refuses authorization — it is the final backstop | PASS |
| 3 | A **sealed ledger is tampered** (no longer byte-empty — someone wrote into a sealed partition) | `sealed_partitions_untouched` flips false; authorization blocked | PASS |
| 4 | Attacker **hand-edits the committed `paper_readiness_state.json`** to claim `paper_activation_authorized = true` (and `paper_trading_active = true`) | `verify_paper_readiness` re-derives from bytes, detects the disagreement, and **raises** | PASS |
| 5 | **Degenerate market data** — a valid frame whose trailing liquidity collapses to zero volume into the terminal bar | The fractional engine prices the hypothetical terminal mark impact-free and returns a **finite** equity rather than crashing (regression for F5-C2) | PASS |
| 6 | **Total data loss** — every committed artifact wiped from the tree | Derivation does not raise, authorizes nothing, and `sealed_partitions_untouched` fails closed because *absence is not proof of emptiness* | PASS |

### Reading the results

- **Scenario 2 is the load-bearing one.** It proves the platform has *no code path* that authorizes
  paper trading on committed data alone: even a fully-provisioned tree with a forged candidate is
  refused until an explicit, on-file human activation approval exists. Authorization is the
  conjunction of eleven gates, and the human gate cannot be satisfied by any file the platform writes
  for itself.
- **Scenarios 3, 4, and 6 confirm fail-closed defaults.** Tampering, forgery, and data loss each
  drive the derivation *toward* "blocked", never toward "authorized". `verify_paper_readiness`
  additionally enforces a standing safety net: regardless of the committed file, it raises if
  authorization, active trading, or sell-readiness ever derives true in this milestone.
- **Scenario 5 is the robustness regression.** It ties the catastrophe drill to the F5-C2 fix (the
  terminal-liquidation crash), guaranteeing degenerate but schema-valid market data cannot produce a
  non-finite mark or an escaped exception.

## What this rehearsal is not

It is not evidence of trading edge, not a live-readiness certification, and not a substitute for the
external human/legal gates. It demonstrates only that **catastrophes fail closed** — that the
platform's refusal to paper-trade is robust to corruption, forgery, injection, tampering, and data
loss. The reason paper trading does not begin remains the one stated in
`docs/V2_PAPER_READINESS_GAP.md`: there is **no eligible strategy candidate**, and none may be
invented, relabeled, or resurrected to change that.

## Reproduce

```
.venv/bin/pytest tests/test_v2_fable5_catastrophe.py -q
```

All scenarios are offline and disposable; the suite mutates nothing outside its own `tmp_path`
fixtures and asserts (scenario "zero-exposure") that deriving readiness against the real repository
creates or removes no file.
