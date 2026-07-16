"""Execute a :class:`RunConfig` end to end and publish a deterministic output bundle.

This is the one place that turns a validated configuration into artifacts on disk: it
resolves the dataset (deterministic synthetic generator or a local file), optionally splits
it and selects an evaluation segment with a warm-up context, runs the accepted engine through
the public API, renders a deterministic report, builds the tamper-evident receipt, and
publishes ``result.json`` / ``report.md`` / ``receipt.json`` / ``manifest.json`` transactionally
(``manifest.json`` last). It never contacts the network and writes nothing outside the
resolved output directory. A local file source is confined to ``base_dir`` and can never point
at the governed ``research/`` roots — the config parser already refuses such paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.api.backtest import run_binary_backtest, run_fractional_backtest
from eth_research.api.config import DatasetConfig, RunConfig, SplitConfig
from eth_research.api.dataset import (
    chronological_split,
    generate_synthetic_dataset,
    validate_dataset,
)
from eth_research.api.errors import ConfigurationError, DatasetError
from eth_research.api.models import (
    API_VERSION,
    ChronologicalSplitSpec,
    DatasetHandle,
    DatasetSpec,
    ValidatedDataset,
)
from eth_research.api.publish import publish_bundle
from eth_research.api.receipt import RunReceipt, build_receipt
from eth_research.api.results import ResearchResult
from eth_research.api.serialization import canonical_json_bytes, sha256_hex
from eth_research.data.builder import read_raw_ohlcv

__all__ = ["MANIFEST_SCHEMA_VERSION", "RunOutcome", "execute_config", "render_report"]

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunOutcome:
    """What :func:`execute_config` produced: where, the run id, and the bundle digests."""

    output_dir: str
    run_id: str
    result_sha256: str
    receipt: RunReceipt
    files: dict[str, str]


def _load_dataset(dataset: DatasetConfig, base_dir: Path) -> ValidatedDataset:
    if dataset.source == "synthetic":
        synthetic = dataset.synthetic
        if synthetic is None:  # pragma: no cover - guaranteed by the parser
            raise ConfigurationError("dataset: synthetic source without a synthetic block")
        return generate_synthetic_dataset(
            n_periods=synthetic.n_periods,
            interval=synthetic.interval,
            start=synthetic.start,
            start_price=synthetic.start_price,
            drift=synthetic.drift,
            volatility=synthetic.volatility,
            seed=synthetic.seed,
        )
    file_cfg = dataset.file
    if file_cfg is None:  # pragma: no cover - guaranteed by the parser
        raise ConfigurationError("dataset: file source without a file block")
    # Confine the *resolved* path within base_dir: the textual guard already rejects a
    # literal ``research/`` / ``..`` / absolute path, but a symlink whose name is innocuous
    # could still point the reader at the governed roots or the sealed holdout. Resolving and
    # requiring containment refuses that escape.
    base_resolved = base_dir.resolve()
    resolved = (base_dir / file_cfg.path).resolve()
    if not resolved.is_relative_to(base_resolved):
        raise DatasetError(
            f"dataset file path escapes the configuration directory: {file_cfg.path}"
        )
    try:
        frame = read_raw_ohlcv(resolved)
    except (OSError, ValueError, TypeError) as exc:
        raise DatasetError(f"could not read dataset file {file_cfg.path}: {exc}") from exc
    spec = DatasetSpec(
        interval_seconds=file_cfg.interval_seconds,
        assume_utc=file_cfg.assume_utc,
        allow_extra_columns=file_cfg.allow_extra_columns,
    )
    return validate_dataset(frame, spec)


def _select_segment(
    dataset: ValidatedDataset, split: SplitConfig
) -> tuple[DatasetHandle, DatasetHandle | None, ChronologicalSplitSpec | None]:
    if not split.enabled:
        return dataset, None, None
    spec = ChronologicalSplitSpec(
        train_fraction=split.train_fraction, validation_fraction=split.validation_fraction
    )
    splits = chronological_split(dataset, spec)
    if split.evaluate == "train":
        return splits.train, None, spec
    if split.evaluate == "validation":
        context = splits.validation_context(split.context_bars) if split.context_bars > 0 else None
        return splits.validation, context, spec
    context = splits.test_context(split.context_bars) if split.context_bars > 0 else None
    return splits.test, context, spec


def render_report(result: ResearchResult) -> str:
    """A deterministic Markdown report for one run (no wall-clock or host identity)."""
    spec = result.run_spec
    params = spec.strategy.param_dict()
    param_str = ", ".join(f"{k}={v}" for k, v in sorted(params.items())) or "(none)"
    lines = [
        "# Research run report",
        "",
        f"- engine: `{spec.engine}`",
        f"- strategy: `{spec.strategy.kind}` (params: {param_str})",
        f"- cost scenario: `{spec.cost.scenario}`",
        f"- initial cash: {spec.initial_cash}",
        f"- risk-free rate: {spec.risk_free_rate}",
        f"- dataset fingerprint: `{result.dataset_fingerprint}`",
        f"- evaluated window: {result.start_time} .. {result.end_time} "
        f"({result.evaluated_row_count} bars)",
        f"- package version: {result.package_version} (API {result.api_version})",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in result.metrics)
    return "\n".join(lines) + "\n"


def execute_config(
    config: RunConfig,
    *,
    config_bytes: bytes,
    base_dir: Path,
    output_dir: Path | None = None,
    overwrite: bool | None = None,
) -> RunOutcome:
    """Run ``config`` and publish its output bundle; return a :class:`RunOutcome`."""
    dataset = _load_dataset(config.dataset, base_dir)
    evaluated, context, split_spec = _select_segment(dataset, config.split)

    if config.engine == "binary":
        result = run_binary_backtest(
            evaluated,
            config.strategy,
            config.costs,
            initial_cash=config.run.initial_cash,
            context=context,
            risk_free_rate=config.run.risk_free_rate,
            split=split_spec,
        )
    else:
        result = run_fractional_backtest(
            evaluated,
            config.strategy,
            config.costs,
            initial_cash=config.run.initial_cash,
            context=context,
            risk_free_rate=config.run.risk_free_rate,
            split=split_spec,
        )

    result_bytes = result.to_json_bytes()
    report_bytes = render_report(result).encode("utf-8") if config.output.write_report else None
    receipt = build_receipt(result_bytes, report_bytes=report_bytes, config_bytes=config_bytes)
    receipt_bytes = receipt.to_json_bytes()

    files: dict[str, bytes] = {"result.json": result_bytes}
    if report_bytes is not None:
        files["report.md"] = report_bytes
    files["receipt.json"] = receipt_bytes
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": receipt.run_id,
        "package_version": PACKAGE_VERSION,
        "api_version": API_VERSION,
        "files": {name: sha256_hex(data) for name, data in sorted(files.items())},
    }
    files["manifest.json"] = canonical_json_bytes(manifest)

    if output_dir is not None:
        resolved_out = output_dir
    else:
        candidate = base_dir / config.output.directory
        if not candidate.resolve().is_relative_to(base_dir.resolve()):
            raise ConfigurationError(
                f"output directory escapes the configuration directory: {config.output.directory}"
            )
        resolved_out = candidate
    effective_overwrite = config.output.overwrite if overwrite is None else overwrite
    digests = publish_bundle(
        resolved_out, files, overwrite=effective_overwrite, completeness_marker="manifest.json"
    )
    return RunOutcome(
        output_dir=str(resolved_out),
        run_id=receipt.run_id,
        result_sha256=sha256_hex(result_bytes),
        receipt=receipt,
        files=digests,
    )
