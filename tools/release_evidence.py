#!/usr/bin/env python3
"""Deterministic, standard-library-only generator + checker for the v1.1.0 release evidence.

Emits three canonical-JSON artifacts under ``release/<version>/``:

* ``release_manifest.json`` — the release identity: package name/version, the distribution *source*
  members (``src/eth_research/**``) with content hashes and a tree digest, the runtime dependency
  set, the governed-state neutrality digest (every ``research/`` artifact hashed), and the sealed
  ledger triple. Every field is a function of the **tracked** source in a clean checkout — the tool
  hashes the working tree (filtering ``__pycache__``), so generate/verify from a clean tree; an
  untracked file under ``src/`` or ``research/`` shifts a digest and drift then fails closed.
* ``sbom.cdx.json`` — a minimal CycloneDX 1.5 software bill of materials derived from ``uv.lock``.
* ``release_state.json`` — the honest publication posture: built and hardened, **not published**,
  with the exact external gates that keep publication closed.

Usage::

    python3 tools/release_evidence.py --write --repo-root .     # (re)generate the artifacts
    python3 tools/release_evidence.py --check --repo-root .     # fail closed on any drift

Standard library only; no third-party import and no network. ``--check`` mutates no tracked file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

VERSION = "1.1.0"
RELDIR = f"release/v{VERSION}"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SEALED_LEDGERS = (
    "research/m3a/development_gate_access.jsonl",
    "research/m2b/test_evaluations.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)
# The pre-GA governed-state baseline captured on the merged main (M3). GA hardening must not change
# any research/ artifact, so this digest must reproduce exactly.
GOVERNED_BASELINE_DIGEST = "b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _iter_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def governed_baseline_digest(repo_root: Path) -> str:
    """Hash every artifact under ``research/`` (sorted by posix path) into one digest."""
    research = repo_root / "research"
    lines = []
    for p in _iter_files(research):
        rel = p.relative_to(repo_root).as_posix()
        lines.append(f"{_sha256_bytes(p.read_bytes())}  {rel}\n")
    return _sha256_bytes("".join(lines).encode("utf-8"))


def distribution_source(repo_root: Path) -> dict[str, object]:
    pkg = repo_root / "src" / "eth_research"
    members = []
    for p in _iter_files(pkg):
        rel = p.relative_to(repo_root / "src").as_posix()
        members.append({"path": rel, "sha256": _sha256_bytes(p.read_bytes())})
    tree_digest = _sha256_bytes(
        "".join(f"{m['sha256']}  {m['path']}\n" for m in members).encode("utf-8")
    )
    return {"member_count": len(members), "tree_digest": tree_digest, "members": members}


def _locked_packages(repo_root: Path) -> list[dict[str, str]]:
    lock = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))
    out = []
    for p in lock.get("package", []):
        name = str(p["name"])
        ver = str(p["version"])
        out.append({"name": name, "version": ver, "purl": f"pkg:pypi/{name}@{ver}"})
    return sorted(out, key=lambda d: d["name"])


def _runtime_dependencies(repo_root: Path) -> list[str]:
    proj = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return list(proj["dependencies"])


def build_manifest(repo_root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "eth-research",
        "version": VERSION,
        "python_requires": ">=3.12",
        "runtime_dependencies": _runtime_dependencies(repo_root),
        "distribution_source": distribution_source(repo_root),
        "governed_state": {
            "baseline_digest": governed_baseline_digest(repo_root),
            "sealed_ledgers": dict.fromkeys(SEALED_LEDGERS, EMPTY_SHA),
        },
        "publication": {
            "published": False,
            "reason": "blocked pending external gates: license, PyPI trusted publisher, "
            "and a reviewed relaxation of the no-id-token workflow governance invariant",
        },
        "generated_by": "tools/release_evidence.py",
    }


def build_sbom(repo_root: Path) -> dict[str, object]:
    # metadata.component is the subject (the distributed package); components[] enumerates the
    # locked environment from uv.lock (runtime + dev/build tools), excluding the subject itself.
    # The wheel's own declared runtime surface is only numpy/pandas/pyarrow (see the manifest).
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "eth-research",
                "version": VERSION,
                "purl": f"pkg:pypi/eth-research@{VERSION}",
                "description": "offline, research-only ETH trading-strategy research toolkit",
            },
            "properties": [
                {
                    "name": "components:scope",
                    "value": "locked runtime and dev/build environment (uv.lock); the distributed "
                    "wheel declares only numpy, pandas, pyarrow at runtime",
                }
            ],
        },
        "components": [
            {"type": "library", "name": p["name"], "version": p["version"], "purl": p["purl"]}
            for p in _locked_packages(repo_root)
            if p["name"] != "eth-research"
        ],
    }


def build_state(_repo_root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "version": VERSION,
        "published": False,
        "distribution_built": True,
        "hardened": True,
        "publication_gates": [
            {
                "id": "license",
                "cleared": False,
                "detail": "no LICENSE file; choosing one is an external human decision "
                "(docs/V1_LICENSE_DECISION.md)",
            },
            {
                "id": "pypi_trusted_publisher",
                "cleared": False,
                "detail": "a PyPI pending publisher must be configured by a human "
                "before any OIDC upload",
            },
            {
                "id": "governance_no_id_token_invariant",
                "cleared": False,
                "detail": "tests/test_workflow_security.py forbids id-token in any "
                "workflow; a live Trusted-Publishing workflow needs a reviewed "
                "relaxation (docs/V1_PUBLICATION_PIPELINE.md)",
            },
        ],
    }


_ARTIFACTS: dict[str, Callable[[Path], dict[str, object]]] = {
    "release_manifest.json": build_manifest,
    "sbom.cdx.json": build_sbom,
    "release_state.json": build_state,
}


def write(repo_root: Path) -> None:
    outdir = repo_root / RELDIR
    outdir.mkdir(parents=True, exist_ok=True)
    for name, builder in _ARTIFACTS.items():
        (outdir / name).write_bytes(_canonical_json(builder(repo_root)))


def check(repo_root: Path) -> list[str]:
    problems = []
    outdir = repo_root / RELDIR
    for name, builder in _ARTIFACTS.items():
        path = outdir / name
        if not path.exists():
            problems.append(f"{RELDIR}/{name} is missing")
            continue
        want = _canonical_json(builder(repo_root))
        if path.read_bytes() != want:
            problems.append(f"{RELDIR}/{name} is stale; regenerate with --write")
    got = governed_baseline_digest(repo_root)
    if got != GOVERNED_BASELINE_DIGEST:
        problems.append(f"governed-state digest changed: {got} != {GOVERNED_BASELINE_DIGEST}")
    for rel in SEALED_LEDGERS:
        p = repo_root / rel
        if not p.exists() or _sha256_bytes(p.read_bytes()) != EMPTY_SHA:
            problems.append(f"sealed ledger {rel} is not byte-empty")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v1.1.0 release-evidence generator/checker")
    ap.add_argument("--repo-root", default=".")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    ns = ap.parse_args(argv)
    root = Path(ns.repo_root).resolve()
    if ns.write:
        write(root)
        print(f"wrote release evidence under {RELDIR}/")
        return 0
    problems = check(root)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    print("release evidence is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
