"""Deterministic snapshot of the public API surface, with a drift ``--check`` guard.

The snapshot records every name in :data:`eth_research.api.__all__` together with a stable
descriptor — an exception's code/exit-code/category and bases, a dataclass's ordered fields
and public methods, a class/protocol's bases and public methods, a function's exact
signature, or a constant's JSON value. It is keyed by the public-contract ``API_VERSION``
(not the package version), so a normal version bump does not perturb it while any change to
the public surface does. ``verify`` fails closed when the committed snapshot no longer
matches the running package, so an accidental public-API change cannot slip through review.
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import sys
from pathlib import Path
from typing import Any

from eth_research import api
from eth_research.api.serialization import canonical_json_bytes, strict_load_canonical

SNAPSHOT_RELPATH = "research/m4a/public_api.json"
SNAPSHOT_SCHEMA_VERSION = 1


class PublicAPIDriftError(RuntimeError):
    """The committed public-API snapshot no longer matches the running package."""


def _public_methods(obj: type) -> list[str]:
    names = []
    for name, _member in inspect.getmembers(obj):
        if name.startswith("_"):
            continue
        names.append(name)
    return sorted(names)


def _json_value(value: Any) -> Any:
    """A canonically-serializable representation of a constant, or ``None`` if not simple."""
    try:
        canonical_json_bytes(value)
    except Exception:
        return None
    return value


def _describe(obj: object) -> dict[str, Any]:
    if inspect.isclass(obj):
        bases = [base.__name__ for base in obj.__bases__ if base is not object]
        if issubclass(obj, BaseException):
            return {
                "kind": "exception",
                "bases": bases,
                "code": getattr(obj, "code", None),
                "exit_code": getattr(obj, "exit_code", None),
                "category": getattr(obj, "category", None),
            }
        if dataclasses.is_dataclass(obj):
            fields = [
                {"name": field.name, "type": str(field.type)} for field in dataclasses.fields(obj)
            ]
            params = getattr(obj, "__dataclass_params__", None)
            return {
                "kind": "dataclass",
                "frozen": bool(getattr(params, "frozen", False)),
                "fields": fields,
                "methods": _public_methods(obj),
            }
        return {"kind": "class", "bases": bases, "methods": _public_methods(obj)}
    if inspect.isfunction(obj):
        return {"kind": "function", "signature": str(inspect.signature(obj))}
    return {"kind": "constant", "type": type(obj).__name__, "value": _json_value(obj)}


def build_snapshot() -> dict[str, Any]:
    """Build the canonical public-API snapshot for the running package."""
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "api_version": api.API_VERSION,
        "symbols": {name: _describe(getattr(api, name)) for name in sorted(api.__all__)},
    }


def snapshot_bytes() -> bytes:
    return canonical_json_bytes(build_snapshot())


def verify(repo_root: str | Path) -> None:
    """Raise :class:`PublicAPIDriftError` unless the committed snapshot matches the package."""
    path = Path(repo_root) / SNAPSHOT_RELPATH
    try:
        committed = path.read_bytes()
    except OSError as exc:
        raise PublicAPIDriftError(
            f"public-API snapshot missing at {SNAPSHOT_RELPATH}: {exc}"
        ) from exc
    fresh = snapshot_bytes()
    if committed != fresh:
        # canonicalize the committed bytes too, so a whitespace-only diff is not a false alarm
        recanonical = canonical_json_bytes(strict_load_canonical(committed, "public_api"))
        if recanonical != fresh:
            raise PublicAPIDriftError(
                "the public API changed but research/m4a/public_api.json was not regenerated"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Public-API snapshot: --check or --write.")
    parser.add_argument("--repo-root", default=".")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed snapshot")
    group.add_argument("--write", action="store_true", help="(re)write the committed snapshot")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / SNAPSHOT_RELPATH
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot_bytes())
        sys.stdout.write(f"wrote {SNAPSHOT_RELPATH}\n")
        return 0
    try:
        verify(args.repo_root)
    except PublicAPIDriftError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write("public API snapshot is current\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
