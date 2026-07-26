"""A long-running operator process for the signal-only shadow platform.

:func:`eth_research.shadow.runner.run_shadow` is a single-pass, byte-reproducible function over a
fixed series of bars — exactly the right shape for a qualification or a replay, and the wrong shape
for a process an operator leaves running and watches. This package supplies the missing piece: a
paced process that drives that runner, bar by bar, on the operator's own clock, and reports what it
sees.

It adds no engine of its own. Signals come from a pre-registered candidate's own causal scalar
oracle; risk clamping, the latching kill switch, paper accounting, monitoring alerts and the
hash-chained journal are all the accepted shadow platform's, untouched — the qualification source
freeze (``governance/v2c/oq_source_freeze.json``) pins those modules by hash and this package does
not modify a byte of them. Reporting to Nardis Cockpit is optional and observational; with it
switched off the loop is the same loop.

This process places no order, holds no venue credential, connects to no exchange, and moves no
money. It is the shadow platform running in one of its three non-live modes, on a schedule.
"""

from __future__ import annotations

from eth_research.operate.paper import (
    SUPPORTED_CANDIDATE_IDS,
    BarReporter,
    OperatorConfig,
    OperatorError,
    OperatorOutcome,
    SignalSource,
    build_signal_source,
    build_steps,
    run_operator,
)

OPERATE_PACKAGE_VERSION: int = 1

__all__ = [
    "OPERATE_PACKAGE_VERSION",
    "SUPPORTED_CANDIDATE_IDS",
    "BarReporter",
    "OperatorConfig",
    "OperatorError",
    "OperatorOutcome",
    "SignalSource",
    "build_signal_source",
    "build_steps",
    "run_operator",
]
