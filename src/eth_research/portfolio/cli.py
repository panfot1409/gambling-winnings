"""The offline ``portfolio`` / ``universe`` command group (Milestone 4B §29).

A small, offline, non-interactive command group stacked additively on the accepted M4A CLI
(:mod:`eth_research.cli.app`), whose argparse structure, exit-code convention, and ``--json``
determinism this module mirrors exactly. Every command builds or reads *local* evidence only:
it never contacts a network, reads a credential, emits telemetry, evaluates caller-named code,
or reads the wall clock into its output. Human text is emitted by default and deterministic
canonical JSON on ``--json``; the JSON bytes are produced by the accepted
:func:`~eth_research.api.serialization.canonical_json_bytes`, so two runs over identical inputs
print byte-identical output.

Commands (all read-only — they compute and print, they never write a file):

* ``universe inspect``   build the synthetic reference universe and print its identity
  (a summary by default; the full canonical :class:`UniverseSpec` under ``--full``).
* ``universe validate``  re-validate a canonical ``UniverseSpec`` through
  :meth:`UniverseSpec.from_mapping`. Offline this command carries only the synthetic reference
  calendars, so ``--in`` fully binds a file iff it describes the reference universe; ``--demo``
  round-trips the built-in reference universe with no file at all.
* ``portfolio demo`` (alias ``portfolio run``)  run the synthetic reference universe end to end
  (protocol + panel + membership + FX + schedule, passing the corporate-action set), compute the
  descriptive metrics, build the :class:`PortfolioResult`, and print its identity (a summary by
  default; the full canonical result under ``--full``).
* ``portfolio verify``   load a canonical :class:`PortfolioResult` through
  :meth:`PortfolioResult.from_mapping` and report its ``result_id``. The strict parse *is* the
  verification: it rejects unknown/missing keys, non-canonical bytes, NaN/Infinity, and any
  internally inconsistent total, so a file that parses is internally consistent.

Exit codes (stable, grouped like the accepted CLI): ``0`` success; ``2`` a usage error (mirrors
argparse's own code and the accepted CLI's no-subcommand return); ``4`` a failed canonical
validation / verification of a supplied artifact (a :class:`CanonicalError` — the same family code
the accepted CLI uses for bad-input-artifact failures); ``70`` an unexpected internal error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    strict_load_canonical,
)
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import build_reference_universe, reference_protocol
from eth_research.portfolio.result import PortfolioResult, build_portfolio_result
from eth_research.portfolio.universe import UniverseSpec

__all__ = ["build_parser", "main"]

# Stable process exit codes, grouped like the accepted M4A CLI (eth_research.cli.app):
_USAGE_EXIT = 2  # a usage error (mirrors argparse's own exit code and app.main's no-func return)
_VALIDATION_EXIT = 4  # a CanonicalError: a supplied artifact failed strict canonical validation
_INTERNAL_EXIT = 70  # an unexpected internal error (mirrors eth_research.cli.app)

# 365.25 days x 24 hours: the annualization basis for the reference universe's hourly cadence. The
# caller always supplies this explicitly (the engine assumes no timing); the run is hourly.
_HOURLY_PERIODS_PER_YEAR = 8766.0


# --------------------------------------------------------------------------- #
# output helpers (mirror eth_research.cli.app: human text by default, canonical JSON on --json)
# --------------------------------------------------------------------------- #
def _emit(payload: dict[str, Any], human: list[str], *, as_json: bool) -> None:
    """Write the result to stdout: canonical JSON bytes on ``--json``, else the human lines."""
    if as_json:
        sys.stdout.write(canonical_json_bytes(payload).decode("utf-8"))
    else:
        sys.stdout.write("\n".join(human) + "\n")


def _emit_error(message: str, *, as_json: bool) -> None:
    """Write a clean one-line (or canonical-JSON) error envelope to stderr; never a traceback."""
    if as_json:
        sys.stderr.write(
            canonical_json_bytes(
                {"error": "portfolio_validation_error", "message": message}
            ).decode("utf-8")
        )
    else:
        sys.stderr.write(f"error: {message}\n")


def _read_bytes(path: str, label: str) -> bytes:
    """Read a local artifact's bytes, translating a read failure into a clean validation error.

    A missing/unreadable input is caller error, not an internal bug, so it exits with the
    validation code rather than the internal one — exactly as the accepted CLI's reader does.
    """
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise CanonicalError(f"could not read {label} {path}: {exc}") from exc


def _fx_pairs(spec: UniverseSpec) -> list[list[str]]:
    """The universe's required ``(quote, base)`` FX pairs as JSON-safe two-element lists."""
    return [[quote, base] for quote, base in spec.required_fx_pairs]


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_universe_inspect(args: argparse.Namespace) -> int:
    """Build the reference universe and print its canonical spec (``--full``) or a summary."""
    spec = build_reference_universe().universe_spec
    if args.full:
        payload: dict[str, Any] = spec.canonical()
        human = [f"universe fingerprint: {spec.fingerprint}", "(full canonical UniverseSpec)"]
    else:
        payload = {
            "base_currency": spec.base_currency,
            "instrument_count": len(spec.instruments),
            "required_fx_pairs": _fx_pairs(spec),
            "fingerprint": spec.fingerprint,
        }
        human = [
            f"base currency: {spec.base_currency}",
            f"instruments: {len(spec.instruments)}",
            f"required fx pairs: {', '.join('/'.join(p) for p in _fx_pairs(spec)) or '(none)'}",
            f"fingerprint: {spec.fingerprint}",
        ]
    _emit(payload, human, as_json=args.json)
    return 0


