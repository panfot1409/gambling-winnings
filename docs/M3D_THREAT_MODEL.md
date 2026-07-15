# M3D Threat Model

Milestone 3D is a data-only, governance-only facility whose single asset is
**epistemic honesty**: the claim that the research program evaluated nothing new,
that the prospective cohort is genuine future data, and that it is immature and
unauthorized. This model enumerates the threats to that claim and the controls
that neutralize each, all enforced by the 25-check whole-program verifier
(`eth_research.m3d.verify_m3d_program`) and the standing test suite.

## Assets

1. The truth of "M3D evaluated / ranked / tuned / promoted no strategy."
2. The genuineness and reproducibility of the prospective cohort's canonical
   content.
3. The byte-emptiness of the two sealed access ledgers and the prospective
   evaluation ledger.
4. The byte-integrity of every prior immutable artifact (M2B/M3A/M3B/M3C).

## Threats and controls

| # | Threat | Control |
|---|--------|---------|
| T1 | A hidden strategy evaluation / metric / ranking is computed | Isolated `m3d` package with an AST import firewall (no engine/strategy/backtest/metrics/evaluation imports); `require_no_evaluation_capability`; `_scan_forbidden_fields` over published artifacts; the four `*_performed/declared/computed/exists` flags are false and rebuilt. |
| T2 | Maturity or authorization is forced | `evaluate_maturity` re-derives maturity from committed evidence, pins the floor at 365, and asserts `evaluation_authorized` stays false even when mature; the manifest is rebuilt byte-exact so a hand-edited `maturity_state`/flag is rejected. |
| T3 | A forming candle or future-dated row is smuggled in | Half-open parse window + inclusive-end request convention exclude the forming candle; the receipt binds retained raw bytes by SHA-256; rows are re-derived, never trusted from metadata. |
| T4 | The cohort overlaps the exhausted/sealed data | The quality audit hard-stops if any prospective open is at or before the final M2B candle; the cohort start is fixed strictly after it. |
| T5 | The acquisition is not genuinely reproducible | An independent audit reacquisition under a distinct plan/commit/run must reproduce byte-identical canonical content; divergence is a HARD STOP. |
| T6 | A sealed or evaluation ledger gains an event | All three ledgers are asserted byte-empty before and after replay, in the verifier, and in CI; the M3D facility never appends any of them. |
| T7 | The M3C candidate verdict is silently changed | The verifier asserts the committed M3C candidate decision still carries the rejected outcome. |
| T8 | A prior immutable artifact drifts | Every governance and acquisition artifact is rebuilt and compared byte-for-byte; prior-milestone anchors are hash-bound. |
| T9 | A residual network / write capability remains | The one-shot acquisition workflow and its sentinel are deleted at the final HEAD; workflow-security tests assert no workflow grants `contents: write` or contacts Coinbase, every action is SHA-pinned, uv is hash-pinned, no secrets, no force push, no piped installer. |
| T10 | The offline runner opens a socket | Repo hygiene forbids `urllib`/`http`/`socket`/`ssl`/`requests` imports across `src`/`tests`/`examples`; the network boundary is `curl` in the (now retired) workflow only. |
| T11 | Status/replay leaks OHLCV or performance data | The status CLI emits only safe governance facts (a content fingerprint is a hash, never a price) and fails closed on any value-bearing forbidden key; replay computes and prints no candle value. |
| T12 | A partial/torn publication leaves a dishonest state | The transactional publisher is all-or-nothing with readback+reparse+rehash and rollback in fresh and overwrite states; failure injection is tested at every position. |

## Hard stops

Any of the following stops the milestone immediately with no repair or
substitution: a sealed or evaluation ledger becomes non-empty; a prior immutable
artifact drifts; the M3C verdict changes; Coinbase returns no completed row, a
gap, malformed data, or changed semantics; primary and audit canonical content
differ; or a Class D red-team finding is confirmed.
