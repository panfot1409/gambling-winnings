"""V2A-V2B section 22 -- whole-stack acceptance verifier + standing acquisition-retirement check."""

from __future__ import annotations

from pathlib import Path

from eth_research.v2ab.acceptance import verify_stack_acceptance
from eth_research.v2ab.acquisition_audit import verify_btc_acquisition

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_whole_stack_acceptance_is_clean() -> None:
    """Every chained acceptance verifier passes against the committed repository."""
    assert verify_stack_acceptance(_REPO_ROOT) == []


def test_no_active_acquisition_authorization_remains() -> None:
    """Standing check: the retired V2B BTC acquisition leaves no active authorization.

    The one-shot BTC acquisition was executed and retired; no committed workflow may contact the
    exchange, reference the V2B acquisition runner, or re-arm the acquire sentinel. (The accepted,
    inactive M3E prospective machinery references its own offline ``m3e.acquire_runner`` in
    plan-only mode and contacts no endpoint; it is out of scope here and not flagged.)
    """
    workflows = sorted((_REPO_ROOT / ".github/workflows").glob("*.yml"))
    assert workflows, "expected at least one workflow file"
    for wf in workflows:
        text = wf.read_text().lower()
        assert "api.exchange.coinbase.com" not in text, f"{wf.name} contacts the exchange"
        assert "v2b.acquire_runner" not in text, f"{wf.name} references the V2B acquisition runner"
        assert "v2b/acquire" not in text, f"{wf.name} references a V2B acquisition path"
    assert not (_REPO_ROOT / "research/v2b/acquire.trigger").exists(), "acquire sentinel is present"
    # The acquisition audit independently confirms the retirement + reproduction.
    assert verify_btc_acquisition(_REPO_ROOT) == []
