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


def test_milestone_3a_development_version() -> None:
    """Milestone 3A development code identifies itself as 0.4.0.

    v0.3.0 marks the merged Milestone 2B release; 3A is the next
    development version and is not tagged.
    """
    assert eth_research.__version__ == "0.4.0"
