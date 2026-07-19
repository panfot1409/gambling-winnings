# V2B BTC-USD acquisition — plan, window, temporary workflow, two-run protocol

The only genuinely-new information source V2B is permitted is **historical BTC-USD daily
candles**, restricted to the exact half-open window that matches the authorized ETH
research-train. This document records the acquisition design, the temporary hardened
workflow, the honest transient CI behaviour while that workflow exists, and the two
independent acquisitions and their canonical-equality check.

## The authorized window (hard-coded, not caller-set)

| Field | Value |
|---|---|
| Venue / product | Coinbase Exchange public market data / `BTC-USD` |
| Endpoint | `https://api.exchange.coinbase.com/products/BTC-USD/candles` |
| Granularity | 86 400 s (daily) |
| Window (half-open) | `[2016-05-23T00:00:00Z, 2022-06-22T00:00:00Z)` |
| Last authorized open | `2022-06-21T00:00:00Z` (the research cutoff) |
| Expected daily opens | **2221** (matches the accepted ETH research partition) |
| Windows / request cap | 8 non-overlapping windows of ≤ 299 daily buckets |
| Plan SHA-256 | `1a7368eb8012ff7e7ce6799204d8316b71acccbfaeeb6b581be13b2aab096e6a` |

The window is hard-coded in `eth_research.v2b.acquisition` (`WINDOW_START`,
`WINDOW_END_EXCLUSIVE`, `RESEARCH_CUTOFF_LAST_OPEN`). There is no caller-supplied product,
host, start, end, or granularity: `build_btc_acquisition_plan()` is the one plan a workflow
can run, and its `plan_sha256` is bound into every receipt. No BTC (or ETH) observation at or
after the research cutoff may be acquired, parsed, hashed, or used. The strict parser
(`parse_candles_body`) excludes pre-window rows and **rejects** any row at/after the window end
or the cutoff, any duplicate/misaligned bucket, any non-finite or non-positive price, and any
OHLCV-identity violation.

Endpoint semantics were cross-checked against the current official Coinbase Exchange
"Get product candles" reference (`start`/`end`/`granularity`, `[time, low, high, open, close,
volume]` rows, newest-first, ≤ 300 buckets/response). This session's egress is proxy-blocked,
so the reference could not be fetch-confirmed here; the accepted M2B/M3D adapter semantics plus
independent strict response validation are used, and the 299-bucket cap leaves margin below the
300-candle response limit.

## Offline runner (no networking)

`eth_research.v2b.acquire_runner` is socket-free. `emit-plan` writes the fixed per-window curl
request parameters (endpoint, granularity, user agent, plan hash, canonical start/end params,
safe filename — **no free-form command string**). `verify` reads the downloaded bodies plus a
per-window status sidecar and validates every response strictly offline (HTTP 200,
`application/json`, in-window day-aligned finite OHLCV, exact per-window and total open counts,
no forming/duplicate/missing bucket, no unexpected staged file), then writes a byte-reproducible
`BtcAttemptReceipt` recording body hashes + lengths — **never candle values**.

## Temporary hardened workflow (`.github/workflows/v2b-acquire.yml`)

The acquisition runs on a GitHub Actions runner (this environment's direct egress is
proxy-blocked, so the fetch cannot happen locally). The workflow is a temporary, one-shot,
push-sentinel bootstrap scoped to the exact branch and the single committed sentinel
`research/v2b/acquire.trigger`. Its hardening is asserted statically in
`tests/test_v2b_acquire_workflow_security.py`:

- top-level `permissions: contents: read`; `contents: write` **only** on the `acquire` job;
- no `id-token`, no secrets, no `packages:`, no `write-all`;
- `if:` guarded to `panfot1409/gambling-winnings` and the exact branch ref;
- attempt id whitelisted by a `case` guard to the two allowed ids;
- `actions/checkout` full-SHA pinned; uv from the hash-pinned `ci/uv-requirements.txt`;
- curl hardened: `--proto '=https' --tlsv1.2 --max-redirs 0 --fail --max-filesize`; no piped
  installer; the response body is written to a file (`-o`) and never printed to logs;
