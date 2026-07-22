"""V2C sections 23-24: read-only OQ status / replay / verify / recover CLIs.

State-aware and offline. ``replay`` re-derives every V2C OQ governance invariant from the committed
source -- the OQ source freeze, the protocol bundle, the supersession chain -- and, depending on the
registry lifecycle state, either confirms the pristine (not-yet-run) posture or deep-verifies the
completed run archive and independently re-accepts it through the OQ-Q oracle. All three sealed
access ledgers are asserted byte-empty throughout. Every command is read-only except
``recover --finalize``, the calculation-free finalizer for a crashed-but-published run.

    python -m eth_research.v2c.oq.cli status  --repo-root .
    python -m eth_research.v2c.oq.cli replay  --repo-root .
    python -m eth_research.v2c.oq.cli verify  --repo-root .
    python -m eth_research.v2c.oq.cli recover --repo-root . [--finalize]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eth_research.v2.strict import V2ValidationError, sha256_bytes
from eth_research.v2c.oq import finalize as _finalize
from eth_research.v2c.oq.completion import OQ_COMPLETION_INTENT_RELPATH
from eth_research.v2c.oq.freeze import verify_oq_source_freeze
from eth_research.v2c.oq.oracle import assert_independent_acceptance
from eth_research.v2c.oq.orchestrator import PREMATURE_OQ_FREEZE_COMMIT
from eth_research.v2c.oq.protocol import verify_oq_protocol_bundle
from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH, registry_state
from eth_research.v2c.oq.supersession import (
    EMPTY_SHA256,
    OQ_SUPERSESSION_PATH,
    SEALED_LEDGER_RELPATHS,
    assert_freeze_superseded,
    verify_supersession,
)
from eth_research.v2c.oq.verify_archive import OQRunArchiveError, verify_oq_run_archive


class OQCLIError(V2ValidationError):
    """A read-only OQ CLI invariant failed."""


def _registry_state(reg: Path) -> str:
    return registry_state(reg) if reg.exists() else "pristine"


def _assert_sealed_ledgers_empty(root: Path) -> None:
    for rel in SEALED_LEDGER_RELPATHS:
        path = root / rel
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256_bytes(path.read_bytes()) != EMPTY_SHA256
        ):
            raise OQCLIError(f"sealed ledger {rel} is missing or not byte-empty")


def status(root: Path, reg: Path) -> dict[str, object]:
    return {
        "registry_state": _registry_state(reg),
        "pending_completion_intent": (root / OQ_COMPLETION_INTENT_RELPATH).exists(),
    }


def replay(root: Path, reg: Path) -> list[str]:
    """State-aware read-only replay. Returns the ordered passed checks; raises on any violation."""
    checks: list[str] = []
    verify_oq_source_freeze(root)
    checks.append("source_freeze_reproduces")
    verify_oq_protocol_bundle(root)
    checks.append("protocol_bundle_reproduces")
    problems = verify_supersession(root / OQ_SUPERSESSION_PATH)
    if problems:
        raise OQCLIError("supersession ledger is not clean: " + "; ".join(problems))
    assert_freeze_superseded(root / OQ_SUPERSESSION_PATH, PREMATURE_OQ_FREEZE_COMMIT)
    checks.append("premature_freeze_recorded_superseded")
    _assert_sealed_ledgers_empty(root)
    checks.append("sealed_ledgers_byte_empty")

    state = _registry_state(reg)
    if state == "pristine":
        if reg.exists() and reg.stat().st_size != 0:
            raise OQCLIError("registry is byte-nonempty but reports pristine")
        checks.append("registry_pristine_no_run_registered")
    elif state == "completed":
        checks.extend(verify_oq_run_archive(root, reg))
        assert_independent_acceptance(root, reg)
        checks.append("oq_q_oracle_independently_accepts")
    else:
        raise OQCLIError(f"registry is {state!r} (an unfinalized run); replay cannot certify it")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.v2c.oq.cli", description="V2C OQ CLIs")
    parser.add_argument("command", choices=("status", "replay", "verify", "recover"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--registry", default=None)
    parser.add_argument(
        "--finalize", action="store_true", help="recover: append the recorded event"
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    reg = Path(args.registry) if args.registry else root / OQ_REGISTRY_PATH

    try:
        if args.command == "status":
            print(json.dumps({"ok": True, **status(root, reg)}))
            return 0
        if args.command == "replay":
            print(json.dumps({"ok": True, "checks": replay(root, reg)}))
            return 0
        if args.command == "verify":
            if _registry_state(reg) != "completed":
                print(json.dumps({"ok": True, "state": _registry_state(reg), "checks": []}))
                return 0
            print(json.dumps({"ok": True, "checks": list(verify_oq_run_archive(root, reg))}))
            return 0
        # recover
        result = _finalize.finalize(root, reg) if args.finalize else _finalize.assess(root, reg)
        ok = result.state in (
            _finalize.STATE_FINALIZED,
            _finalize.STATE_ALREADY_FINALIZED,
            _finalize.STATE_NO_INTENT,
            _finalize.STATE_FINALIZABLE,
        )
        print(json.dumps({"ok": ok, "state": result.state, "detail": result.detail}))
        return 0 if ok else 1
    except (OSError, V2ValidationError, OQRunArchiveError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["OQCLIError", "main", "replay", "status"]
