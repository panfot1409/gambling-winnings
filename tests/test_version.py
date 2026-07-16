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


def test_milestone_3f_development_version() -> None:
    """Milestone 3F development code identifies itself as 0.9.0.

    v0.3.0 marks the merged Milestone 2B release; 3A was development version
    0.4.0; 3B was 0.5.0; 3C was 0.6.0; 3D was 0.7.0; 3E was 0.8.0 (the M2B-M3E
    stack is merged to main, tags policy-blocked). 3F is the next development
    version 0.9.0 and is not tagged. Every prior milestone's frozen artifacts
    still pin their own versions and remain byte-identical under the 0.9.0
    running package, because a running version that differs from a frozen
    artifact version marks a development ("snapshot") run rather than
    re-authorizing a frozen one-time run.
    """
    assert eth_research.__version__ == "0.9.0"


def test_completed_milestones_pin_their_own_frozen_versions() -> None:
    """A completed milestone freezes its version once a later one bumps the package.

    M3C/M3D/M3E are complete: each constant pins the literal version its committed
    artifacts stamp, independent of the running package, so every accepted artifact
    rebuilds byte-for-byte. M3F is the current milestone and tracks the live running
    version.
    """
    from eth_research.m3c import M3C_PACKAGE_VERSION
    from eth_research.m3d import M3D_PACKAGE_VERSION
    from eth_research.m3e import M3E_PACKAGE_VERSION
    from eth_research.m3f import M3F_PACKAGE_VERSION

    assert M3C_PACKAGE_VERSION == "0.6.0"
    assert M3D_PACKAGE_VERSION == "0.7.0"
    assert M3E_PACKAGE_VERSION == "0.8.0"
    assert M3F_PACKAGE_VERSION == eth_research.__version__ == "0.9.0"
