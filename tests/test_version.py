"""The installed package metadata and ``__version__`` must never drift.

Every manifest records ``package_version``; a manifest built by this code
must carry this code's own unique version, not the version of some other
tagged release.
"""

from __future__ import annotations

from importlib.metadata import version

import eth_research


def test_package_metadata_and_dunder_version_agree() -> None:
    assert eth_research.__version__ == version("eth-research")


def test_milestone_2b_development_version() -> None:
    """Milestone 2B code identifies itself as 0.3.0, not a released tag's version."""
    assert eth_research.__version__ == "0.3.0"
