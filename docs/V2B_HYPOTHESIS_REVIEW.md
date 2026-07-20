# V2B Hypothesis Review — cross-asset (BTC→ETH) information

Written and frozen **before any real BTC price byte enters the branch** (the V2B candidate source is
frozen from this review; the acquisition follows). It grounds the two pre-registered V2B candidate
families in the primary literature, fixes the narrow hypothesis, and states plainly what the evidence
does **not** support.

## Source-verification caveat (read first — scientific honesty)

The citations below were located and cross-checked across multiple independent search indexes
(RePEc/IDEAS, publisher pages, SSRN, NBER) on **access date 2026-07-19**. This session's outbound
network egress is governed by a restrictive policy: **every** attempt to fetch an external host
(arXiv, NBER, AMS, SSRN, Wiley, ScienceDirect, Oxford Academic, RePEc, Crossref, Semantic Scholar,
even `example.com`) was denied by the proxy (`403 connect_rejected`, policy denial). We did **not**
route around that denial. Consequently every source is cited by its **full bibliographic reference**
— the verifiable, honest core — and the locators (SSRN ids, DOIs, RePEc handles) are those returned
by search and are **not fetch-confirmed this session**. Two DOIs (Sifat et al. 2019; Alexander &
Dakos 2020) were search-summariser-derived and warrant extra care. A reviewer with open egress should
re-resolve each locator. No marketing blog, vendor page, or secondary summary is cited as scientific
support.

## The frozen hypothesis

> **H (narrow):** A lagged BTC state contains *incremental causal information* that may improve an ETH
> — or a BTC/ETH/cash — allocation rule relative to ETH buy-and-hold, **under realistic costs**, on
> the authorized research-train partition.

Explicitly **not** the hypothesis: "BTC predicts ETH profitably." H is a claim about *incremental
information that must be demonstrated*, out-of-sample-in-spirit (here: on a held-out-from-V2A,
cost-aware, multiplicity-corrected research-train read), not a claim of reliable profit.

## Literature grounding (primary sources)

**Momentum / trend is a real, documented effect.**
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). "Time Series Momentum." *Journal of
  Financial Economics* 104(2), 228–250. — an asset's own past return predicts its future return
  across 58 futures; the template for a BTC/ETH own-trend state. (SSRN 2089463; RePEc
  eee/jfinec/v104y2012i2p228-250.)
- Jegadeesh, N., & Titman, S. (1993). "Returns to Buying Winners and Selling Losers." *Journal of
  Finance* 48(1), 65–91. — founding cross-sectional relative-strength result; underpins an ETH-vs-BTC
  ranking. (DOI 10.1111/j.1540-6261.1993.tb04702.x.)

**Cross-asset lead-lag exists in principle …**
- Cohen, L., & Frazzini, A. (2008). "Economic Links and Predictable Returns." *Journal of Finance*
  63(4), 1977–2011. — economically-linked assets underreact to related-asset news, generating
  cross-asset predictability; the equity analogue of a "BTC confirms ETH" channel. (DOI
  10.1111/j.1540-6261.2008.01379.x.)
- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). "Value and Momentum Everywhere."
  *Journal of Finance* 68(3), 929–985. — momentum is a *shared* cross-asset-class effect; a BTC/ETH
  co-movement is more plausibly systematic than a unique BTC→ETH edge. (SSRN 2174501.)

**… but for BTC↔ETH specifically it is weak, bidirectional, and largely non-exploitable.**
- Sifat, I. M., Mohamad, A., & Mohamed Shariff, M. S. B. (2019). "Lead-Lag Relationship between
  Bitcoin and Ethereum." *Research in International Business and Finance* 50, 306–321. — **the key
  honesty anchor**: the BTC↔ETH lead-lag is time-varying and largely bidirectional, and traders "can
  barely exploit" it. Evidence *against* simple, profitable BTC→ETH prediction. (RePEc
  eee/riibaf/v50y2019icp306-321; search-derived DOI 10.1016/j.ribaf.2019.06.012.)

**Volatility scaling is the standard, literature-backed risk sizing.**
- Moreira, A., & Muir, T. (2017). "Volatility-Managed Portfolios." *Journal of Finance* 72(4),
  1611–1644 (NBER w22208). — scaling exposure inversely to realized volatility. (DOI
  10.1111/jofi.12513.) *V2B's primary candidates deliberately do not add a vol overlay* (to stay
  distinct from the vol-scaled families already rejected in M3B/M3C/V2A); this is cited as the
  established alternative, not adopted.

**Why H must be narrow — the erasure mechanisms.**
- Lesmond, D. A., Schill, M. J., & Zhou, C. (2004). "The Illusory Nature of Momentum Profits."
  *Journal of Financial Economics* 71(2), 349–380. — realistic trading costs can erase momentum's
  paper profits; the central caveat for any turnover-bearing BTC→ETH rule. (SSRN 256926.)
- Frazzini, A., Israel, R., & Moskowitz, T. J. (2018 wp). "Trading Costs of Asset Pricing Anomalies."
  SSRN 2294498. — the both-sides counter-evidence: real costs may be far smaller and momentum still
  implementable. Cited for balance; V2B still evaluates under a *stressed* cost scenario.
