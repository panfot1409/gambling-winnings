# V2 Fable 5 — Threat Model

The threat model for the Fable 5 full-system audit of the merged V2 platform (`main` = `09fc9c0` =
MV2C). It states what the platform is, who the adversaries are, what must not happen, and where the
audit's guarantees end. It is deliberately conservative: the platform is **not live**, holds **no
eligible strategy**, and paper trading is **blocked** — so the dominant threats are not to capital
but to *scientific and governance integrity*.

## What the platform is (and is not)

- An **offline research and simulation** codebase plus an **operationally-qualified but inactive**
  execution/shadow platform. It evaluates strategies on committed historical data, records governed
  decisions, and can (when a candidate exists and is authorized) rehearse shadow operations.
- It has **no** network egress, exchange SDK, wallet, broker connectivity, or order-routing path in
  runtime source. Network-module names appear only in denylists that reject them.
- V2A/V2B were run once each and produced **governed NULL results** (zero nominated candidates).
  V2C qualified the *platform*, not a strategy. There is therefore **no edge and no candidate**.
- The repository is **private** (`Private :: Do Not Upload`; no license). Distribution is private-only.
  > **Erratum, 2026-07-28 (V2F-R).** This inference was wrong, and it was load-bearing: it is a
  > threat-model *assumption* that later analysis rested on. `Private :: Do Not Upload` is a PyPI
  > trove classifier governing whether the Python Package Index rejects an upload; it carries no
  > information about GitHub repository visibility. The repository was in fact **public** when this
  > line was written, and third-party market data was being published from it. Repository visibility
  > is now derived only from a committed GitHub API observation
  > (`governance/v2f/repository_visibility.json`). The classifier remains the packaging kill-switch
  > and nothing more. See `docs/V2_PUBLIC_EXPOSURE_INCIDENT.md`.

## Assets to protect

| Asset | Why it matters |
|-------|----------------|
| Accepted V2A/V2B/V2C artifacts | The scientific record; must be byte-immutable once sealed |
| Three sealed ledgers (test-eval, dev-gate, prospective) | Sealed partitions; opening one taints the holdout / research firewall |
| The `sell_ready` = false derivation | Commercial honesty; must never be forced true without genuine evidence |
| The paper-activation gate = blocked | Must never authorize paper trading absent an eligible candidate + human approval |
| Buyer boundary | A source-blind buyer must receive only redacted, approved artifacts |
| Distribution artifacts | Must carry only the pure-Python package — no data, ledgers, governance, secrets |

## Adversaries and their capabilities

1. **The over-eager operator (dominant threat).** Someone — human or agent — who *wants* a shippable
   result and is tempted to relabel a null result as a candidate, loosen a decision rule, reinterpret
   operational qualification as edge, or force a readiness flag true. The controls against this are
   scientific, not cryptographic: pure byte-derived gates with no forcing literal, anti-relabel
   verifiers, and the human-approval backstop.
2. **A writer with filesystem access.** Someone who can hand-edit committed files (registry lines,
   governance JSON, decision artifacts). Controlled by fail-closed re-derivation from bytes, the
   inventory drift check, the source freeze, and — for the acknowledged keyless-registry limitation —
   git history plus human review.
3. **A hostile buyer.** A source-blind counterparty probing the buyer boundary for source leakage,
   path traversal, withheld-partition disclosure, code injection, or quota bypass. Controlled by the
   gateway allowlist + redaction + OS-level `-S`/`-I`/`-B` isolation.
4. **A supply-chain attacker.** Someone attempting to smuggle sensitive material into a distribution
   artifact or add an unpinned/over-privileged workflow. Controlled by the distribution scanner, the
   reproducible build, and the workflow least-privilege / SHA-pin checks.
5. **The environment itself.** Non-determinism, degenerate market data, crashes at durable
   boundaries, disk full. Controlled by pinned interpreters, NaN-degradation, transactional
   publication with rollback, and fail-closed finalization.

## Trust boundaries

- **Committed bytes ↔ derivation.** Every governance conclusion (`sell_ready`, paper activation,
  inventory, source freeze) is *derived from committed bytes* and re-checked in CI. Nothing is a
  stored flag trusted on its own. This is the primary integrity boundary.
- **Frozen source ↔ live tree.** The V2C OQ source freeze and the Fable 5 source freeze pin the
  audit-relevant source and governance bytes; a replay CI re-derives them. The keyless registry hash
  chain provides tamper-**evidence** (not authenticity) and is delegated to git history + human review.
- **Buyer ↔ vendor.** An OS-process boundary (`-S` disables site processing of the editable install,
  so the isolated child cannot import the repository package) plus a redaction/allowlist gateway.
  Documented limitation: no OS-level sandbox; the static AST client scanner proves properties of the
  *shipped fixed client*, not containment of an arbitrary hostile binary.
- **Repository ↔ outside world.** Private classification, no license, no publication pipeline that
  ships source; distribution is private-only and scanned.

## What must never happen (hard-stop conditions)

- **Class D:** a sealed partition is opened; an accepted result drifts byte-for-byte; a one-shot is
  re-run or corrupted; the repository is published; any uncontrolled-exposure capability (network
  egress, broker connectivity, order routing, live capital) is added.
- **Accepted-result-invalidating Class A:** a scientific/accounting/evidence defect that would
  invalidate a committed V2A/V2B/V2C result.

The audit found **none** of these. All three sealed ledgers stayed byte-empty; the accepted artifact
set is byte-neutral from MV2C to HEAD; no strategy was evaluated; no prospective/paper activation
occurred.

## Coverage and the boundaries of these guarantees

The five primary auditors + challenge round exercised: causality/temporal leakage, accounting
reconciliation, numerical edge cases, claim integrity, governance/provenance/immutability/exactly-
once state, security/supply-chain/isolation/IP, operations/reliability/recovery/risk controls, and
buyer/commercial-honesty/sell-ready derivation. The reproduced Class-C items were fixed or documented.

**Where the guarantees end (honest limitations):**

- The registry hash chain is **keyless** — tamper-evidence, not cryptographic authenticity; a writer
  with filesystem access can hand-append a byte-valid forged terminal event. Delegated to signed git
  history + human review. A live deployment should upgrade to a keyed/signed chain.
- The offline acceptance verifiers re-bind the archive/verdict/exposure digests but historically did
  not re-bind the frozen-*input* provenance digests; this is covered by V2C bug C-001, which
  re-executes the frozen source and re-derives the digests on the authoritative interpreter.
- The buyer isolation has **no OS-level sandbox**; the static client scanner covers only the shipped
  fixed client.
- The sales-honesty scanner is a keyword heuristic scoped to the named buyer/commercial files; after
  the F5-C1 fix it no longer fails open on a distant/cross-clause negator, but the paragraph
  example-marker remains a deliberate author-controlled exemption over the project's own spec text.
- Data-integrity verification establishes internal consistency of the committed evidence with itself
  (the oracles re-derive the committed NULL decisions); it does not regenerate the committed
  primitives from raw market data (which would consume a one-shot).

None of these limitations creates an uncontrolled-exposure capability, and each is disclosed here and
in the relevant module/security docs.
