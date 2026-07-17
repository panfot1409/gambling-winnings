"""GA packaging metadata is present, self-consistent, and honest about the license gate.

These lock in the v1.1.0 general-availability packaging metadata added on ``release/v1.1.0-ga``:
project URLs, PyPI classifiers, keywords, authors, a research/simulation-framed description, and the
deliberate publication guards. Critically, they assert that **no license classifier or license field**
is declared — choosing a license is an external human decision (``docs/V1_LICENSE_DECISION.md``) — and
that the ``Private :: Do Not Upload`` guard is present so the unlicensed package cannot be pushed to
public PyPI by accident. The package version stays exactly ``1.1.0`` (this is release packaging, not a
code bump).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _project() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project: dict[str, Any] = data["project"]
    return project


def test_name_and_version_unchanged() -> None:
    proj = _project()
    assert proj["name"] == "eth-research"
    assert proj["version"] == "1.1.0"
    assert proj["version"] == eth_research.__version__


def test_description_is_research_simulation_framed() -> None:
    desc = _project()["description"].lower()
    assert "research" in desc
    assert "simulation" in desc or "simulat" in desc
    # The old wording implied a product for building trading algorithms; the GA framing is
    # research/simulation and explicitly not live trading.
    assert "no live trading" in desc
    assert "trading algorithms" not in desc


def test_project_urls_present() -> None:
    urls = _project()["urls"]
    for key in ("Homepage", "Repository", "Documentation", "Changelog", "Issues"):
        assert key in urls, key
        assert urls[key].startswith("https://github.com/panfot1409/gambling-winnings")


def test_keywords_and_authors_present() -> None:
    proj = _project()
    assert "ethereum" in proj["keywords"]
    assert len(proj["keywords"]) >= 5
    assert proj["authors"] and all("name" in a for a in proj["authors"])


def test_expected_classifiers_present() -> None:
    classifiers = set(_project()["classifiers"])
    for expected in (
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Typing :: Typed",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ):
        assert expected in classifiers, expected


def test_no_license_is_declared_the_gate_is_external() -> None:
    proj = _project()
    # Choosing a license is a human decision; the release pipeline must not invent one.
    assert "license" not in proj, "a license field was added — that is an external human gate"
    assert not any(c.startswith("License ::") for c in proj["classifiers"]), (
        "a license classifier was added — that is an external human gate"
    )


def test_do_not_upload_guard_present_until_gates_cleared() -> None:
    # Belt-and-suspenders: the unlicensed package must not reach public PyPI by accident.
    assert "Private :: Do Not Upload" in _project()["classifiers"]
