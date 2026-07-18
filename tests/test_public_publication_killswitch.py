"""Standing fail-closed kill switch against PUBLIC publication of the private package.

``eth-research`` v1.1.0 ships PRIVATELY to authorized collaborators of the private repository
``panfot1409/gambling-winnings``. It is unlicensed, carries the ``Private :: Do Not Upload``
guard, and must never reach a public index or registry. This test scans the production and
executable surface — ``.github/workflows/**``, ``src/eth_research/**``, and ``tools/**`` — for
any concrete public-publication vector and fails closed if one appears.

Historical DOCS (``docs/**``, ``CHANGELOG.md``) legitimately *describe* these vectors — as
blocked, or as a not-yet-live Trusted-Publishing template — so they are deliberately OUT of
scope for the scan. The narrow docs allowlist below records the only paths that may mention a
vector; nothing under the three scanned trees is allowlisted, so a real workflow or executable
source file can never green-light one.

HONESTY — this is a lexical scan. It catches the concrete, named vectors below (the PyPI upload
hosts, ``twine upload``, the ``gh-action-pypi-publish`` / ``softprops/action-gh-release``
actions, ``id-token: write``, a public ``gh release create``, and an ``OSI Approved`` license
classifier), plus the removal of the ``Private :: Do Not Upload`` guard and the addition of a
public channel to ``private_distribution_policy.json``. It cannot prove the ABSENCE of an
arbitrarily obfuscated publish path; it is one layer, paired with the workflow supply-chain
scanner and the no-id-token/no-secret/artifact-upload controls
(``tests/test_workflow_security.py``, ``tests/test_private_workflow_security.py``), the
private-distribution policy's closed posture, the wheel ``Private :: Do Not Upload`` guard, and
mandatory human review.

GitHub Packages note (verified from GitHub Packages' supported-registry documentation): GitHub
Packages hosts npm, RubyGems, Apache Maven, Gradle, NuGet, and Docker/Container registries — it
has NO native Python / PyPI registry. There is therefore no in-platform public Python index to
publish to; the only public Python channels are external (PyPI/TestPyPI), which the patterns
below forbid across the executable surface.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import eth_research

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]

# Each forbidden vector is matched by a SPECIFIC pattern keyed to a real upload/publish action,
# not a bare descriptive word — so a comment that merely *names* a blocked vector (e.g. the
# release-evidence gate text, or the workflow scanner's own detector regexes) is not a false hit.
FORBIDDEN_VECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pypi_upload_host", re.compile(r"upload\.pypi\.org")),
    ("pypi_legacy_endpoint", re.compile(r"pypi\.org/legacy")),
    ("test_pypi_host", re.compile(r"test\.pypi\.org")),
    ("twine_upload", re.compile(r"\btwine\s+upload\b")),
    ("gh_action_pypi_publish", re.compile(r"gh-action-pypi-publish")),
    ("action_gh_release", re.compile(r"softprops/action-gh-release")),
    ("public_gh_release_create", re.compile(r"\bgh\s+release\s+create\b")),
    ("oidc_id_token_write", re.compile(r"id-token\s*:\s*write")),
    ("osi_license_classifier", re.compile(r"License\s*::\s*OSI Approved")),
)

# Paths that may legitimately mention a vector (historical docs / templates). NOTHING under the
# three scanned trees is listed: a production workflow or executable source file is never exempt.
DOCS_ALLOWLIST: frozenset[str] = frozenset()

PRIVATE_GUARD_CLASSIFIER = "Private :: Do Not Upload"


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    files += sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    files += sorted((REPO_ROOT / ".github" / "workflows").glob("*.yaml"))
    for base in ("src/eth_research", "tools"):
        root = REPO_ROOT / base
        files += sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def test_no_public_publication_vector_in_production_or_executable_source() -> None:
    violations: list[str] = []
    for path in _scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in DOCS_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        for name, pattern in FORBIDDEN_VECTORS:
            if pattern.search(text):
                violations.append(f"{rel}: forbidden public-publication vector [{name}]")
    assert violations == [], "\n".join(violations)


def test_scan_actually_covers_the_three_trees() -> None:
    # Guard the guard: prove the scan is non-empty and reaches each tree (a silently empty scan
    # would pass vacuously).
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in _scanned_files()}
    assert any(p.startswith(".github/workflows/") for p in scanned)
    assert any(p.startswith("src/eth_research/") for p in scanned)
    assert any(p.startswith("tools/") for p in scanned)
    assert ".github/workflows/private-release-build.yml" in scanned
    assert "tools/private_release.py" in scanned
    assert "src/eth_research/m3f/workflow_inventory.py" in scanned


def test_the_kill_switch_would_fire_on_a_planted_vector(tmp_path: Path) -> None:
    # The scan is genuinely fail-closed: a planted vector is detected by the same patterns.
    planted = {
        "id-token: write": "oidc_id_token_write",
        "twine upload dist/*": "twine_upload",
        "uses: pypa/gh-action-pypi-publish@release/v1": "gh_action_pypi_publish",
        "url: https://upload.pypi.org/legacy/": "pypi_upload_host",
        "gh release create v1.1.0": "public_gh_release_create",
        "License :: OSI Approved :: MIT License": "osi_license_classifier",
    }
    for sample, expected in planted.items():
        hits = [name for name, pattern in FORBIDDEN_VECTORS if pattern.search(sample)]
        assert expected in hits, f"{sample!r} should trip [{expected}], got {hits}"


def test_pyproject_keeps_the_private_guard_and_no_license_classifier() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    assert PRIVATE_GUARD_CLASSIFIER in classifiers, "the Private :: Do Not Upload guard was removed"
    for classifier in classifiers:
        assert not classifier.startswith("License ::"), f"license classifier appeared: {classifier}"
        assert "OSI Approved" not in classifier, f"OSI classifier appeared: {classifier}"
    # No license is declared at all (an SPDX expression would also enable a public upload).
    assert "license" not in pyproject["project"] or not pyproject["project"].get("license")


def test_private_distribution_policy_has_no_public_channel() -> None:
    policy_path = REPO_ROOT / "release/private/v1.1.0/private_distribution_policy.json"
    policy = json.loads(policy_path.read_bytes())
    for flag in (
        "public_pypi_allowed",
        "test_pypi_allowed",
        "public_github_release_allowed",
        "public_package_registry_allowed",
        "open_source_claim_allowed",
        "license_present",
    ):
        assert policy[flag] is False, f"policy {flag} must stay false"
    assert policy["distribution_classification"] == "private"
    assert policy["repository_visibility_required"] == "private"
    public_tokens = ("pypi", "public", "anonymous", "registry")
    for channel in policy["accepted_distribution_channels"]:
        assert not any(token in channel for token in public_tokens), (
            f"a public channel was added to the policy: {channel}"
        )
