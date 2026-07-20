"""V2C sections 28-31: deterministic build + fail-closed check of the commercial evidence pack.

Serializes the four fixed models -- the inactive deployment blueprint, the private SBOM, the IP
dossier, and the commercial-options record -- to canonical JSON under ``release/private/v2c/`` and
verifies the committed bytes reproduce exactly. Every artifact is a pure function of the committed
source (and, for the SBOM, of ``uv.lock``), so ``check`` fails closed on any drift. Nothing here is
published; the pack is private evidence in a private repository.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from eth_research.v2.strict import canonical_json_bytes
from eth_research.v2c.commercial.deployment import DeploymentBlueprint
from eth_research.v2c.commercial.ip_dossier import IPDossier
from eth_research.v2c.commercial.options import CommercialOptions
from eth_research.v2c.commercial.sbom import build_private_sbom

#: Where the committed commercial-evidence artifacts live (a private, non-published location).
EVIDENCE_DIR: str = "release/private/v2c"

DEPLOYMENT_ARTIFACT: str = "deployment_blueprint.json"
SBOM_ARTIFACT: str = "sbom.cdx.json"
IP_DOSSIER_ARTIFACT: str = "ip_dossier.json"
COMMERCIAL_OPTIONS_ARTIFACT: str = "commercial_options.json"


def _deployment(_repo_root: Path) -> bytes:
    return canonical_json_bytes(DeploymentBlueprint.current().to_canonical())


def _sbom(repo_root: Path) -> bytes:
    return canonical_json_bytes(build_private_sbom(repo_root))


def _ip_dossier(_repo_root: Path) -> bytes:
    return canonical_json_bytes(IPDossier.current().to_canonical())


def _commercial_options(_repo_root: Path) -> bytes:
    return canonical_json_bytes(CommercialOptions.current().to_canonical())


_ARTIFACTS: dict[str, Callable[[Path], bytes]] = {
    DEPLOYMENT_ARTIFACT: _deployment,
    SBOM_ARTIFACT: _sbom,
    IP_DOSSIER_ARTIFACT: _ip_dossier,
    COMMERCIAL_OPTIONS_ARTIFACT: _commercial_options,
}


def build_all(repo_root: str | Path) -> dict[str, bytes]:
    """Build every commercial-evidence artifact as canonical-JSON bytes, keyed by filename."""
    root = Path(repo_root)
    return {name: builder(root) for name, builder in _ARTIFACTS.items()}


def write_all(repo_root: str | Path) -> list[Path]:
    """(Re)write every committed artifact under ``release/private/v2c/``; return the paths."""
    root = Path(repo_root)
    outdir = root / EVIDENCE_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in build_all(root).items():
        path = outdir / name
        path.write_bytes(payload)
        written.append(path)
    return written


def check(repo_root: str | Path) -> list[str]:
    """Return the list of drift problems (empty == OK): committed bytes must reproduce exactly."""
    root = Path(repo_root)
    outdir = root / EVIDENCE_DIR
    problems: list[str] = []
    expected = build_all(root)
    for name, payload in expected.items():
        path = outdir / name
        if not path.exists():
            problems.append(f"{EVIDENCE_DIR}/{name} is missing")
            continue
        if path.read_bytes() != payload:
            problems.append(f"{EVIDENCE_DIR}/{name} drifted from the deterministic build")
    return problems


__all__ = [
    "COMMERCIAL_OPTIONS_ARTIFACT",
    "DEPLOYMENT_ARTIFACT",
    "EVIDENCE_DIR",
    "IP_DOSSIER_ARTIFACT",
    "SBOM_ARTIFACT",
    "build_all",
    "check",
    "write_all",
]
