"""Run the paper operator as a process.

    python -m eth_research.operate --interval 3 --bars 1200

Cockpit reporting is switched on by the environment and by nothing else:

    NARDIS_COCKPIT_URL   where Cockpit is           (read by the telemetry client)
    NARDIS_BOT_API_KEY   this bot's ingest key      (read by the telemetry client)

With neither set — or with ``NARDIS_TELEMETRY_ENABLED=false``, or with the optional
``nardis-telemetry`` client simply not installed — the process runs exactly the same loop and says
so once in its log. There is no flag here that turns Cockpit on: monitoring is an operator's
deployment decision, not a trading parameter.

The log format is the standard ``asctime`` one, one ``bar N`` line per iteration, so an operator
(or the Cockpit acceptance harness) can measure this loop's cadence from the trader's own clock.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from types import FrameType

from eth_research.cockpit.client import build_client
from eth_research.cockpit.config import CockpitConfig
from eth_research.cockpit.heartbeat import HeartbeatWorker
from eth_research.cockpit.reporter import STARTUP_FAILED_CODE, CockpitReporter
from eth_research.operate.paper import (
    DEFAULT_BACKFILL_BARS,
    DEFAULT_BAR_SECONDS,
    DEFAULT_MAX_BARS,
    DEFAULT_STARTING_CASH,
    SUPPORTED_CANDIDATE_IDS,
    OperatorConfig,
    OperatorError,
    run_operator,
)
from eth_research.shadow.domain import SHADOW_MODES, SYNTHETIC_DEMO
from eth_research.v2.candidates import MEANREV_SPEC
from eth_research.v2.strict import V2ValidationError

log = logging.getLogger("eth_research.operate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eth_research.operate",
        description=(
            "Run the signal-only shadow platform as a paced paper-trading process. "
            "Places no order, holds no credential, connects to no venue, moves no money."
        ),
    )
    parser.add_argument(
        "--candidate",
        default=MEANREV_SPEC.candidate_id,
        choices=sorted(SUPPORTED_CANDIDATE_IDS),
        help="Pre-registered candidate whose causal signal oracle drives the run",
    )
    parser.add_argument("--instrument", default="eth_usd", help="Instrument slug (e.g. eth_usd)")
    parser.add_argument(
        "--mode",
        default=SYNTHETIC_DEMO,
        choices=sorted(SHADOW_MODES),
        help="One of the platform's three non-live modes",
    )
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between bars")
    parser.add_argument("--bars", type=int, default=DEFAULT_MAX_BARS, help="Bars to operate")
    parser.add_argument(
        "--backfill",
        type=int,
        default=DEFAULT_BACKFILL_BARS,
        help="Leading bars replayed at full speed so the dashboard is not empty (default: 60)",
    )
    parser.add_argument(
        "--bar-seconds",
        type=int,
        default=DEFAULT_BAR_SECONDS,
        help="Bar width in market time (default: daily)",
    )
    parser.add_argument("--starting-cash", type=float, default=DEFAULT_STARTING_CASH)
    parser.add_argument("--max-target-weight", type=float, default=1.0)
    parser.add_argument("--max-weight-step", type=float, default=1.0)
    parser.add_argument("--max-drawdown", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=1409, help="Synthetic series seed")
    parser.add_argument("--start-price", type=float, default=2_000.0)
    parser.add_argument("--volatility", type=float, default=0.02)
    return parser


def _config(args: argparse.Namespace) -> OperatorConfig:
    return OperatorConfig(
        candidate_id=str(args.candidate),
        instrument_symbol=str(args.instrument),
        mode=str(args.mode),
        starting_cash=float(args.starting_cash),
        max_target_weight=float(args.max_target_weight),
        max_weight_step=float(args.max_weight_step),
        max_drawdown_fraction=float(args.max_drawdown),
        bar_seconds=int(args.bar_seconds),
        max_bars=int(args.bars),
        backfill_bars=int(args.backfill),
        interval_seconds=float(args.interval),
        seed=int(args.seed),
        start_price=float(args.start_price),
        volatility=float(args.volatility),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stderr
    )
    args = build_parser().parse_args(argv)
    stop = threading.Event()

    def _handle_signal(_signum: int, _frame: FrameType | None) -> None:
        log.info("shutdown requested")
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        config = _config(args)
        config.validate()
    except (OperatorError, V2ValidationError) as error:
        log.error("refusing to start: %s", error)
        return 2

    telemetry = CockpitConfig.from_env()
    reporter = CockpitReporter(build_client(telemetry), symbol=config.instrument_symbol)
    heartbeat = HeartbeatWorker(reporter, interval_seconds=telemetry.heartbeat_interval_seconds)

    try:
        reporter.register()
    except Exception as error:  # a reporter that misbehaves must not stop the trader
        log.warning("telemetry registration was not clean: %s", error)

    # Only now, with the trader ready to run, does the process start claiming to be alive.
    heartbeat.start()
    try:
        outcome = run_operator(config, reporter, stop)
    except (OperatorError, V2ValidationError) as error:
        log.error("operator failed: %s", error)
        reporter.report_error(
            code=STARTUP_FAILED_CODE, message=f"{type(error).__name__}: {error}", fatal=True
        )
        return 2
    except Exception as error:
        log.exception("operator failed")
        reporter.report_error(
            code=STARTUP_FAILED_CODE, message=f"{type(error).__name__}: {error}", fatal=True
        )
        return 1
    finally:
        heartbeat.stop()
        reporter.close()

    # A run that was asked to stop before its first bar stopped cleanly, and says so with a zero
    # exit: shutting down on request is not a failure.
    log.info("exiting after %d bar(s)", outcome.bars_processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
