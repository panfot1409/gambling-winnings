"""V2C: candidate-free, data-only prospective-evidence and offline-operations foundation.

Milestone V2C builds on the merged V2A and V2B **null** results without evaluating any trading
strategy. Its ground rule is enforced in code by :mod:`eth_research.v2c.firewall`: the only
operational target V2C may resolve is ``cash_control`` (hold 100% cash, zero risky exposure), and
every candidate id, strategy/signal callable, candidate module, research protocol, financial
endpoint, nomination rule, return/equity metric, benchmark, optimization request, or
market-performance report is refused fail-closed before it can reach an engine.

This package imports **no** candidate, strategy, evaluator, or backtest-engine module. The firewall
recognizes the legacy candidate ids as opaque strings, so it can refuse them without importing the
code that produced them.
"""

from __future__ import annotations

from eth_research.v2c.firewall import (
    CASH_CONTROL_TARGET_ID,
    FORBIDDEN_REQUEST_KINDS,
    KNOWN_LEGACY_CANDIDATE_IDS,
    CashControl,
    CashControlIntent,
    V2CFirewallError,
    assert_no_candidate_reference,
    guard_request_kind,
    resolve_operational_target,
)

__all__ = [
    "CASH_CONTROL_TARGET_ID",
    "FORBIDDEN_REQUEST_KINDS",
    "KNOWN_LEGACY_CANDIDATE_IDS",
    "CashControl",
    "CashControlIntent",
    "V2CFirewallError",
    "assert_no_candidate_reference",
    "guard_request_kind",
    "resolve_operational_target",
]
