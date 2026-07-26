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
* ``release_state.json`` — the honest **private** release posture: the public-GA route was
  abandoned, the package is built and hardened but **not publicly published**, distribution is
  private, and the ordered private lifecycle (``public_ga_abandoned`` → ``private_ga_in_progress``
  → ``ready`` → ``shipped``) records the current state with its fail-closed private gates.

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


# Development layers added AFTER the pre-GA baseline are outside this frozen neutrality scope: they
# carry their own drift checks (V2A: eth_research.v2.replay.verify_v2a + the v2a-replay workflow;
# V2B: the eth_research.v2b research-memory / dataset / registry verifiers + the v2b-replay
# workflow; the V2A-V2B stacked-acceptance layer: the eth_research.v2ab.acceptance verifier + the
# v2ab-replay workflow), so their research/ artifacts are excluded here — as the M3C-M3E freeze
# table excludes the later M3F/M4A/M4B layers it does not own. The baseline stays the merged-main
# (M3) governed state; excluding these strictly-later additive layers reproduces it exactly.
_POST_BASELINE_PREFIXES = ("research/v2a/", "research/v2b/", "research/v2/", "research/v2ab/")


def governed_baseline_digest(repo_root: Path) -> str:
    """Hash every pre-GA artifact under ``research/`` (sorted by posix path) into one digest."""
    research = repo_root / "research"
    lines = []
    for p in _iter_files(research):
        rel = p.relative_to(repo_root).as_posix()
        if any(rel.startswith(prefix) for prefix in _POST_BASELINE_PREFIXES):
            continue
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


# The private-release lifecycle, in order. The prior public-GA route was abandoned when the owner
# decided to keep the project private; this evidence tracks only the private posture from there.
RELEASE_LIFECYCLE = (
    "public_ga_abandoned",
    "private_ga_in_progress",
    "ready",
    "shipped",
)
# The current lifecycle state, advanced by hand at each milestone: ``private_ga_in_progress`` while
# the private release is being built, ``ready`` at code freeze (pre-merge — the source is frozen and
# every canonical identity is registered and reproduces), ``shipped`` only after the private payload
# has been delivered through the access-controlled Actions artifact. ``--check`` fails closed unless
# the committed ``release_state.json`` matches this constant.
#
# Advanced to ``shipped`` after the private-GA merge (MPGA) reached ``main`` with all required
# CI terminal-green and the deterministic private payload was built and delivered on an
# independent GitHub runner, via the dispatch-only ``private-release-build.yml``, to this PRIVATE
# repository's own access-controlled Actions artifact store, then verified member-exact against
# the committed manifest and the reproducible-build canonical identities. ``shipped`` marks that
# private delivery occurred; it does NOT mean any public publication — ``published`` stays false
# and every public channel stays closed. The durable install channel is the immutable merge
# commit (git+ssh commit-pin); the Actions artifact is a re-buildable convenience copy.
RELEASE_STATE = "shipped"


def build_state(_repo_root: Path) -> dict[str, object]:
    if RELEASE_STATE not in RELEASE_LIFECYCLE:  # pragma: no cover - guarded constant
        raise ValueError(f"unknown release state: {RELEASE_STATE}")
    return {
        "schema_version": 2,
        "version": VERSION,
        "distribution_classification": "private",
        "repository_visibility_required": "private",
        "release_lifecycle": list(RELEASE_LIFECYCLE),
        "release_state": RELEASE_STATE,
        "release_state_index": RELEASE_LIFECYCLE.index(RELEASE_STATE),
        "public_ga_abandoned": True,
        "distribution_built": True,
        "hardened": True,
        # Public publication is closed and stays closed: the package ships privately to authorized
        # collaborators only. ``published`` is the public-publication flag and is never true.
        "published": False,
        "public_channels_closed": {
            "public_pypi": False,
            "test_pypi": False,
            "public_github_release": False,
            "public_package_registry": False,
            "open_source_claim": False,
            "license_present": False,
        },
        # Private delivery posture. ``private_payload_delivered`` flips true only at ``shipped``.
        "private_distribution": True,
        "private_payload_delivered": RELEASE_STATE == "shipped",
        # The standing conditions the private release is held to (all fail-closed, none external).
        "private_gates": [
            {
                "id": "repository_private",
                "required": True,
                "detail": "the repository must be private; the private-release workflow verifies "
                "github.event.repository.private before building or uploading",
            },
            {
                "id": "sealed_ledgers_byte_empty",
                "required": True,
                "detail": "the three sealed access ledgers must stay byte-empty",
            },
            {
                "id": "governed_state_unchanged",
                "required": True,
                "detail": "every accepted research/ artifact stays byte-identical to the governed "
                "baseline digest",
            },
            {
                "id": "no_public_publication_vector",
                "required": True,
                "detail": "tests/test_public_publication_killswitch.py forbids any public-"
                "publication vector in the executable surface",
            },
        ],
    }


