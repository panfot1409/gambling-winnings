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


def test_milestone_3c_development_version() -> None:
    """Milestone 3C development code identifies itself as 0.6.0.

    v0.3.0 marks the merged Milestone 2B release; 3A was development version
    0.4.0; 3B was 0.5.0 (merged to main, tag policy-blocked); 3C is the next
    development version 0.6.0 and is not tagged. The frozen M2B dossier still pins
    0.3.0, the committed M3A run-003 artifacts still record 0.4.0, and the M3B
    run-001 artifacts still record 0.5.0 — all remain byte-identical under the
    0.6.0 running package.
    """
    assert eth_research.__version__ == "0.6.0"
