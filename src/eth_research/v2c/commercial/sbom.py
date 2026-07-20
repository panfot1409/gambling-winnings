"""V2C section 29: the private software bill of materials for the V2C development distribution.

A minimal CycloneDX 1.5 SBOM whose subject (``metadata.component``) is ``eth-research`` at the
frozen V2C development version, classified **private**, and whose ``components[]`` enumerate the
locked environment from ``uv.lock`` (excluding the subject itself). It is derived deterministically
from the committed lock file, so it reproduces byte-for-byte from a clean tree. The private
classification is carried as an explicit CycloneDX property; there is no public-distribution claim.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from eth_research.v2.strict import V2ValidationError

#: The frozen V2C development version this SBOM is the bill of materials for.
V2C_DEV_VERSION: str = "2.0.0.dev2"

SBOM_SPEC_VERSION: str = "1.5"


class PrivateSBOMError(V2ValidationError):
    """The private SBOM could not be built or drifted from the locked environment."""


def _locked_packages(repo_root: Path) -> list[dict[str, str]]:
    lock_path = repo_root / "uv.lock"
    if not lock_path.is_file():
        raise PrivateSBOMError(f"uv.lock not found at {lock_path}")
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages: list[dict[str, str]] = []
    for entry in lock.get("package", []):
        name = str(entry["name"])
        version = str(entry["version"])
        packages.append({"name": name, "version": version, "purl": f"pkg:pypi/{name}@{version}"})
    return sorted(packages, key=lambda item: item["name"])


def build_private_sbom(repo_root: str | Path) -> dict[str, object]:
    """Build the private CycloneDX SBOM for the V2C development distribution from ``uv.lock``."""
    root = Path(repo_root)
    components = [
        {"type": "library", "name": p["name"], "version": p["version"], "purl": p["purl"]}
        for p in _locked_packages(root)
        if p["name"] != "eth-research"
    ]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SBOM_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "eth-research",
                "version": V2C_DEV_VERSION,
                "purl": f"pkg:pypi/eth-research@{V2C_DEV_VERSION}",
                "description": (
                    "offline, research-only ETH trading-strategy research toolkit "
                    "(private V2C development distribution)"
                ),
            },
            "properties": [
                {
                    "name": "distribution:classification",
                    "value": "private",
                },
                {
                    "name": "distribution:public_publication",
                    "value": "forbidden",
                },
                {
                    "name": "components:scope",
                    "value": (
                        "locked runtime and dev/build environment (uv.lock); the distributed "
                        "wheel declares only numpy, pandas, pyarrow at runtime"
                    ),
                },
            ],
        },
        "components": components,
    }


__all__ = [
    "SBOM_SPEC_VERSION",
    "V2C_DEV_VERSION",
    "PrivateSBOMError",
    "build_private_sbom",
]
