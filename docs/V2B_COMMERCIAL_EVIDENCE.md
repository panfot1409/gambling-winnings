# V2B commercial evidence — multi-asset shadow and buyer posture

Preregistered **before any V2B result exists** (`eth_research.v2b.shadow`,
`eth_research.v2b.buyer_evidence`). Both extend the accepted V2A commercial layer without changing
its guarantees, and neither upgrades the commercial posture.

## Multi-asset (ETH/BTC/cash) vector shadow

The accepted shadow platform is signal-only and single-instrument. V2B extends it to the joint
ETH/BTC/cash universe: each bar's target is a **vector** of two long-only signal envelopes (ETH and
BTC; cash `= 1 − w_eth − w_btc`), derived from the candidate's causal executed path (a close-`≤t`
signal is valid as-of `open[t+1]`), with non-negativity and `gross ≤ 1` re-asserted per bar.

It is signal-only and offline. The three non-live modes are `synthetic_demo`, `historical_shadow`,
and `paper_simulation`; the prohibitions — **no network, no orders, no credentials, no money, no
leverage or shorting** — are the same fail-closed prohibitions the accepted shadow package enforces.
The committed policy artifact `research/v2b/multi_asset_shadow.json` freezes the instruments, modes,
prohibitions, and candidate ids. The per-bar vector machinery is exercised on synthetic panels only:
the shadow carries **signals, not returns**, and no real-partition performance artifact is committed.

## Buyer evidence — still not sell-ready

`research/v2b/buyer_evidence.json` reuses the accepted buyer-evaluation boundary (evaluation
contract, claims catalog, readiness scorecard, factsheet) unchanged. The V2B update does **not**
upgrade the posture: it stays `not_sell_ready` and `sell_ready` is explicitly `false`. Every prior
negative limitation is carried forward, and V2B's own are added:

- research-stage only — evaluated on the authorized research-train partition only; no out-of-sample,
  forward, or live evidence;
- V2A returned no nominated ETH-only candidate; that negative result stands as immutable evidence
  and is not reopened;
- V2B adds a genuinely-new BTC information source and at most one cross-asset candidate may be
  forwarded to an **independent** development-gate review; a nomination is **not** validation,
  forward evidence, deployment readiness, capacity, or a performance claim;
- any nomination must clear the cumulative family-wise multiplicity correction over M3A/M3B/M3C/V2A
  plus V2B — a stricter bar than any single milestone applied;
- sealed partitions are never read (byte-empty access ledgers);
- shadow operations are signal-only;
- `sell_ready` is false and remains false; nothing here is an offer to sell.

The artifact is frozen canonical JSON with a fingerprint, so a buyer reads exactly the honest,
negative-preserving posture — never a performance or deployment claim.
