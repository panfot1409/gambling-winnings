# Erratum m3a-run003-report-zero-inclusion-v1

- **Error class:** `incorrect_statistical_summary`
- **Target experiment:** `m3a-fixed-baseline-comparison-v2-run-003`
- **Target artifact:** `research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/development_report.md`
- **Target artifact SHA-256:** `d6e920760fd4217cbac00cf6126b0da2afc1f0a9e673aacfc9aee5fc6baa3bfd`
- **Target results:** `research/m3a/experiments/m3a-fixed-baseline-comparison-v2-run-003/development_results.json`
- **Target results SHA-256:** `5f6377b6eb0eb8c2a5ba126c37b29de5095670f7ed27c064f44e18c9c91ea8ae`
- **Previous erratum SHA-256:** `0000000000000000000000000000000000000000000000000000000000000000`

## Erroneous statement (preserved verbatim in the immutable artifact)

> every fold-aware bootstrap interval of mean daily paired excess return versus buy-and-hold straddles zero

Statement byte hash (domain-separated): `6c370216c26ba64d74a453c78d6ed6b4dc94f5c7c31af7d4398dc3ac64bbcd8c`

## Corrected statement

The primary fold-stratified bootstrap intervals for sma_20_50 and donchian_55_20 straddle zero. The primary cash intervals are strictly below zero and therefore exclude zero on the underperformance (negative) side. The hierarchical sensitivity intervals straddle zero for every strategy, including cash. This is in-sample research-train evidence, not alpha, and promotes no candidate. The original report's rounded -0.00% display of the cash primary upper bound does not make zero part of the interval. All financial results remain unchanged from run-002.

## Affected cells (full precision, rederived from the committed results)

| strategy | scenario | interval | ci_lower | ci_upper | contains zero |
| --- | --- | --- | --- | --- | --- |
| cash | base | primary | -0.005063937422795938 (-0.506394%) | -1.220168774754618e-05 (-0.001220%) | no |
| cash | stressed | primary | -0.005063904789164851 (-0.506390%) | -1.1503664325654388e-05 (-0.001150%) | no |
| cash | severe | primary | -0.005062567013459328 (-0.506257%) | -1.0358783751154005e-05 (-0.001036%) | no |

## Declarations

- Financial values changed: false
- Methodology changed: false
- Strategy parameters changed: false
- Development gate accessed: false
- Final holdout accessed: false
- New experiment run: false

