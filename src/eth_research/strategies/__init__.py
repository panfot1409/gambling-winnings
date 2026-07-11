"""Trading strategies: interface, benchmark, and simple baselines."""

from eth_research.strategies.base import Strategy
from eth_research.strategies.buy_and_hold import BuyAndHold
from eth_research.strategies.moving_average import MovingAverageCrossover

__all__ = [
    "BuyAndHold",
    "MovingAverageCrossover",
    "Strategy",
]
