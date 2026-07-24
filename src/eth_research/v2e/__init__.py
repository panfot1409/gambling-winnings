"""V2E — private, read-only operations dashboard and paper-activation harness.

This package renders the honest operational state of the research program for the
repository owner's own machine (loopback by default) and mechanizes the paper-execution
lifecycle WITHOUT activating it. It is strictly read-only with respect to research and
governance state: it derives one immutable :class:`~eth_research.v2e.state.DashboardState`
exclusively from the existing canonical parsers and committed artifacts, fails closed on
any inconsistency, and never repairs, mutates, or appends anything.

Boundaries (enforced by tests):

* no strategy, candidate, signal, or market-data code is imported or executed;
* the paper lifecycle rests at ``disabled`` while no eligible candidate exists — the
  accepted fable5 paper-readiness gate is consumed, never re-derived or weakened;
* the HTTP surface is GET/HEAD-only with a fixed route set and no filesystem mapping;
* nothing here requires network access, GitHub tokens, or credentials of any kind.
"""

from __future__ import annotations