- fast-forward-only bot commit confined to the raw dir, with a before/after remote-head check;
- the endpoint is never a literal in the YAML (it is emitted from the hard-coded package
  constant), so no acquisition host string appears in any workflow.

### Honest transient CI state while the workflow exists (sections 11–12)

This branch stacks on top of the accepted M3F governance layer, whose honest-state derivation
enforces a **forever-invariant**: no workflow may grant `contents: write`. While the temporary
acquire workflow is present, the accepted governance verifiers therefore *correctly and loudly*
flag it. Exactly eight M3F governance tests report `HARD STOP: a workflow can write repository
contents` (and the equivalent supply-chain / independent-verifier / honest-state renders):

```
tests/test_m3f_honest_state.py::test_derive_real_repo_honest_state_holds_invariants
tests/test_m3f_honest_state.py::test_honest_state_render_is_deterministic
tests/test_m3f_audit.py::test_real_repo_governance_checks_all_pass
tests/test_m3f_audit.py::test_raise_for_status_is_silent_when_all_available_checks_pass
tests/test_m3f_audit.py::test_replay_status_reports_governance_facts
tests/test_m3f_independence.py::test_independent_verifier_passes_on_real_repo
tests/test_m3f_inventories.py::test_workflow_inventory_all_real_workflows_pass_the_supply_chain_check
tests/test_m3f_oracle.py::test_oracles_pass_on_real_repo
```

This is the **honest** transient state, not a regression, and it is not worked around: the
accepted governance code is left byte-for-byte unchanged (never weakened to hide the write
workflow). The `acquire` job runs independently of `ci.yml`, so the acquisition proceeds while
`ci.yml` transiently reports these eight. The instant section 13 retires the workflow and its
sentinel, all eight return to green, and no accepted governance artifact was modified. The
milestone's hard CI-green gates — source freeze (E), registration (R), one-shot execution (P) —
all fall **after** retirement.

## Two independent acquisitions (section 12)

| Attempt | id | Purpose |
|---|---|---|
| Genesis | `coinbase-btc-usd-research-genesis-001` | canonical acquisition |
| Audit | `coinbase-btc-usd-research-audit-002` | independent reacquisition |

Both run the **same** immutable plan (same `plan_sha256`) under different workflow run ids and,
where operationally possible, different source commits, writing to distinct raw directories with
distinct receipts and no shared response files. After each run the bot commit is pulled
fast-forward and re-verified offline (closed file set, status, receipt, every body length + SHA,
strict per-candle parse, exact in-window opens, no duplicate/missing/extra/forming candle, OHLCV
identities), then reduced to one canonical daily series. Genesis and audit are compared on: exact
row count, exact first/last open, the exact timestamp set, exact OHLCV values, and the exact
canonical content fingerprint. **Raw byte identity is not required** (whitespace/order may
legitimately differ); **canonical candle identity is the decisive check.** If even one canonical
candle differs, the run hard-stops before any strategy evaluation, a mismatch audit is published,
and the V2B one-shot budget stays unconsumed.

<!-- RUN EVIDENCE (filled after the acquisitions complete) -->
### Run evidence

| Field | Genesis | Audit |
|---|---|---|
| Workflow run id | _(pending)_ | _(pending)_ |
| Source commit | _(pending)_ | _(pending)_ |
| Receipt SHA-256 | _(pending)_ | _(pending)_ |
| Parsed daily opens | _(pending)_ | _(pending)_ |
| First / last open | _(pending)_ | _(pending)_ |
| Canonical fingerprint | _(pending)_ | _(pending)_ |

Canonical equality: _(pending)_.

## Retirement (section 13)

After the two-run canonical-equality check succeeds, the write-capable workflow and its sentinel
are removed, both raw bundles and the Actions run history are preserved, and standing tests prove
no workflow grants `contents: write`, no workflow contacts Coinbase, no acquisition trigger or
schedule remains, and every remaining `uses:` is full-SHA pinned. Any future acquisition requires
a new, separately reviewed workflow commit.
