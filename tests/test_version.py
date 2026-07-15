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


def test_milestone_3e_development_version() -> None:
    """Milestone 3E development code identifies itself as 0.8.0.

    v0.3.0 marks the merged Milestone 2B release; 3A was development version
    0.4.0; 3B was 0.5.0 (merged to main, tag policy-blocked); 3C was 0.6.0 (a
    draft PR, not tagged); 3D was 0.7.0 (a draft PR, not tagged); 3E is the next
    development version 0.8.0 and is not tagged. Every prior milestone's frozen
    artifacts still pin their own versions — the M2B dossier 0.3.0, the M3A
    run-003 artifacts 0.4.0, the M3B run-001 artifacts 0.5.0, the M3C run-001
    artifacts 0.6.0, and the M3D prospective cohort 0.7.0 — and all remain
    byte-identical under the 0.8.0 running package, because a running version
    that differs from a frozen artifact version marks a development ("snapshot")
    run rather than re-authorizing the frozen one-time run.
    """
    assert eth_research.__version__ == "0.8.0"


def test_completed_milestones_pin_their_own_frozen_versions() -> None:
    """A completed milestone freezes its version once a later one bumps the package.

    M3D is complete: its constant must pin the literal 0.7.0 its committed
    artifacts stamp, independent of the 0.8.0 running package, so every M3D
    artifact rebuilds byte-for-byte. M3E is the current milestone and tracks the
    live running version.
    """
    from eth_research.m3c import M3C_PACKAGE_VERSION
    from eth_research.m3d import M3D_PACKAGE_VERSION
    from eth_research.m3e import M3E_PACKAGE_VERSION

    assert M3C_PACKAGE_VERSION == "0.6.0"
    assert M3D_PACKAGE_VERSION == "0.7.0"
    assert M3E_PACKAGE_VERSION == eth_research.__version__ == "0.8.0"
