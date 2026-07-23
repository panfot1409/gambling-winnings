# V2 Fable 5 — Auditor Reports

The Fable 5 full-system audit of the merged V2 platform (`main` = `09fc9c0` = MV2C) ran **five
independent primary auditors** over disjoint surfaces, followed by a **cross-auditor challenge
round** in which each auditor adversarially reviewed a peer's report. Every auditor worked read-only
on the real tree at branch head `1cace6d9`, ran all mutation/attack work on disposable `mktemp`
copies, re-verified the authoritative baseline against the pinned interpreter (`.venv` CPython
3.12.3), and never opened a sealed ledger. This document records each auditor's scope, verdict, and
the load-bearing observations; the reproduced defects are tracked in `docs/V2_FABLE5_BUG_LOG.md` and
`governance/v2/fable5_findings.json`.

**Aggregate outcome: zero Class-A (scientific), Class-B (governance/security), or Class-D
(sealed-state / immutable-drift / uncontrolled-exposure) defects.** All genuine findings are Class C
(defense-in-depth / robustness / test-strength); the challenge round converted the primary auditors'
"weakest boundary" observations into the reproduced Class-C items that were then fixed or documented.

## Primary auditors

### Auditor 1 — Scientific / Numerical / Accounting / Data-Integrity

**Verdict: PASS, zero genuine defects.** Audited the fractional long-only engine, the binary
backtest engine, the walk-forward protocol, both bootstraps, the ULP replay contract, shared
metrics, the promotion decision, and the V2A/V2B reconstruction oracles. Directly reproduced (not
merely read): the fractional engine is **prefix-invariant and causal** — mutating a future bar
cannot change an earlier bar's fill, price, lagged liquidity, or equity (strict `< as_of` liquidity
slice + one-bar-lagged signal); the **independent reconciler** re-derives cash/holdings/equity/fees/
exposure/cost-decomposition from primitives and rejects an injected free gain; metrics degrade to
NaN rather than absurd-but-finite at degenerate Sharpe/Sortino edges; and the V2A/V2B governed NULL
results reconstruct independently (zero eligible/nominated candidates). Flagged the terminal
hypothetical-liquidation path as the least-guarded corner but reasoned it "unreachable under the
frozen scenarios" — a conclusion the challenge round overturned (see F5-C2).

### Auditor 2 — Governance / Provenance / Immutability / Exactly-Once State

**Verdict: PASS, zero genuine defects.** Audited the V2C OQ governance surface (freeze,
supersession, registry, orchestrator, completion, finalize, archive, verify_archive, oracle,
result), the accepted qualification archive, the three sealed ledgers, and the V2/V2B honest-NULL /
`sell_ready` state. The source freeze and OQ-E2 activation anchor reproduce byte-for-byte from live
source; the registry lifecycle `registered → started → completed` (verdict `qualified`) has an
intact keyless hash chain; the three sealed ledgers are 0 bytes (`e3b0c44…7852b855`) and were never
opened; `oq_result.json` (`739cec5d…`) and the result bundle (`e52308a0…`) match; the deep archive
verifier and the independent OQ-Q oracle both accept. A full tamper battery (forged prev-hash,
reorder, duplicate started, verdict forgery, completed→failed downgrade, budget-reset truncation,
artifact deletion, byte-tamper, symlinked frozen source, non-zero-exposure oracle bypass) **failed
closed** at either the chain or the cross-check layer. **Strongest invariant:** accepted-artifact
byte-neutrality from the MV2C baseline to HEAD is exact — the only baseline→HEAD changes are additive
audit tooling. Named the keyless hash chain as the weakest boundary (integrity rests on git history
plus surviving-evidence gates, not a cryptographic attestation) — honestly disclosed as a known
limitation.

### Auditor 3 — Security / Supply Chain / Isolation / IP Confidentiality

**Verdict: PASS, zero genuine defects.** Grepped all of `src` for network/socket/http/websocket/
exchange-SDK/wallet/eval/exec/pickle/yaml.load/dynamic-import/subprocess/shell-injection: none
present as runtime usage (network-module names appear only in denylists that reject them; every
eval/exec/compile hit is `re.compile`; all subprocess calls are fixed list-argv git invocations with
`shell=False`). Ran the buyer harness end-to-end (7/7 checks PASS) and independently proved the `-S`
isolation flag is **load-bearing** (the isolated child cannot import `eth_research` with `-S`, can
without). Scanned all 17 workflows: every one is least-privilege (`contents: read`), SHA-pinned, with
no PR-triggered writes, secrets, OIDC, or pipe-to-shell. Built wheel + sdist twice in a scratch dir
and compared SHA-256 (byte-reproducible), ran the distribution scanner (clean), and confirmed the
distribution carries only the pure-Python package tree — no research data, sealed ledgers,
governance, tests, tools, docs, or git metadata.

### Auditor 4 — Operations / Reliability / Failure Recovery / Risk Controls

