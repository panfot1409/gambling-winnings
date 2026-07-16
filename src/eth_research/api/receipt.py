"""The deterministic run receipt: a tamper-evident binding over one research run's artifacts.

A :class:`RunReceipt` is generated *after* the result bytes are finalized and read back. It
binds the schema/package/API versions, the immutable research inputs (engine, dataset
fingerprint, strategy identity + fixed params, cost scenario, run parameters), the SHA-256 of
each produced artifact (result, and optionally report / config / dataset manifest), the
running Python and numeric-dependency versions, and a deterministic ``run_id`` derived from
the immutable inputs alone (so the same research inputs yield the same id on any machine).

It deliberately records **no** credential, wallet, key, absolute path, hostname, username, IP,
wall-clock time, environment dump, or command string.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.api.errors import ReceiptVerificationError
from eth_research.api.models import API_VERSION, StrategySpec
from eth_research.api.results import ResearchResult
from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_finite_float,
    require_int,
    require_mapping,
    require_sha256_hex,
    require_str,
    sha256_hex,
    strict_load_canonical,
)

__all__ = ["RECEIPT_SCHEMA_VERSION", "RunReceipt", "build_receipt", "verify_run_receipt"]

RECEIPT_SCHEMA_VERSION = 1


def _dependency_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - dependency always installed at runtime
        return "unknown"


def _run_id(
    *,
    engine: str,
    dataset_fingerprint: str,
    strategy: StrategySpec,
    cost_scenario: str,
    initial_cash: float,
    context_bars: int,
    risk_free_rate: float,
) -> str:
    identity = {
        "run_identity_v1": {
            "engine": engine,
            "dataset_fingerprint": dataset_fingerprint,
            "strategy": strategy.to_dict(),
            "cost_scenario": cost_scenario,
            "initial_cash": initial_cash,
            "context_bars": context_bars,
            "risk_free_rate": risk_free_rate,
        }
    }
    return sha256_hex(canonical_json_bytes(identity))


@dataclass(frozen=True)
class RunReceipt:
    """A canonical, tamper-evident receipt binding one research run's artifacts and inputs."""

    receipt_schema_version: int
    package_version: str
    api_version: str
    run_id: str
    engine: str
    strategy: StrategySpec
    cost_scenario: str
    initial_cash: float
    context_bars: int
    risk_free_rate: float
    dataset_fingerprint: str
    dataset_manifest_sha256: str | None
    result_sha256: str
    report_sha256: str | None
    config_sha256: str | None
    python_implementation: str
    python_version: str
    numpy_version: str
    pandas_version: str
    pyarrow_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_schema_version": self.receipt_schema_version,
            "package_version": self.package_version,
            "api_version": self.api_version,
            "run_id": self.run_id,
            "engine": self.engine,
            "strategy": self.strategy.to_dict(),
            "cost_scenario": self.cost_scenario,
            "initial_cash": self.initial_cash,
            "context_bars": self.context_bars,
            "risk_free_rate": self.risk_free_rate,
            "dataset_fingerprint": self.dataset_fingerprint,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "result_sha256": self.result_sha256,
            "report_sha256": self.report_sha256,
            "config_sha256": self.config_sha256,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "numpy_version": self.numpy_version,
            "pandas_version": self.pandas_version,
            "pyarrow_version": self.pyarrow_version,
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def receipt_sha256(self) -> str:
        return sha256_hex(self.to_json_bytes())

    @classmethod
    def from_dict(cls, payload: Any) -> RunReceipt:
        try:
            data = require_mapping(payload, "run_receipt")

            def opt_hex(key: str) -> str | None:
                value = data.get(key)
                return None if value is None else require_sha256_hex(value, f"run_receipt.{key}")

            return cls(
                receipt_schema_version=require_int(
                    data.get("receipt_schema_version"), "run_receipt.receipt_schema_version"
                ),
                package_version=require_str(
                    data.get("package_version"), "run_receipt.package_version"
                ),
                api_version=require_str(data.get("api_version"), "run_receipt.api_version"),
                run_id=require_sha256_hex(data.get("run_id"), "run_receipt.run_id"),
                engine=require_str(data.get("engine"), "run_receipt.engine"),
                strategy=StrategySpec.from_dict(data.get("strategy")),
                cost_scenario=require_str(data.get("cost_scenario"), "run_receipt.cost_scenario"),
                initial_cash=require_finite_float(
                    data.get("initial_cash"), "run_receipt.initial_cash"
                ),
                context_bars=require_int(data.get("context_bars"), "run_receipt.context_bars"),
                risk_free_rate=require_finite_float(
                    data.get("risk_free_rate"), "run_receipt.risk_free_rate"
                ),
                dataset_fingerprint=require_str(
                    data.get("dataset_fingerprint"), "run_receipt.dataset_fingerprint"
                ),
                dataset_manifest_sha256=opt_hex("dataset_manifest_sha256"),
                result_sha256=require_sha256_hex(
                    data.get("result_sha256"), "run_receipt.result_sha256"
                ),
                report_sha256=opt_hex("report_sha256"),
                config_sha256=opt_hex("config_sha256"),
                python_implementation=require_str(
                    data.get("python_implementation"), "run_receipt.python_implementation"
                ),
                python_version=require_str(
                    data.get("python_version"), "run_receipt.python_version"
                ),
                numpy_version=require_str(data.get("numpy_version"), "run_receipt.numpy_version"),
                pandas_version=require_str(
                    data.get("pandas_version"), "run_receipt.pandas_version"
                ),
                pyarrow_version=require_str(
                    data.get("pyarrow_version"), "run_receipt.pyarrow_version"
                ),
            )
        except CanonicalError as exc:
            raise ReceiptVerificationError(f"invalid run receipt: {exc}") from exc

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> RunReceipt:
        try:
            payload = strict_load_canonical(raw, "run_receipt")
        except CanonicalError as exc:
            raise ReceiptVerificationError(f"invalid run receipt: {exc}") from exc
        return cls.from_dict(payload)


