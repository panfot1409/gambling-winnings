"""Disposable-clone recovery drill for Milestone 3F.

The drill reconstructs the private capsule (see :mod:`eth_research.m3f.bundle`)
into a throwaway directory and proves two things about the reconstruction:

* it reproduces byte-for-byte (every manifest file re-hashes; the capsule digest
  re-derives); and
* it re-derives the honest governance state and passes the semantic oracles — a
  reconstructed tree that is not *also* governance-honest is not a recovery.

It then runs *failure drills*: each corrupts the reconstruction (a dropped file, a
flipped byte, an injected production proposal, a non-empty sealed ledger, a broken
registry chain) and confirms the corresponding verifier detects it. A drill that a
verifier fails to catch is itself a finding.

The drill record contains only digests, counts, and boolean outcomes — never a
temporary path or a timestamp — so it is byte-reproducible and safe to commit.
Strictly read-only with respect to the repository: the only writes are into a
disposable directory that is deleted when the drill ends.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from eth_research.m3f import M3F_PACKAGE_VERSION
from eth_research.m3f.bundle import build_manifest, verify_materialized
from eth_research.m3f.honest_state import derive_honest_state
from eth_research.m3f.oracle import run_oracles
from eth_research.m3f.validation import (
    M3FValidationError,
    canonical_json_bytes,
    load_canonical_json,
)

DRILL_RELPATH = "research/m3f/recovery_drill.json"
DRILL_SCHEMA_VERSION = 1
_REGISTRY = "research/m3e/proposal_registry.jsonl"
_A_LEDGER = "research/m2b/test_evaluations.jsonl"
_COMPACT_PROPOSAL = '{"entry_kind":"proposal","proposal_created":true,"schema_version":1}'


def _materialize(
    manifest: dict[str, Any],
    source_root: Path,
    dest: Path,
    *,
    drop: frozenset[str] = frozenset(),
    replace: Mapping[str, bytes] | None = None,
) -> None:
    overrides = dict(replace or {})
    for entry in manifest["files"]:
        rel = entry["path"]
        if rel in drop:
            continue
        raw = overrides.get(rel)
        if raw is None:
            raw = (source_root / rel).read_bytes()
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)


def recovery_drill(repo_root: str | Path) -> dict[str, Any]:
    """Reconstruct the capsule in a disposable directory and verify it fully."""
    root = Path(repo_root)
    manifest = build_manifest(root)
    with tempfile.TemporaryDirectory(prefix="m3f-recovery-") as tmp:
        dest = Path(tmp)
        _materialize(manifest, root, dest)
        materialize_failures = verify_materialized(manifest, dest)
        try:
            derive_honest_state(dest)
            honest_ok = True
        except M3FValidationError:
            honest_ok = False
        oracle_report = run_oracles(dest)
    return {
        "capsule_digest": manifest["capsule_digest"],
        "capsule_file_count": manifest["file_count"],
        "byte_reproduced": not materialize_failures,
        "honest_state_derived": honest_ok,
        "oracles_ok": oracle_report.ok,
        "materialize_failures": materialize_failures[:5],
        "ok": bool(not materialize_failures and honest_ok and oracle_report.ok),
    }


def _detect_materialized(manifest: dict[str, Any], root: Path) -> bool:
    return bool(verify_materialized(manifest, root))


def _detect_honest_state(_manifest: dict[str, Any], root: Path) -> bool:
    try:
        derive_honest_state(root)
    except M3FValidationError:
        return True
    return False


def _detect_oracles(_manifest: dict[str, Any], root: Path) -> bool:
    return not run_oracles(root).ok


def _run_failure_drill(
    name: str,
    manifest: dict[str, Any],
    source_root: Path,
    *,
    drop: frozenset[str] = frozenset(),
    replace: Mapping[str, bytes] | None = None,
    detector: Callable[[dict[str, Any], Path], bool],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="m3f-drill-") as tmp:
        dest = Path(tmp)
        _materialize(manifest, source_root, dest, drop=drop, replace=replace)
        detected = detector(manifest, dest)
    return {"name": name, "detected": detected}


def failure_drills(repo_root: str | Path) -> dict[str, Any]:
    """Each corruption of the reconstruction must be detected by a verifier."""
    root = Path(repo_root)
    manifest = build_manifest(root)
    first_file = manifest["files"][0]["path"]
    registry_bytes = (root / _REGISTRY).read_bytes()
    injected = registry_bytes + _COMPACT_PROPOSAL.encode("utf-8") + b"\n"
    corrupted_registry = _corrupt_chain(registry_bytes)

    drills = [
        _run_failure_drill(
            "dropped_file",
            manifest,
            root,
            drop=frozenset({first_file}),
            detector=_detect_materialized,
        ),
        _run_failure_drill(
            "flipped_byte",
            manifest,
            root,
            replace={first_file: (root / first_file).read_bytes() + b"\x00"},
            detector=_detect_materialized,
        ),
        _run_failure_drill(
            "injected_proposal",
            manifest,
            root,
            replace={_REGISTRY: injected},
            detector=_detect_honest_state,
        ),
        _run_failure_drill(
            "nonempty_sealed_ledger",
            manifest,
            root,
            replace={_A_LEDGER: b'{"leak":true}\n'},
            detector=_detect_honest_state,
        ),
        _run_failure_drill(
            "broken_registry_chain",
            manifest,
            root,
            replace={_REGISTRY: corrupted_registry},
            detector=_detect_oracles,
        ),
    ]
    drills.sort(key=lambda d: d["name"])
    return {"drills": drills, "all_detected": all(d["detected"] for d in drills)}


def _corrupt_chain(registry_bytes: bytes) -> bytes:
    """Flip one hex digit of a back-pointer so the chain no longer reproduces."""
    text = registry_bytes.decode("utf-8")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if '"previous_line_sha256":"' in line and "genesis" not in line:
            marker = '"previous_line_sha256":"'
            start = line.index(marker) + len(marker)
            original = line[start]
            swapped = "0" if original != "0" else "1"
            lines[index] = line[:start] + swapped + line[start + 1 :]
            break
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_drill_record(repo_root: str | Path) -> dict[str, Any]:
    """Deterministic drill record (digests + counts + booleans only)."""
    recon = recovery_drill(repo_root)
    negatives = failure_drills(repo_root)
    return {
        "schema_version": DRILL_SCHEMA_VERSION,
        "package_version": M3F_PACKAGE_VERSION,
        "capsule_digest": recon["capsule_digest"],
        "capsule_file_count": recon["capsule_file_count"],
        "reconstruction_ok": recon["ok"],
        "reconstruction_byte_reproduced": recon["byte_reproduced"],
        "reconstruction_honest_state_derived": recon["honest_state_derived"],
        "reconstruction_oracles_ok": recon["oracles_ok"],
        "failure_drills": [
            {"name": d["name"], "detected": d["detected"]} for d in negatives["drills"]
        ],
        "all_failure_drills_detected": negatives["all_detected"],
    }


def render_drill_bytes(record: dict[str, Any]) -> bytes:
    return canonical_json_bytes(record)


def verify_drill_record(repo_root: str | Path) -> None:
    """The committed drill record reproduces from a fresh drill and reports success."""
    root = Path(repo_root)
    committed = load_canonical_json((root / DRILL_RELPATH).read_bytes(), "recovery_drill")
    fresh = build_drill_record(root)
    if canonical_json_bytes(committed) != canonical_json_bytes(fresh):
        raise M3FValidationError("recovery drill record drifted from a fresh drill")
    if not committed.get("reconstruction_ok") or not committed.get("all_failure_drills_detected"):
        raise M3FValidationError("committed recovery drill record does not report full success")


def _drill_payload(repo_root: str | Path) -> dict[str, Any]:
    record = build_drill_record(repo_root)
    return {
        "ok": bool(record["reconstruction_ok"] and record["all_failure_drills_detected"]),
        "capsule_digest": record["capsule_digest"],
        "capsule_file_count": record["capsule_file_count"],
        "all_failure_drills_detected": record["all_failure_drills_detected"],
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    from eth_research.m3f.cli import repo_root_parser, run_guarded

    args = repo_root_parser("M3F disposable-clone recovery drill (read-only)").parse_args(argv)
    return run_guarded(lambda: _drill_payload(args.repo_root), as_json=args.json or args.deep)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
