"""Public, strictly-typed offline research API for the eth-research platform.

This is the intentional public surface: a small set of frozen, canonical-JSON serializable
value models, a handful of pure functions that delegate to the accepted research engines (no
numerical formula is reimplemented here), and a closed error taxonomy. It contains no
live-trading capability of any kind — no exchange connectivity, authentication, wallet, order
routing, leverage, or network client — and operates only on historical OHLCV data the caller
supplies from local files or the deterministic synthetic generator.

Only the names re-exported below (``__all__``) are public and covered by the compatibility
policy; everything else under :mod:`eth_research.api` is an implementation detail.
"""

from __future__ import annotations

from eth_research.api.backtest import (
    calculate_metrics,
    run_binary_backtest,
    run_fractional_backtest,
)
from eth_research.api.config import (
    CONFIG_SCHEMA_VERSION,
    RunConfig,
    load_config,
    load_config_file,
)
from eth_research.api.dataset import (
    CanonicalDatasetArtifacts,
    DataSplitResult,
    build_canonical_dataset,
    chronological_split,
    generate_synthetic_dataset,
    load_canonical_dataset,
    validate_dataset,
)
from eth_research.api.errors import (
    AccountingError,
    BacktestError,
    CausalityError,
    ConfigurationError,
    DatasetError,
    DatasetIntegrityError,
    DatasetSchemaError,
    EthResearchError,
    OutputCollisionError,
    ReceiptVerificationError,
    ResultValidationError,
    StrategyError,
)
from eth_research.api.models import (
    API_VERSION,
    BINARY_COST_SCENARIOS,
    BINARY_STRATEGY_KINDS,
    ENGINES,
    FRACTIONAL_COST_SCENARIOS,
    FRACTIONAL_STRATEGY_KINDS,
    BinaryBacktestSpec,
    CanonicalDataset,
    ChronologicalSplitSpec,
    CostSpec,
    DatasetHandle,
    DatasetSpec,
    FractionalBacktestSpec,
    ResearchRunSpec,
    StrategySpec,
    ValidatedDataset,
    ValidationFinding,
    ValidationReport,
)
from eth_research.api.publish import publish_bundle
from eth_research.api.receipt import RunReceipt, build_receipt, verify_run_receipt
from eth_research.api.results import ResearchResult
from eth_research.api.strategies import (
    BINARY_STRATEGY_PARAMS,
    FractionalStrategy,
    Strategy,
    build_binary_strategy,
    build_fractional_strategy,
    list_binary_strategies,
    list_fractional_strategies,
)

__all__ = [
    # contract version
    "API_VERSION",
    # enumerations
    "BINARY_COST_SCENARIOS",
    "BINARY_STRATEGY_KINDS",
    "BINARY_STRATEGY_PARAMS",
    "CONFIG_SCHEMA_VERSION",
    "ENGINES",
    "FRACTIONAL_COST_SCENARIOS",
    "FRACTIONAL_STRATEGY_KINDS",
    # error taxonomy
    "AccountingError",
    "BacktestError",
    # value models
    "BinaryBacktestSpec",
    "CanonicalDataset",
    "CanonicalDatasetArtifacts",
    "CausalityError",
    "ChronologicalSplitSpec",
    "ConfigurationError",
    "CostSpec",
    "DataSplitResult",
    "DatasetError",
    "DatasetHandle",
    "DatasetIntegrityError",
    "DatasetSchemaError",
    "DatasetSpec",
    "EthResearchError",
    "FractionalBacktestSpec",
    # strategy protocol + registry
    "FractionalStrategy",
    "OutputCollisionError",
    "ReceiptVerificationError",
    "ResearchResult",
    "ResearchRunSpec",
    "ResultValidationError",
    "RunConfig",
    "RunReceipt",
    "Strategy",
    "StrategyError",
    "StrategySpec",
    "ValidatedDataset",
    "ValidationFinding",
    "ValidationReport",
    "build_binary_strategy",
    # dataset functions
    "build_canonical_dataset",
    "build_fractional_strategy",
    # result + receipt
    "build_receipt",
    # backtest functions
    "calculate_metrics",
    "chronological_split",
    "generate_synthetic_dataset",
    "list_binary_strategies",
    "list_fractional_strategies",
    "load_canonical_dataset",
    "load_config",
    "load_config_file",
    "publish_bundle",
    "run_binary_backtest",
    "run_fractional_backtest",
    "validate_dataset",
    "verify_run_receipt",
]