- Hamilton, J. D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series."
  *Econometrica* 57(2), 357–384; and Ang, A., & Timmermann, A. (2012). "Regime Changes and Financial
  Markets." *Annual Review of Financial Economics* 4, 313–337 (NBER w17182). — a BTC→ETH relationship
  should be expected to be regime-dependent and unstable out-of-sample, not constant.
- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica* 68(5), 1097–1126 (DOI
  10.1111/1468-0262.00152); Sullivan, R., Timmermann, A., & White, H. (1999). "Data-Snooping,
  Technical Trading Rule Performance, and the Bootstrap." *Journal of Finance* 54(5), 1647–1691. —
  in-sample technical-rule winners routinely fail once the search is accounted for.
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2014). "Pseudo-Mathematics and
  Financial Charlatanism." *Notices of the AMS* 61(5), 458–471; and (2016/2017) "The Probability of
  Backtest Overfitting." *Journal of Computational Finance* 20(4), 39–69. — high in-sample Sharpe is
  trivially manufacturable by trying enough configurations.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). "…and the Cross-Section of Expected Returns." *Review of
  Financial Studies* 29(1), 5–68 (NBER w20592); Harvey, C. R., & Liu, Y. (2020). "False (and Missed)
  Discoveries in Financial Economics." *Journal of Finance* 75(5), 2503–2553. — the significance bar
  must rise once many tests are run; the direct justification for V2B's cumulative family-wise
  multiplicity correction (see `docs/V2B_MULTIPLICITY_METHOD.md`).
- Lo, A. W., & MacKinlay, A. C. (1990). "An Econometric Analysis of Nonsynchronous Trading."
  *Journal of Econometrics* 45(1–2), 181–211 (NBER w2960); and Alexander, C., & Dakos, M. (2020). "A
  Critical Investigation of Cryptocurrency Data and Analysis." *Quantitative Finance* 20(2), 173–188
  (search-derived DOI 10.1080/14697688.2019.1641347). — stale/nonsynchronous daily closes and
  crypto data-source inconsistency can *manufacture* apparent cross-asset lead-lag; a prime
  alternative explanation V2B must not mistake for signal.

## What the literature does and does not support

Momentum and cross-asset lead-lag are real (Moskowitz-Ooi-Pedersen; Cohen-Frazzini; Asness-Moskowitz-
Pedersen), and a BTC↔ETH lead-lag is documented — but weak, frequently bidirectional, and largely
non-exploitable intraday (Sifat et al. 2019). It does **not** support "BTC predicts ETH profitably":
such signals are routinely erased by costs (Lesmond et al.), destabilized by nonstationarity and
regimes (Hamilton; Ang-Timmermann), inflated by data-snooping / multiple testing / overfitting (White;
Sullivan-Timmermann-White; Harvey-Liu-Zhu; Bailey et al.), and can be spurious artefacts of
stale/inconsistent daily-close data (Lo-MacKinlay; Alexander-Dakos). The evidence justifies **only**
the narrow hypothesis H, to be tested out-of-sample-in-spirit, under realistic and stressed costs,
with cumulative multiple-testing correction.

## How the two frozen candidate families operationalize H (before data)

Both candidate families (`eth_research.v2b.candidates`, source frozen before acquisition) read a joint
ETH/BTC daily-close panel, are long-only, unlevered, gross ≤ 1, and **refuse** (no signal) if BTC is
absent — never an ETH-only fallback. Primary parameters are fixed here:

- **Candidate A — cross-asset trend confirmation** (`cross_asset_btc_confirmed_eth_trend`, ETH
  horizon = BTC horizon = 100 days): the direct operationalization of *cross-asset confirmation*
  (Cohen-Frazzini; Moskowitz-Ooi-Pedersen) — hold ETH only when ETH's own single-horizon trend is up
  *and* BTC's confirms it. It cannot profit unless BTC state carries information beyond ETH's own
  trend (tested: information-dependence, §6).
- **Candidate B — cross-sectional relative-strength rotation**
  (`cross_asset_eth_btc_relative_strength_rotation`, lookback = 90 days): the operationalization of
  *relative strength* (Jegadeesh-Titman; Asness-Moskowitz-Pedersen) — allocate to the stronger of
  ETH/BTC when its momentum is positive, else cash.

Both are deliberately simple, unlevered, long-only, and deliberately **without** a volatility overlay,
so they are genuinely distinct from every already-rejected family (M3A/M3B/M3C/V2A) — see the
anti-relabel catalog and distinctness matrix (`docs/V2B_RESEARCH_MEMORY_METHOD.md`,
`tests/test_v2b_candidates.py`). Single horizons and a single lookback are chosen (no grid) precisely
because the literature warns that scanning lookbacks manufactures false winners (White; Bailey et al.).

## Honest posture

This is a research read on one instrument pair, one historical partition, daily closes. A rejected
candidate is not "proven edge-free"; a nominated candidate is *research-stage only* and earns nothing
but an independent development-gate review. V2 stays `not_sell_ready` regardless.
