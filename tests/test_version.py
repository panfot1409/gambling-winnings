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


def test_active_development_version_is_v2b() -> None:
    """The active development version is the V2B pre-release ``2.0.0.dev1``.

    V2B continues the adopted V2 sell-ready roadmap on top of the accepted V2A
    negative result. The version is a development pre-release (``.dev1``): the V2
    research foundation is still under construction and nothing is released or
    tagged as 2.0. ``Private :: Do Not Upload`` is preserved and no license is
    added. Bumping the active version from ``2.0.0.dev0`` to ``2.0.0.dev1`` turns
    V2A into a completed, frozen milestone whose committed governed artifacts pin
    their own recorded version (``V2A_PACKAGE_VERSION``), exactly as every earlier
    completed milestone does.
    """
    assert eth_research.__version__ == "2.0.0.dev1"


def test_milestone_4b_is_frozen_at_1_1_0() -> None:
    """Milestone 4B is a completed milestone frozen at 1.1.0.

    v0.3.0 marks the merged Milestone 2B release; 3A was development version
    0.4.0; 3B was 0.5.0; 3C was 0.6.0; 3D was 0.7.0; 3E was 0.8.0; 3F was 0.9.0
    (the M2B-M3F stack, tags policy-blocked); 4A was the offline research
    platform 1.0 release candidate (1.0.0); 4B was the multi-asset portfolio
    research simulator 1.1.0 (the private-GA release, remote tag policy-blocked);
    V2A was the commercial-evidence milestone frozen at ``2.0.0.dev0``. V2B is the
    current development milestone at ``2.0.0.dev1``. Every completed milestone's
    frozen artifacts pin their own versions and remain byte-identical under the
    running package, because a running version that differs from a frozen artifact
    version marks a development ("snapshot") run rather than re-authorizing a
    frozen one-time run.
    """
    from eth_research.portfolio import M4B_PACKAGE_VERSION

    assert M4B_PACKAGE_VERSION == "1.1.0"
    assert eth_research.__version__ == "2.0.0.dev1"


def test_completed_milestones_pin_their_own_frozen_versions() -> None:
    """A completed milestone freezes its version once a later one bumps the package.

    M3C/M3D/M3E/M3F, 4A, 4B, and now V2A are complete: each constant pins the
    literal version its committed artifacts stamp, independent of the running
    package, so every accepted artifact rebuilds byte-for-byte. V2B is the current
    development milestone and tracks the live running version ``2.0.0.dev1``.
    """
    from eth_research.m3c import M3C_PACKAGE_VERSION
    from eth_research.m3d import M3D_PACKAGE_VERSION
    from eth_research.m3e import M3E_PACKAGE_VERSION
    from eth_research.m3f import M3F_PACKAGE_VERSION
    from eth_research.m4a import M4A_PACKAGE_VERSION
    from eth_research.portfolio import M4B_PACKAGE_VERSION
    from eth_research.v2 import V2A_PACKAGE_VERSION

    assert M3C_PACKAGE_VERSION == "0.6.0"
    assert M3D_PACKAGE_VERSION == "0.7.0"
    assert M3E_PACKAGE_VERSION == "0.8.0"
    assert M3F_PACKAGE_VERSION == "0.9.0"
    assert M4A_PACKAGE_VERSION == "1.0.0"
    assert M4B_PACKAGE_VERSION == "1.1.0"
    assert V2A_PACKAGE_VERSION == "2.0.0.dev0"
    assert eth_research.__version__ == "2.0.0.dev1"
