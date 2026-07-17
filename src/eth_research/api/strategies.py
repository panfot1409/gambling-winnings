"""Public strategy protocol and the built-in strategy registry (in-process only).

The public API exposes exactly two ways to supply a strategy:

* a :class:`~eth_research.api.models.StrategySpec` naming a **built-in** strategy id and
  its fixed integer parameters — the only form the CLI accepts, validated against a
  closed enumeration; or
* a custom :class:`Strategy` instance passed directly through the Python API. A custom
  strategy is **trusted caller code**: it runs in-process, is not sandboxed, and is
  documented as the caller's responsibility. There is no dynamic import from a path, no
  entry-point plugin loader, and no ``eval``/``exec`` — a strategy is always a Python
  object the caller already holds.

Built-ins delegate to the accepted engine strategies unchanged; this module only maps a
declarative spec onto them and translates their construction errors into
:class:`~eth_research.api.errors.StrategyError`.
"""

from __future__ import annotations

from eth_research.api.errors import StrategyError
from eth_research.api.models import StrategySpec
from eth_research.fractional.strategies import STRATEGIES_BY_NAME, FractionalStrategy
from eth_research.strategies import (
    BuyAndHold,
    Cash,
    DonchianChannel,
    MovingAverageCrossover,
    Strategy,
)

__all__ = [
    "BINARY_STRATEGY_PARAMS",
    "FractionalStrategy",
    "Strategy",
    "build_binary_strategy",
    "build_fractional_strategy",
    "list_binary_strategies",
    "list_fractional_strategies",
]

#: Built-in binary strategies and their fixed integer parameters (name -> default).
BINARY_STRATEGY_PARAMS: dict[str, dict[str, int]] = {
    "buy_and_hold": {},
    "cash": {},
    "moving_average_crossover": {"fast_window": 20, "slow_window": 50},
    "donchian_channel": {"entry_window": 55, "exit_window": 20},
}


def list_binary_strategies() -> tuple[str, ...]:
    """The built-in binary strategy ids, in a stable order."""
    return tuple(BINARY_STRATEGY_PARAMS)


def list_fractional_strategies() -> tuple[str, ...]:
    """The built-in fractional strategy ids, in a stable order."""
    return tuple(STRATEGIES_BY_NAME)


def _resolved_int_params(kind: str, spec: StrategySpec) -> dict[str, int]:
    allowed = BINARY_STRATEGY_PARAMS[kind]
    provided = spec.param_dict()
    unknown = set(provided) - set(allowed)
    if unknown:
        raise StrategyError(
            f"strategy {kind!r} does not accept parameter(s) {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    return {name: provided.get(name, default) for name, default in allowed.items()}


def build_binary_strategy(spec: StrategySpec) -> Strategy:
    """Construct a built-in binary :class:`Strategy` from a :class:`StrategySpec`.

    Raises :class:`StrategyError` for an unknown id, an unexpected parameter, or an
    invalid parameter combination (translated from the engine's own ``ValueError``).
    """
    kind = spec.kind
    if kind not in BINARY_STRATEGY_PARAMS:
        raise StrategyError(
            f"unknown binary strategy {kind!r}; expected one of {list_binary_strategies()}"
        )
    params = _resolved_int_params(kind, spec)
    try:
        if kind == "buy_and_hold":
            return BuyAndHold()
        if kind == "cash":
            return Cash()
        if kind == "moving_average_crossover":
            return MovingAverageCrossover(
                fast_window=params["fast_window"], slow_window=params["slow_window"]
            )
        if kind == "donchian_channel":
            return DonchianChannel(
                entry_window=params["entry_window"], exit_window=params["exit_window"]
            )
    except ValueError as exc:  # engine-side parameter validation
        raise StrategyError(f"invalid parameters for {kind!r}: {exc}") from exc
    raise StrategyError(f"unhandled binary strategy {kind!r}")  # pragma: no cover - defensive


def build_fractional_strategy(spec: StrategySpec) -> FractionalStrategy:
    """Resolve a built-in fractional strategy id to its pre-composed engine strategy.

    Fractional strategies take no free parameters, so any parameter is rejected.
    """
    if spec.param_dict():
        raise StrategyError(f"fractional strategy {spec.kind!r} takes no parameters")
    try:
        return STRATEGIES_BY_NAME[spec.kind]
    except KeyError:
        raise StrategyError(
            f"unknown fractional strategy {spec.kind!r}; "
            f"expected one of {list_fractional_strategies()}"
        ) from None
