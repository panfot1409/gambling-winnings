# Validation-stage decision: fixed SMA(20/50) not promoted to test

- Subject: `sma_20_50` (fixed 20/50 windows — nothing tuned)
- Decision: **rejected_for_test_promotion**
- Test accessed to reach this decision: false
- Parameter changes made: none

## Criterion (fixed before any test access)

Promote the fixed SMA(20/50) specification to the one-time test only if it does not materially underperform buy-and-hold in the validation period. This criterion is fixed before any test access and no parameter is tuned.

## Validation evidence

- Buy-and-hold (benchmark) validation return: +204.67%
- SMA(20/50) (candidate) validation return: +1.48%
- Gap (candidate minus benchmark): -203.19 pp

## Rationale

This fixed SMA specification materially underperformed buy-and-hold in the validation period, so it is not promoted to the one-time test. This is a statement about one fixed specification on one validation period only — not a claim that moving-average strategies fail in general, and not a claim that buy-and-hold is itself an alpha strategy (it is the benchmark).

## Provenance

- Protocol SHA-256: `a75a9cf508ead459976060ab7518c4e382ecb95e54cc0ee36ec0ff9281f26a81`
- Dataset content fingerprint: `sha256:273f89eb07ae882784e40c2bc2ef2be5db93ddb3efa7de6270880ad1b7dd5718`
- Pre-registered code commit: `b89627463775bf32698effb5adea1270a5927890`

The pre-registered protocol is preserved unchanged as an honest record. The one-time test holdout remains untouched and sealed.
