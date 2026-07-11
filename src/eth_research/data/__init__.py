"""Historical market data: validated OHLCV schema and synthetic series."""

from eth_research.data.schema import (
    OHLCV_COLUMNS,
    PRICE_COLUMNS,
    TIMESTAMP_COLUMN,
    SchemaError,
    validate_ohlcv,
)
from eth_research.data.synthetic import make_synthetic_ohlcv

__all__ = [
    "OHLCV_COLUMNS",
    "PRICE_COLUMNS",
    "TIMESTAMP_COLUMN",
    "SchemaError",
    "make_synthetic_ohlcv",
    "validate_ohlcv",
]
