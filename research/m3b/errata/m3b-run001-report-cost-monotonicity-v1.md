# Erratum m3b-run001-report-cost-monotonicity-v1

- **Error class:** `overbroad_cost_monotonicity_claim`
- **Target experiment:** `m3b-fractional-execution-risk-v1-run-001`
- **Target report:** `research/m3b/fractional_report.md`
- **Target report SHA-256:** `68501639e7ba0660c7114c5b502861996b25bc0dff7e136500f4aca28260ae96`
- **Target results:** `research/m3b/fractional_results.json`
- **Target results SHA-256:** `81f94fab60f4f168bf5bb237c1e32e0d4567f4325ee6c541af7feffca2ab9dfc`
- **Previous erratum SHA-256:** `0000000000000000000000000000000000000000000000000000000000000000`

## Overbroad statement (preserved verbatim in the immutable report)

> The cost scenarios shrink net return monotonically in the modeled frictions

Statement byte hash (domain-separated): `449b17724cce015ccf4814360b3c0a08355c2d4ba476e868faf674805d4783de`

## Correction

Monotonic decline in the modeled frictions (compatibility_v1 >= causal_proxy_base >= causal_proxy_stressed) holds for the per-(strategy, cost-scenario) fold-median marked returns shown in Section 4, but NOT for every one of the 75 individual cells. Exactly one cell violates it: donchian_55_20 fold 1, whose causal_proxy_base marked return is below its causal_proxy_stressed marked return (a higher-friction scenario returned more in that single fold). The unqualified 'shrink net return monotonically' phrasing is therefore overbroad; it is correct only of the fold medians. No financial value changes and the immutable report bytes are preserved verbatim.

## Cell-wise counterexamples (full precision, rederived from the committed results)

| strategy | fold | lower-friction | return | higher-friction | return |
| --- | ---: | --- | ---: | --- | ---: |
| donchian_55_20 | 1 | causal_proxy_base | 0.9066879504114878 (+90.668795%) | causal_proxy_stressed | 0.9134855729480535 (+91.348557%) |

## Declarations

- Financial values changed: false
- Methodology changed: false
- Strategy parameters changed: false
- Development gate accessed: false
- Final holdout accessed: false
- New experiment run: false

