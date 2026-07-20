"""Signal-only shadow-operations platform for observing a research candidate without acting on it.

The shadow platform replays or simulates a candidate's *signal* through an as-of clock, a risk-limit
engine, a latching kill switch, deterministic paper accounting, and an append-only journal, and
records what a live operator would have seen. It has three non-live modes only
(``synthetic_demo`` / ``historical_shadow`` / ``paper_simulation``) and never connects to a network,
places an order, holds a credential, or moves money — those prohibitions are enforced fail-closed at
the mode boundary and by the repository's AST no-network guard.
"""

from __future__ import annotations

SHADOW_PACKAGE_VERSION: int = 1
