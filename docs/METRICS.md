# Metrics

A backtest records a fixed set of performance metrics on its immutable
`ResearchResult`. The two engines report two different metric sets. The numbers
are delegated verbatim from the accepted internal engines — the public layer
reimplements no formula; it collects the engine's output and coerces each value
to a plain finite number or `null`.

Read the metrics from a result with `.metric_map()`:

```python
result = run_binary_backtest(dataset, StrategySpec("buy_and_hold"), CostSpec("base"))
metrics = result.metric_map()
print(metrics["total_return"], metrics["sharpe"])
```

## Undefined metrics serialize as null

A metric that is genuinely undefined for a run — for example the Sharpe ratio of
a zero-volatility cash strategy — is represented as JSON `null` (Python `None`),
not as a non-finite number. This keeps every result finite, canonical, and
deterministic. The value is never otherwise altered; this is type coercion, not
recomputation.

```python
r = run_binary_backtest(dataset, StrategySpec("cash"), CostSpec("base"))
assert r.metric_map()["sharpe"] is None   # cash has zero volatility
```

## Binary metrics

`run_binary_backtest` and `calculate_metrics` report these keys:

| key | meaning |
| --- | --- |
| `n_periods` | number of evaluated bars |
| `periods_per_year` | annualization factor implied by the candle interval |
| `initial_equity` | starting equity |
| `terminal_equity` | ending equity |
| `total_return` | total return over the evaluated window |
| `cagr` | compound annual growth rate |
| `sharpe` | annualized Sharpe ratio (uses `risk_free_rate`) |
| `sortino` | annualized Sortino ratio |
| `max_drawdown` | maximum peak-to-trough drawdown (negative) |
| `total_traded_notional` | sum of the notional of all fills |
| `turnover` | traded notional relative to equity |
| `num_trades` | number of trades executed |

## Fractional metrics

`run_fractional_backtest` reports these keys:

| key | meaning |
| --- | --- |
| `total_return` | total return over the evaluated window |
| `annualized_return` | annualized return |
| `annualized_volatility` | annualized volatility of returns |
| `sharpe_ratio` | annualized Sharpe ratio (uses `risk_free_rate`) |
| `sortino_ratio` | annualized Sortino ratio |
| `max_drawdown` | maximum peak-to-trough drawdown (negative) |
| `num_fills` | number of fills |
| `num_partial_fills` | number of fills limited by the participation constraint |
| `total_traded_notional` | sum of the notional of all fills |
| `turnover` | traded notional relative to equity |
| `total_fees` | total fees paid |
| `average_achieved_exposure` | mean realized exposure over the window |
| `time_in_market` | fraction of bars with non-zero exposure |
| `terminal_equity` | ending equity |
| `terminal_liquidation_equity` | ending equity after liquidating the final position at cost |

## Annualization

`periods_per_year` is derived from the dataset's candle interval (for daily
bars, 365.25). The Sharpe and Sortino ratios use the `risk_free_rate` passed to
the run (default `0.0`). Because the metrics come straight from the accepted
engines, two runs with identical inputs produce identical metric values, and the
serialized result has a stable SHA-256 (see
[REPRODUCIBILITY.md](REPRODUCIBILITY.md)).
