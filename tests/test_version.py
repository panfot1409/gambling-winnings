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


def test_milestone_3d_development_version() -> None:
    """Milestone 3D development code identifies itself as 0.7.0.

    v0.3.0 marks the merged Milestone 2B release; 3A was development version
    0.4.0; 3B was 0.5.0 (merged to main, tag policy-blocked); 3C was 0.6.0 (a
    draft PR, not tagged); 3D is the next development version 0.7.0 and is not
    tagged. Every prior milestone's frozen artifacts still pin their own
    versions — the M2B dossier 0.3.0, the M3A run-003 artifacts 0.4.0, the M3B
    run-001 artifacts 0.5.0, and the M3C run-001 artifacts 0.6.0 — and all
    remain byte-identical under the 0.7.0 running package, because a running
    version that differs from a frozen artifact version marks a development
    ("snapshot") run rather than re-authorizing the frozen one-time run.
    """
    assert eth_research.__version__ == "0.7.0"
