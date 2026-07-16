"""The public research-result model and its strict canonical (de)serialization.

A :class:`ResearchResult` is the immutable record of one backtest: the run description, the
dataset identity, the evaluated window, and the delegated performance metrics. Its metric
numbers come verbatim from the accepted engines (see :mod:`eth_research.api.backtest`); this
module reimplements no formula. Serialization is canonical and a fixed point, so re-running
the same inputs produces byte-identical result bytes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.api.errors import ResultValidationError
from eth_research.api.models import API_VERSION, ResearchRunSpec
from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    require_int,
    require_mapping,
    require_str,
    sha256_hex,
    strict_load_canonical,
)

__all__ = ["RESULT_SCHEMA_VERSION", "MetricValue", "ResearchResult", "build_research_result"]

RESULT_SCHEMA_VERSION = 1

MetricValue = float | int | None


def _require_metric_value(value: Any, field: str) -> MetricValue:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CanonicalError(f"{field}: a boolean is not a metric value")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalError(f"{field}: metric must be finite")
        return value
    raise CanonicalError(f"{field}: expected a number or null")


@dataclass(frozen=True)
class ResearchResult:
    """Immutable, canonical record of one research backtest run."""

    result_schema_version: int
    package_version: str
    api_version: str
    run_spec: ResearchRunSpec
    dataset_fingerprint: str
    dataset_row_count: int
    evaluated_row_count: int
    start_time: str
    end_time: str
    metrics: tuple[tuple[str, MetricValue], ...]

    def metric_map(self) -> dict[str, MetricValue]:
        return dict(self.metrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_schema_version": self.result_schema_version,
            "package_version": self.package_version,
            "api_version": self.api_version,
            "run_spec": self.run_spec.to_dict(),
            "dataset_fingerprint": self.dataset_fingerprint,
            "dataset_row_count": self.dataset_row_count,
            "evaluated_row_count": self.evaluated_row_count,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metrics": dict(self.metrics),
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def result_sha256(self) -> str:
        return sha256_hex(self.to_json_bytes())

    @classmethod
    def from_dict(cls, payload: Any) -> ResearchResult:
        try:
            data = require_mapping(payload, "research_result")
            metrics_raw = require_mapping(data.get("metrics"), "research_result.metrics")
            metrics = tuple(
                (key, _require_metric_value(metrics_raw[key], f"research_result.metrics.{key}"))
                for key in sorted(metrics_raw)
            )
            return cls(
                result_schema_version=require_int(
                    data.get("result_schema_version"), "research_result.result_schema_version"
                ),
                package_version=require_str(
                    data.get("package_version"), "research_result.package_version"
                ),
                api_version=require_str(data.get("api_version"), "research_result.api_version"),
                run_spec=ResearchRunSpec.from_dict(data.get("run_spec")),
                dataset_fingerprint=require_str(
                    data.get("dataset_fingerprint"), "research_result.dataset_fingerprint"
                ),
                dataset_row_count=require_int(
                    data.get("dataset_row_count"), "research_result.dataset_row_count"
                ),
                evaluated_row_count=require_int(
                    data.get("evaluated_row_count"), "research_result.evaluated_row_count"
                ),
                start_time=require_str(data.get("start_time"), "research_result.start_time"),
                end_time=require_str(data.get("end_time"), "research_result.end_time"),
                metrics=metrics,
            )
        except CanonicalError as exc:
            raise ResultValidationError(f"invalid research result: {exc}") from exc

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ResearchResult:
        try:
            payload = strict_load_canonical(raw, "research_result")
        except CanonicalError as exc:
            raise ResultValidationError(f"invalid research result: {exc}") from exc
        return cls.from_dict(payload)


def build_research_result(
    *,
    run_spec: ResearchRunSpec,
    dataset_fingerprint: str,
    dataset_row_count: int,
    evaluated_row_count: int,
    start_time: str,
    end_time: str,
    metrics: dict[str, MetricValue],
) -> ResearchResult:
    """Assemble a :class:`ResearchResult`, stamping the running package and API versions.

    The metric mapping is stored as a sorted tuple of pairs so the result is hashable and
    its serialization is canonical.
    """
    ordered = tuple(
        (key, _require_metric_value(metrics[key], f"metrics.{key}")) for key in sorted(metrics)
    )
    return ResearchResult(
        result_schema_version=RESULT_SCHEMA_VERSION,
        package_version=PACKAGE_VERSION,
        api_version=API_VERSION,
        run_spec=run_spec,
        dataset_fingerprint=dataset_fingerprint,
        dataset_row_count=dataset_row_count,
        evaluated_row_count=evaluated_row_count,
        start_time=start_time,
        end_time=end_time,
        metrics=ordered,
    )
