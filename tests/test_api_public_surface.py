"""The public API surface, error taxonomy, models, and strict serialization."""

from __future__ import annotations

import pytest

from eth_research import api
from eth_research.api import errors as api_errors
from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_finite_float,
    require_int,
    strict_load_canonical,
)

# --------------------------------------------------------------------------- #
# surface                                                                     #
# --------------------------------------------------------------------------- #


def test_all_names_are_importable_and_exported() -> None:
    for name in api.__all__:
        assert hasattr(api, name), f"{name} in __all__ but missing from module"
    # __all__ is unique
    assert len(api.__all__) == len(set(api.__all__))


def test_no_live_trading_symbols_leak() -> None:
    forbidden = ("exchange", "wallet", "order", "leverage", "broker", "credential", "api_key")
    for name in dir(api):
        lowered = name.lower()
        assert not any(bad in lowered for bad in forbidden), name


# --------------------------------------------------------------------------- #
# error taxonomy                                                              #
# --------------------------------------------------------------------------- #

_ERROR_CLASSES = [
    api.EthResearchError,
    api.ConfigurationError,
    api.DatasetError,
    api.DatasetSchemaError,
    api.DatasetIntegrityError,
    api.StrategyError,
    api.BacktestError,
    api.AccountingError,
    api.CausalityError,
    api.ResultValidationError,
    api.ReceiptVerificationError,
    api.OutputCollisionError,
]


def test_every_error_has_a_unique_code() -> None:
    codes = [cls.code for cls in _ERROR_CLASSES]
    assert len(codes) == len(set(codes))
    for cls in _ERROR_CLASSES:
        assert cls.category in ("error", "input", "execution", "verification", "output")
        assert isinstance(cls.exit_code, int)
        assert cls.exit_code >= 1


def test_error_hierarchy() -> None:
    assert issubclass(api.DatasetSchemaError, api.DatasetError)
    assert issubclass(api.DatasetIntegrityError, api.DatasetError)
    assert issubclass(api.DatasetError, api.EthResearchError)
    assert issubclass(api.AccountingError, api.BacktestError)
    assert issubclass(api.CausalityError, api.BacktestError)
    for cls in _ERROR_CLASSES:
        assert issubclass(cls, api.EthResearchError)


def test_exit_codes_are_grouped_by_family() -> None:
    assert api.ConfigurationError.exit_code == 3
    assert api.DatasetError.exit_code == api.DatasetSchemaError.exit_code == 4
    assert api.StrategyError.exit_code == 5
    assert api.BacktestError.exit_code == api.AccountingError.exit_code == 6
    assert api.ResultValidationError.exit_code == 7
    assert api.ReceiptVerificationError.exit_code == 8
    assert api.OutputCollisionError.exit_code == 9


def test_error_envelope_is_stable() -> None:
    exc = api.StrategyError("nope")
    assert exc.as_dict() == {"error": "strategy_error", "category": "input", "message": "nope"}


def test_errors_module_all_matches_taxonomy() -> None:
    exported = set(api_errors.__all__)
    assert exported == {cls.__name__ for cls in _ERROR_CLASSES}


# --------------------------------------------------------------------------- #
# serialization strictness                                                    #
# --------------------------------------------------------------------------- #


def test_canonical_bytes_are_sorted_and_newline_terminated() -> None:
    raw = canonical_json_bytes({"b": 1, "a": 2})
    assert raw == b'{\n  "a": 2,\n  "b": 1\n}\n'


def test_canonical_bytes_reject_non_finite() -> None:
    with pytest.raises(CanonicalError):
        canonical_json_bytes({"x": float("inf")})


def test_strict_load_rejects_duplicate_keys() -> None:
    with pytest.raises(CanonicalError):
        strict_load_canonical(b'{"a": 1, "a": 2}\n', "x")


def test_strict_load_requires_trailing_newline() -> None:
    with pytest.raises(CanonicalError):
        strict_load_canonical(b'{"a": 1}', "x")


def test_strict_load_rejects_non_finite_number() -> None:
    with pytest.raises(CanonicalError):
        strict_load_canonical(b'{"a": 1e999}\n', "x")


def test_require_int_rejects_bool() -> None:
    with pytest.raises(CanonicalError):
        require_int(True, "x")


def test_require_finite_float_rejects_int_and_bool() -> None:
    with pytest.raises(CanonicalError):
        require_finite_float(3, "x")
    with pytest.raises(CanonicalError):
        require_finite_float(True, "x")
    assert require_finite_float(3.5, "x") == 3.5


# --------------------------------------------------------------------------- #
# model round-trips + strictness                                              #
# --------------------------------------------------------------------------- #


def test_strategy_spec_roundtrip_and_ordering() -> None:
    spec = api.StrategySpec.create("moving_average_crossover", slow_window=50, fast_window=20)
    # params sorted deterministically regardless of kwargs order
    assert spec.params == (("fast_window", 20), ("slow_window", 50))
    assert api.StrategySpec.from_dict(spec.to_dict()) == spec


def test_cost_and_split_and_dataset_specs_roundtrip() -> None:
    assert api.CostSpec.from_dict(api.CostSpec("base").to_dict()) == api.CostSpec("base")
    split = api.ChronologicalSplitSpec(0.5, 0.25)
    assert api.ChronologicalSplitSpec.from_dict(split.to_dict()) == split
    ds = api.DatasetSpec(interval_seconds=86400, assume_utc=True)
    assert api.DatasetSpec.from_dict(ds.to_dict()) == ds


def test_split_spec_rejects_out_of_range() -> None:
    with pytest.raises(CanonicalError):
        api.ChronologicalSplitSpec(0.7, 0.4)  # sums to > 1
    with pytest.raises(CanonicalError):
        api.ChronologicalSplitSpec(0.0, 0.2)  # not > 0


def test_research_run_spec_roundtrip() -> None:
    spec = api.ResearchRunSpec(
        engine="binary",
        dataset=api.DatasetSpec(interval_seconds=86400),
        strategy=api.StrategySpec("buy_and_hold"),
        cost=api.CostSpec("base"),
        initial_cash=10_000.0,
        context_bars=0,
        risk_free_rate=0.0,
        split=api.ChronologicalSplitSpec(),
    )
    assert api.ResearchRunSpec.from_dict(spec.to_dict()) == spec


def test_research_run_spec_rejects_unknown_engine() -> None:
    with pytest.raises(CanonicalError):
        api.ResearchRunSpec(
            engine="quantum",
            dataset=api.DatasetSpec(interval_seconds=86400),
            strategy=api.StrategySpec("cash"),
            cost=api.CostSpec("base"),
            initial_cash=10_000.0,
            context_bars=0,
            risk_free_rate=0.0,
        )
