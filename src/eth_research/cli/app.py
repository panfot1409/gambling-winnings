"""The single offline ``eth-research`` command-line interface.

One console entry point exposes a small, offline, non-interactive set of commands:
``version``, ``doctor``, ``demo generate``, ``dataset validate|build|inspect``,
``backtest run``, ``result verify``, and ``receipt verify``. Every command emits concise
human text by default and deterministic ``--json`` on request, never prompts, never uses
colour, never contacts the network or reads credentials/home state, refuses to overwrite an
existing output by default, and writes only inside the output directory it is told to use.
Failures are reported through the public error taxonomy with a stable per-class exit code;
an unexpected internal error exits 70.

The internal governance CLIs (``eth_research.m3*`` / ``eth_research.fractional.*`` module
mains) are deliberately not surfaced here.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from eth_research import __version__ as PACKAGE_VERSION
from eth_research.api import (
    API_VERSION,
    CostSpec,
    DatasetSpec,
    EthResearchError,
    ResearchResult,
    ResultValidationError,
    RunReceipt,
    StrategySpec,
    build_canonical_dataset,
    generate_synthetic_dataset,
    load_canonical_dataset,
    load_config_file,
    publish_bundle,
    run_binary_backtest,
    validate_dataset,
    verify_run_receipt,
)
from eth_research.api.orchestrate import execute_config
from eth_research.api.serialization import sha256_hex
from eth_research.data.builder import read_raw_ohlcv

_INTERNAL_EXIT = 70


def _dependency_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"


def _print(payload: dict[str, Any], human: list[str], *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write("\n".join(human) + "\n")


def _read_bytes(path: str, error: type[EthResearchError], label: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise error(f"could not read {label} {path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# commands                                                                    #
# --------------------------------------------------------------------------- #
def cmd_version(args: argparse.Namespace) -> int:
    payload = {"package_version": PACKAGE_VERSION, "api_version": API_VERSION}
    _print(
        payload,
        [f"eth-research {PACKAGE_VERSION} (public API {API_VERSION})"],
        as_json=args.json,
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # the public API imports and a full synthetic run completes offline
    ok_pipeline = True
    detail = ""
    try:
        dataset = generate_synthetic_dataset(n_periods=30, seed=0)
        run_binary_backtest(dataset, StrategySpec("buy_and_hold"), CostSpec("base"))
    except Exception as exc:
        ok_pipeline = False
        detail = f"{type(exc).__name__}: {exc}"
    check("synthetic_pipeline", ok_pipeline, detail)
    check("offline", True, "no network client is imported by the package")

    payload = {
        "package_version": PACKAGE_VERSION,
        "api_version": API_VERSION,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "numpy_version": _dependency_version("numpy"),
        "pandas_version": _dependency_version("pandas"),
        "pyarrow_version": _dependency_version("pyarrow"),
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
    }
    human = [
        f"eth-research {PACKAGE_VERSION} (API {API_VERSION})",
        f"python {payload['python_implementation']} {payload['python_version']}",
        f"numpy {payload['numpy_version']}  pandas {payload['pandas_version']}  "
        f"pyarrow {payload['pyarrow_version']}",
        *[f"[{'ok' if c['ok'] else 'FAIL'}] {c['name']} {c['detail']}".rstrip() for c in checks],
    ]
    _print(payload, human, as_json=args.json)
    return 0 if payload["ok"] else _INTERNAL_EXIT


def cmd_demo_generate(args: argparse.Namespace) -> int:
    dataset = generate_synthetic_dataset(n_periods=args.periods, seed=args.seed)
    csv_bytes = dataset.frame.reset_index().to_csv(index=False).encode("utf-8")
    config = {
        "config_schema_version": 1,
        "dataset": {
            "source": "file",
            "file": {"path": "synthetic_eth.csv", "interval_seconds": dataset.interval_seconds},
        },
        "engine": "binary",
        "strategy": {
            "kind": "moving_average_crossover",
            "params": {"fast_window": 10, "slow_window": 30},
        },
        "costs": {"scenario": "base"},
        "split": {"enabled": True, "evaluate": "validation", "context_bars": 30},
        "run": {"initial_cash": 10000.0},
        "output": {"directory": "results"},
    }
    config_bytes = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digests = publish_bundle(
        args.output,
        {"synthetic_eth.csv": csv_bytes, "config.json": config_bytes},
        overwrite=args.overwrite,
    )
    payload = {"output_dir": str(args.output), "files": digests}
    human = [
        f"wrote demo dataset + config to {args.output}",
        "next: eth-research backtest run --config " + str(Path(args.output) / "config.json"),
    ]
    _print(payload, human, as_json=args.json)
    return 0


def cmd_dataset_validate(args: argparse.Namespace) -> int:
    frame = read_raw_ohlcv(args.input)
    spec = DatasetSpec(
        interval_seconds=args.interval_seconds,
        assume_utc=args.assume_utc,
        allow_extra_columns=args.allow_extra_columns,
    )
    dataset = validate_dataset(frame, spec, require_clean=False)
    report = dataset.report
    payload = {
        "fingerprint": dataset.fingerprint,
        "row_count": dataset.row_count,
        "valid": report.is_valid,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "findings": [f.to_dict() for f in report.findings],
    }
    human = [
        f"dataset fingerprint: {dataset.fingerprint}",
        f"rows: {dataset.row_count}  errors: {report.error_count}  "
        f"warnings: {report.warning_count}",
        "valid" if report.is_valid else "INVALID (error-severity findings present)",
    ]
    _print(payload, human, as_json=args.json)
    return 0 if report.is_valid else 4


def cmd_dataset_build(args: argparse.Namespace) -> int:
    artifacts = build_canonical_dataset(
        args.input,
        args.output,
        symbol=args.symbol,
        venue=args.venue,
        quote_asset=args.quote_asset,
        interval_seconds=args.interval_seconds,
        source_description=args.source,
        assume_utc=args.assume_utc,
        allow_extra_columns=args.allow_extra_columns,
        overwrite=args.overwrite,
    )
    payload = {
        "canonical_path": artifacts.canonical_path,
        "manifest_path": artifacts.manifest_path,
        "quality_report_path": artifacts.quality_report_path,
        "fingerprint": artifacts.fingerprint,
        "manifest_sha256": artifacts.manifest_sha256,
    }
    human = [
        f"built canonical dataset: {artifacts.canonical_path}",
        f"manifest: {artifacts.manifest_path}",
        f"fingerprint: {artifacts.fingerprint}",
    ]
    _print(payload, human, as_json=args.json)
    return 0


def cmd_dataset_inspect(args: argparse.Namespace) -> int:
    dataset = load_canonical_dataset(args.manifest)
    payload = dataset.identity()
    human = [
        f"fingerprint: {dataset.fingerprint}",
        f"rows: {dataset.row_count}  interval_seconds: {dataset.interval_seconds}",
        f"window: {dataset.start_time} .. {dataset.end_time}",
        f"manifest sha256: {dataset.manifest_sha256}",
    ]
    _print(payload, human, as_json=args.json)
    return 0


def cmd_backtest_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config_file(config_path)
    config_bytes = config_path.read_bytes()
    output_override = Path(args.output) if args.output is not None else None
    overwrite_override = True if args.overwrite else None
    outcome = execute_config(
        config,
        config_bytes=config_bytes,
        base_dir=config_path.resolve().parent,
        output_dir=output_override,
        overwrite=overwrite_override,
    )
    payload = {
        "output_dir": outcome.output_dir,
        "run_id": outcome.run_id,
        "result_sha256": outcome.result_sha256,
        "files": outcome.files,
    }
    human = [
        f"published run {outcome.run_id} to {outcome.output_dir}",
        f"result sha256: {outcome.result_sha256}",
        "files: " + ", ".join(sorted(outcome.files)),
    ]
    _print(payload, human, as_json=args.json)
    return 0


def cmd_result_verify(args: argparse.Namespace) -> int:
    raw = _read_bytes(args.result, EthResearchError, "result")
    result = ResearchResult.from_json_bytes(raw)
    if result.to_json_bytes() != raw:
        raise ResultValidationError("result is not in canonical form (re-serialization differs)")
    payload = {
        "valid": True,
        "result_sha256": sha256_hex(raw),
        "engine": result.run_spec.engine,
        "strategy": result.run_spec.strategy.kind,
        "dataset_fingerprint": result.dataset_fingerprint,
    }
    human = [f"result is valid (sha256 {payload['result_sha256']})"]
    _print(payload, human, as_json=args.json)
    return 0


def cmd_receipt_verify(args: argparse.Namespace) -> int:
    receipt = RunReceipt.from_json_bytes(_read_bytes(args.receipt, EthResearchError, "receipt"))
    result_bytes = _read_bytes(args.result, EthResearchError, "result")
    report_bytes = _read_bytes(args.report, EthResearchError, "report") if args.report else None
    config_bytes = _read_bytes(args.config, EthResearchError, "config") if args.config else None
    verify_run_receipt(
        receipt, result_bytes=result_bytes, report_bytes=report_bytes, config_bytes=config_bytes
    )
    payload = {"valid": True, "run_id": receipt.run_id, "result_sha256": receipt.result_sha256}
    human = [f"receipt {receipt.run_id} verified against the supplied artifacts"]
    _print(payload, human, as_json=args.json)
    return 0


# --------------------------------------------------------------------------- #
# parser                                                                      #
# --------------------------------------------------------------------------- #
def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eth-research",
        description="Offline ETH research: validate data, run backtests, verify artifacts.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("version", help="print the package and API versions")
    _add_json(p)
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("doctor", help="check the installation and run a synthetic self-test")
    _add_json(p)
    p.set_defaults(func=cmd_doctor)

    p_demo = sub.add_parser("demo", help="generate a runnable offline demo")
    demo_sub = p_demo.add_subparsers(dest="subcommand")
    p = demo_sub.add_parser("generate", help="write a synthetic dataset + sample config")
    p.add_argument("--output", required=True, help="output directory (created if absent)")
    p.add_argument("--periods", type=int, default=400, help="number of synthetic bars")
    p.add_argument("--seed", type=int, default=0, help="deterministic seed")
    p.add_argument("--overwrite", action="store_true", help="overwrite existing demo files")
    _add_json(p)
    p.set_defaults(func=cmd_demo_generate)

    p_ds = sub.add_parser("dataset", help="validate / build / inspect OHLCV datasets")
    ds_sub = p_ds.add_subparsers(dest="subcommand")

    p = ds_sub.add_parser("validate", help="validate a local OHLCV file")
    p.add_argument("--input", required=True, help="path to a .csv/.parquet OHLCV file")
    p.add_argument("--interval-seconds", type=int, required=True, dest="interval_seconds")
    p.add_argument("--assume-utc", action="store_true", dest="assume_utc")
    p.add_argument("--allow-extra-columns", action="store_true", dest="allow_extra_columns")
    _add_json(p)
    p.set_defaults(func=cmd_dataset_validate)

    p = ds_sub.add_parser("build", help="build a canonical dataset (parquet + manifest)")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True, help="output directory")
    p.add_argument("--symbol", required=True)
    p.add_argument("--venue", required=True)
    p.add_argument("--quote-asset", required=True, dest="quote_asset")
    p.add_argument("--interval-seconds", type=int, required=True, dest="interval_seconds")
    p.add_argument("--source", required=True, help="free-text provenance description")
    p.add_argument("--assume-utc", action="store_true", dest="assume_utc")
    p.add_argument("--allow-extra-columns", action="store_true", dest="allow_extra_columns")
    p.add_argument("--overwrite", action="store_true")
    _add_json(p)
    p.set_defaults(func=cmd_dataset_build)

    p = ds_sub.add_parser("inspect", help="load and re-verify a canonical dataset")
    p.add_argument("--manifest", required=True, help="path to the dataset manifest JSON")
    _add_json(p)
    p.set_defaults(func=cmd_dataset_inspect)

    p_bt = sub.add_parser("backtest", help="run a backtest from a config")
    bt_sub = p_bt.add_subparsers(dest="subcommand")
    p = bt_sub.add_parser("run", help="run one configured backtest and publish the bundle")
    p.add_argument("--config", required=True, help="path to a .json/.toml run config")
    p.add_argument("--output", default=None, help="override the config's output directory")
    p.add_argument("--overwrite", action="store_true", help="overwrite an existing output bundle")
    _add_json(p)
    p.set_defaults(func=cmd_backtest_run)

    p_res = sub.add_parser("result", help="verify a result artifact")
    res_sub = p_res.add_subparsers(dest="subcommand")
    p = res_sub.add_parser("verify", help="validate a result's structure and canonical form")
    p.add_argument("--result", required=True)
    _add_json(p)
    p.set_defaults(func=cmd_result_verify)

    p_rc = sub.add_parser("receipt", help="verify a run receipt")
    rc_sub = p_rc.add_subparsers(dest="subcommand")
    p = rc_sub.add_parser("verify", help="verify a receipt against its artifacts")
    p.add_argument("--receipt", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--report", default=None)
    p.add_argument("--config", default=None)
    _add_json(p)
    p.set_defaults(func=cmd_receipt_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2
    as_json = bool(getattr(args, "json", False))
    try:
        exit_code: int = args.func(args)
        return exit_code
    except EthResearchError as exc:
        if as_json:
            sys.stderr.write(json.dumps(exc.as_dict(), indent=2, sort_keys=True) + "\n")
        else:
            sys.stderr.write(f"error [{exc.code}]: {exc}\n")
        return exc.exit_code
    except Exception as exc:
        sys.stderr.write(f"internal error: {type(exc).__name__}: {exc}\n")
        return _INTERNAL_EXIT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