def cmd_universe_validate(args: argparse.Namespace) -> int:
    """Re-validate a canonical ``UniverseSpec`` through :meth:`UniverseSpec.from_mapping`.

    Offline, the only calendars this command carries are the synthetic reference calendars, so
    ``--in`` fully binds a file iff it describes the reference universe (its calendar fingerprints
    match); otherwise ``from_mapping`` fails closed with a clear calendar-mismatch error. ``--demo``
    round-trips the built-in reference universe with no file.
    """
    reference = build_reference_universe()
    calendars = reference.calendars
    if args.demo:
        spec = UniverseSpec.from_mapping(reference.universe_spec.canonical(), calendars)
        origin = "synthetic reference universe"
    else:
        raw = _read_bytes(args.in_path, "universe")
        spec = UniverseSpec.from_mapping(strict_load_canonical(raw, "universe"), calendars)
        origin = args.in_path
    payload = {
        "valid": True,
        "base_currency": spec.base_currency,
        "instrument_count": len(spec.instruments),
        "required_fx_pairs": _fx_pairs(spec),
        "fingerprint": spec.fingerprint,
    }
    human = [f"validated {origin}", f"fingerprint: {spec.fingerprint}"]
    _emit(payload, human, as_json=args.json)
    return 0


def cmd_portfolio_demo(args: argparse.Namespace) -> int:
    """Run the synthetic reference universe end to end and print the result identity or summary."""
    reference = build_reference_universe()
    run_result = run_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    metrics = compute_portfolio_metrics(run_result, periods_per_year=_HOURLY_PERIODS_PER_YEAR)
    result = build_portfolio_result(run_result, metrics, reference.universe_spec)
    if args.full:
        payload: dict[str, Any] = result.canonical()
    else:
        payload = {
            "result_id": result.result_id,
            "base_currency": result.base_currency,
            "initial_equity": result.initial_equity,
            "terminal_equity": result.terminal_equity,
            "num_fills": result.num_fills,
        }
    human = [
        f"result id: {result.result_id}",
        f"terminal equity: {result.terminal_equity} {result.base_currency} "
        f"(from {result.initial_equity})",
        f"fills: {result.num_fills}",
    ]
    _emit(payload, human, as_json=args.json)
    return 0


def cmd_portfolio_verify(args: argparse.Namespace) -> int:
    """Load a canonical ``PortfolioResult`` and report its ``result_id`` (strict parse = verify)."""
    raw = _read_bytes(args.result, "result")
    result = PortfolioResult.from_mapping(strict_load_canonical(raw, "result"))
    payload = {
        "valid": True,
        "result_id": result.result_id,
        "base_currency": result.base_currency,
        "terminal_equity": result.terminal_equity,
        "num_fills": result.num_fills,
    }
    human = [f"result is valid (result_id {result.result_id})"]
    _emit(payload, human, as_json=args.json)
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit deterministic canonical JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eth-research-portfolio",
        description="Offline M4B portfolio tools: inspect/validate a universe, run/verify results.",
    )
    sub = parser.add_subparsers(dest="group")

    p_universe = sub.add_parser("universe", help="inspect or validate a research universe")
    universe_sub = p_universe.add_subparsers(dest="subcommand")

    p = universe_sub.add_parser("inspect", help="print the synthetic reference universe identity")
    p.add_argument("--full", action="store_true", help="print the full canonical UniverseSpec")
    _add_json(p)
    p.set_defaults(func=cmd_universe_inspect)

    p = universe_sub.add_parser("validate", help="re-validate a canonical UniverseSpec")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--in",
        dest="in_path",
        metavar="PATH",
        help="a canonical UniverseSpec JSON file (binds only the reference calendars offline)",
    )
    source.add_argument(
        "--demo", action="store_true", help="validate the built-in synthetic reference universe"
    )
    _add_json(p)
    p.set_defaults(func=cmd_universe_validate)

    p_portfolio = sub.add_parser("portfolio", help="run or verify a portfolio simulation")
    portfolio_sub = p_portfolio.add_subparsers(dest="subcommand")

    for name, help_text in (
        ("demo", "run the synthetic reference universe end to end"),
        ("run", "alias of 'demo': run the synthetic reference universe end to end"),
    ):
        p = portfolio_sub.add_parser(name, help=help_text)
        p.add_argument("--full", action="store_true", help="print the full canonical result")
        _add_json(p)
        p.set_defaults(func=cmd_portfolio_demo)

    p = portfolio_sub.add_parser("verify", help="verify a canonical PortfolioResult JSON file")
    p.add_argument("--result", required=True, help="path to a canonical PortfolioResult JSON file")
    _add_json(p)
    p.set_defaults(func=cmd_portfolio_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch one offline command, returning its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return _USAGE_EXIT
    as_json = bool(getattr(args, "json", False))
    try:
        exit_code: int = args.func(args)
        return exit_code
    except CanonicalError as exc:
        _emit_error(str(exc), as_json=as_json)
        return _VALIDATION_EXIT
    except Exception as exc:  # a genuine bug: report one clean line, never a traceback
        sys.stderr.write(f"internal error: {type(exc).__name__}: {exc}\n")
        return _INTERNAL_EXIT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