def build_receipt(
    result_bytes: bytes,
    *,
    dataset_manifest_sha256: str | None = None,
    report_bytes: bytes | None = None,
    config_bytes: bytes | None = None,
) -> RunReceipt:
    """Build a receipt from the finalized result bytes read back from their sink.

    The receipt binds the SHA-256 of exactly the bytes passed in, so it must be generated
    only after the result (and any report/config) have been written and read back.
    """
    result = ResearchResult.from_json_bytes(result_bytes)
    spec = result.run_spec
    return RunReceipt(
        receipt_schema_version=RECEIPT_SCHEMA_VERSION,
        package_version=PACKAGE_VERSION,
        api_version=API_VERSION,
        run_id=_run_id(
            engine=spec.engine,
            dataset_fingerprint=result.dataset_fingerprint,
            strategy=spec.strategy,
            cost_scenario=spec.cost.scenario,
            initial_cash=spec.initial_cash,
            context_bars=spec.context_bars,
            risk_free_rate=spec.risk_free_rate,
        ),
        engine=spec.engine,
        strategy=spec.strategy,
        cost_scenario=spec.cost.scenario,
        initial_cash=spec.initial_cash,
        context_bars=spec.context_bars,
        risk_free_rate=spec.risk_free_rate,
        dataset_fingerprint=result.dataset_fingerprint,
        dataset_manifest_sha256=dataset_manifest_sha256,
        result_sha256=sha256_hex(result_bytes),
        report_sha256=sha256_hex(report_bytes) if report_bytes is not None else None,
        config_sha256=sha256_hex(config_bytes) if config_bytes is not None else None,
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        numpy_version=_dependency_version("numpy"),
        pandas_version=_dependency_version("pandas"),
        pyarrow_version=_dependency_version("pyarrow"),
    )


def _require_match(what: str, expected: object, actual: object) -> None:
    if expected != actual:
        raise ReceiptVerificationError(
            f"{what} does not match (receipt {expected!r} != {actual!r})"
        )


def verify_run_receipt(
    receipt: RunReceipt,
    *,
    result_bytes: bytes,
    report_bytes: bytes | None = None,
    config_bytes: bytes | None = None,
) -> None:
    """Re-check a receipt against the artifacts it claims to bind. Raises on any mismatch.

    Verifies the artifact digests, that the receipt's recorded research identity matches the
    result it points at, and that the deterministic ``run_id`` recomputes from the receipt's
    own fields. Environment versions are recorded facts and are not re-checked against the
    verifying machine.
    """
    _require_match("result SHA-256", receipt.result_sha256, sha256_hex(result_bytes))

    computed_report = sha256_hex(report_bytes) if report_bytes is not None else None
    _require_match("report SHA-256", receipt.report_sha256, computed_report)

    computed_config = sha256_hex(config_bytes) if config_bytes is not None else None
    _require_match("config SHA-256", receipt.config_sha256, computed_config)

    result = ResearchResult.from_json_bytes(result_bytes)
    spec = result.run_spec
    _require_match("engine", receipt.engine, spec.engine)
    _require_match("strategy", receipt.strategy, spec.strategy)
    _require_match("cost scenario", receipt.cost_scenario, spec.cost.scenario)
    _require_match("initial cash", receipt.initial_cash, spec.initial_cash)
    _require_match("context bars", receipt.context_bars, spec.context_bars)
    _require_match("risk-free rate", receipt.risk_free_rate, spec.risk_free_rate)
    _require_match("dataset fingerprint", receipt.dataset_fingerprint, result.dataset_fingerprint)

    recomputed = _run_id(
        engine=receipt.engine,
        dataset_fingerprint=receipt.dataset_fingerprint,
        strategy=receipt.strategy,
        cost_scenario=receipt.cost_scenario,
        initial_cash=receipt.initial_cash,
        context_bars=receipt.context_bars,
        risk_free_rate=receipt.risk_free_rate,
    )
    _require_match("run id", receipt.run_id, recomputed)