**Verdict: PASS, zero genuine defects.** Audited the publication transaction, the OQ completion-
intent + calculation-free finalizer, the append-only hash-chained registry, the fail-closed
orchestrator/StartedToken, the shadow risk engine / latching kill switch / as-of clock / acceptance
gate, the tamper-evident journal, and pure monitoring. Directly reproduced via fault injection on
scratch copies: full publication rollback of immutable artifacts + created-dir cleanup, immutable-
overwrite refusal, `O_EXCL` concurrency lock, path-traversal/symlink refusal; finalize fail-closed
under intent-without-archive, missing completeness marker, tampered verdict/evidence, drifted archive
bytes, torn registry append, and double-finalize; NaN/inf/negative/>1 price and weight refusals; and
a zero-cap kill-switch trip-on-breach with 0 fills. 89 operational tests pass. **Strongest
invariant:** crash consistency of terminal disposition — no modeled fault at any durable boundary can
mislabel a partial success as `completed`, and every ambiguous state fails closed. Noted the
single-line torn-append window and the absent `failed`-event producer as the least self-healing
corners (the latter surfaced in the challenge round as F5-N1).

### Auditor 5 — Buyer Due Diligence / API Boundary / Commercial Honesty / Sell-Ready Derivation

**Verdict: PASS, zero genuine defects.** Audited the V2C buyer boundary, the sell-ready derivations
(`readiness.py`, `commercial_truth.py`), and the buyer/commercial claim surface, acting as a
source-blind institutional buyer. A source-blind buyer can invoke only the approved interface and
receives only the four fixed redacted artifacts; every attempt to retrieve source, traverse paths,
name a withheld partition, inject code, import internals, or exceed the 32-request quota returned a
refusal. **Strongest invariant:** `sell_ready` cannot be forced true — both derivations are pure and
evidence-bound, and every forcing vector (literal, override, token, env var, CLI flag, monkeypatch,
alternate builder) is caught by fail-closed parse, pure derivation, self-binding digest, evidence
byte-binding, and full-rebuild equality; it is false because zero candidates were nominated and the
forward-evidence / live-record / license / authorization / security-legal-review gates are unmet.
Characterized the sales-honesty gate as the weakest boundary but framed it as "at worst over-flags /
fails safe" — a characterization the challenge round proved incorrect (see F5-C1, fail-**open**).

## Cross-auditor challenge round

Each challenger adversarially re-examined a peer's report, hunting false positives, missing
adversarial tests, and the true weakest boundary. Four challenges reproduced genuine Class-C items;
one was a reproducer correction with no new defect.

| Challenger → Target | Outcome |
|---------------------|---------|
| A5 (buyer) → A1 (scientific) | **F5-C2 reproduced.** A1's "terminal liquidation unreachable" was false: the trailing-30 median dollar-volume is *not* monotone (zero-volume bars can collapse the window), and the frozen `CAUSAL_PROXY_BASE`/`STRESSED` scenarios (not a custom one) both crash on a valid collapsed-liquidity frame. Fixed forward. |
| A4 (operations) → A5 (buyer) | **F5-C1 reproduced.** A5's "fail-safe" claim was wrong: the honesty scanner fails **open** — a distant/cross-clause negator (12-word window) or a paragraph example-marker lets a genuine unsupported superlative pass. The distant-negator vector was fixed (clause-scoped window); the paragraph marker was retained as a documented, author-controlled exemption. |
| A3 (security) → A4 (operations) | **F5-N1 reproduced.** The `failed` OQ terminal event is defined and read-validated but has **no producer** in the V2C OQ subsystem, so a started-but-uncompletable run has no implemented terminal disposition. Documented as a readiness gap (the OQ surface is frozen; the failure path belongs to a future live/paper run). Also re-affirmed the keyless-registry known limitation. |
| A2 (governance) → A3 (security) | **Reproducer correction, no new defect.** A3's cited AST-scanner bypass examples (`getattr(builtins,…)`, base64) are actually *caught*; the only genuine slip is `getattr(__builtins__,'__import__')(…)` with no import statement — still `is_defect=false` because the scanner only runs over the fixed shipped client and the `-S` OS isolation is the real boundary. Fuzzed the vendor framing loop: bounds held. |
| A1 (scientific) → A2 (governance) | **F5-N2 reproduced.** The offline acceptance verifiers (`verify_oq_run_archive` + OQ-Q oracle) re-bind the archive and derived digests but do **not** re-bind the registry's identity-bound frozen-*input* digests, so a self-consistent forgery of those provenance fields is admitted offline. Already covered by V2C bug **C-001**, which re-executes the frozen source and re-derives the digests; recorded for completeness. |

## Disposition

Every reproduced Class-C item was fixed forward with a failing-test-first regression or documented as
an accepted by-design property; none touches a sealed value, a frozen governed artifact, or any
committed V2A/V2B/V2C result. All replay/oracle verifiers reproduce byte-identically after the fixes.
The five primary auditors independently confirmed that causality, accounting, numerical, governance,
provenance, immutability, security, isolation, supply-chain, IP, operations, recovery, buyer-boundary,
and sell-ready-derivation invariants hold on the accepted platform.