_ARTIFACTS: dict[str, Callable[[Path], dict[str, object]]] = {
    "release_manifest.json": build_manifest,
    "sbom.cdx.json": build_sbom,
    "release_state.json": build_state,
}


def write(repo_root: Path) -> list[str]:
    """Regenerate the release evidence; return the artifact names actually written.

    Under a later development version this deliberately leaves ``release_manifest.json`` alone,
    for the same reason :func:`check` stops reproducing it: the v1.1.0 manifest is a record of the
    v1.1.0 *source tree*, and rebuilding it from a diverged tree would produce an artifact that
    still claims version 1.1.0 while listing today's files — a false record, written by the very
    command ``check``'s "regenerate with --write" message sends an operator to. The sbom and the
    release state are version-independent and are always rebuilt.
    """
    outdir = repo_root / RELDIR
    outdir.mkdir(parents=True, exist_ok=True)
    historical = _active_version(repo_root) != VERSION
    written: list[str] = []
    for name, builder in _ARTIFACTS.items():
        if historical and name == "release_manifest.json":
            continue
        (outdir / name).write_bytes(_canonical_json(builder(repo_root)))
        written.append(name)
    return written


def _active_version(repo_root: Path) -> str:
    """The running package's active version, read from the tracked ``pyproject.toml``."""
    proj = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return str(proj["version"])


def _check_release_manifest_historical(path: Path, repo_root: Path) -> list[str]:
    """Historical-replay verification of the committed v1.1.0 ``release_manifest.json``.

    Used only when the active package version has moved past the frozen release ``VERSION``
    (e.g. a later development version like ``2.0.0.dev0``). The v1.1.0 manifest was built from the
    v1.1.0 *source tree*; a later tree legitimately differs (a bumped ``__version__``, added V2
    modules), so requiring the live tree to reproduce it would be wrong. Instead this validates the
    artifact's own recorded identity and internal consistency, and that the version-independent
    governed record it references still holds — never mutating the artifact and never relaxing the
    live-reproduction check that runs when the active version equals ``VERSION``.
    """
    problems: list[str] = []
    mf = f"{RELDIR}/release_manifest.json"
    manifest = json.loads(path.read_bytes())
    if manifest.get("name") != "eth-research":
        problems.append(f"{mf} records an unexpected package name")
    if manifest.get("version") != VERSION:
        problems.append(
            f"{mf} records version {manifest.get('version')!r} "
            f"(expected the frozen release version {VERSION!r})"
        )
    if manifest.get("runtime_dependencies") != _runtime_dependencies(repo_root):
        problems.append(f"{mf} runtime_dependencies drifted from pyproject")
    ds = manifest.get("distribution_source", {})
    members = ds.get("members", [])
    recomputed = _sha256_bytes(
        "".join(f"{m['sha256']}  {m['path']}\n" for m in members).encode("utf-8")
    )
    if recomputed != ds.get("tree_digest"):
        problems.append(f"{mf} distribution_source tree_digest is inconsistent")
    if ds.get("member_count") != len(members):
        problems.append(f"{mf} distribution_source member_count is inconsistent")
    governed = manifest.get("governed_state", {})
    if governed.get("baseline_digest") != GOVERNED_BASELINE_DIGEST:
        problems.append(f"{mf} records a stale governed baseline digest")
    if governed.get("sealed_ledgers") != dict.fromkeys(SEALED_LEDGERS, EMPTY_SHA):
        problems.append(f"{mf} records non-empty sealed ledgers")
    return problems


def check(repo_root: Path) -> list[str]:
    problems = []
    outdir = repo_root / RELDIR
    # Under a later development version, the v1.1.0 release evidence is a *historical* artifact:
    # its source-derived manifest was built from the v1.1.0 tree and is verified for its own
    # recorded identity rather than reproduced from the diverged live tree. The sbom and
    # release_state are version-independent (the sbom excludes eth-research itself; the state is a
    # posture record), so they are still rebuilt-and-compared in both modes.
    historical = _active_version(repo_root) != VERSION
    for name, builder in _ARTIFACTS.items():
        path = outdir / name
        if not path.exists():
            problems.append(f"{RELDIR}/{name} is missing")
            continue
        if historical and name == "release_manifest.json":
            problems.extend(_check_release_manifest_historical(path, repo_root))
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
        written = write(root)
        print(f"wrote {', '.join(written)} under {RELDIR}/")
        skipped = sorted(set(_ARTIFACTS) - set(written))
        if skipped:
            print(
                f"kept the historical {', '.join(skipped)} "
                f"(active version {_active_version(root)} has moved past the frozen {VERSION})"
            )
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
