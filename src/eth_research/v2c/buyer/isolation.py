"""V2C sections 24 & 26: run the buyer client isolated, and prove non-interference.

Spawns the source-free buyer client as a child process from a temp root, with **fixed argv,
``shell=False``, an isolated + no-site interpreter (``-I -S``), and a minimal environment** (no
``PYTHONPATH``). ``-S`` disables ``site.py`` so the editable-install ``.pth`` is never processed and
the child genuinely cannot import the repository package. The parent acts as the vendor: it drives
the same length-prefixed session server (:func:`serve_session`) over the child's pipes, serving only
redacted artifacts. Afterwards it proves the child ran source-free and stdlib-only (scanning the
on-disk client that actually runs), received only redacted artifacts (withheld items were refused),
wrote nothing outside its temp root but the transcript, and did not perturb the vendor's evaluation
surface (contract fingerprint unchanged).

Honest limitation: the vendor process still holds the private implementation, and this harness
imposes no OS-level sandbox (namespace/seccomp/chroot) -- a determined child still has the user's
filesystem and network. This proves process isolation from the repo package, redaction, and
non-interference of the *shipped* client -- not independent deployment, and not containment of an
arbitrary hostile binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from eth_research.v2c.buyer.boundary import (
    MAX_REQUESTS_PER_SESSION,
    SessionSummary,
    open_vendor_gateway,
    serve_session,
)
from eth_research.v2c.buyer.harness import (
    CLIENT_FILENAME,
    CLIENT_STDLIB_ALLOWLIST,
    build_harness,
    client_import_modules,
    double_build_is_identical,
    scan_source_free,
)

_TRANSCRIPT_NAME: str = "buyer_transcript.json"
_CHILD_TIMEOUT_SECONDS: int = 60
_JOIN_TIMEOUT_SECONDS: int = 5
_WITHHELD_PROBE: str = "source_code"

#: The interpreter flags the child buyer client runs under. ``-I`` isolates it (ignores ``PYTHON*``
#: env vars and the user site), ``-S`` disables ``site.py`` so the editable ``.pth`` is never
#: processed and the child genuinely cannot import the repository package, and ``-B`` writes no
#: bytecode. ``-S`` is what makes the isolation real; ``tests/test_v2c_buyer_boundary.py`` proves a
#: child run with these flags cannot import ``eth_research`` while the same run without ``-S`` can.
ISOLATION_FLAGS: tuple[str, ...] = ("-I", "-S", "-B")

#: The session summary recorded when the driver thread produced none (e.g. a killed, hung child).
_EMPTY_SESSION: SessionSummary = SessionSummary(
    requests_received=0,
    artifacts_served=0,
    refusals=0,
    errors=0,
    quota_exceeded=False,
    response_bytes=0,
)


@dataclass(frozen=True, slots=True)
class IsolationCheck:
    """One isolation/non-interference check and whether it held."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class IsolationReport:
    """The process-isolated buyer-evaluation outcome."""

    checks: tuple[IsolationCheck, ...]
    session: SessionSummary
    transcript: dict[str, object]
    passed: bool


def _harness_tree(harness_dir: Path) -> set[str]:
    """Every file under the harness dir, recursively, as a posix relative path (whole subtree)."""
    return {
        path.relative_to(harness_dir).as_posix()
        for path in harness_dir.rglob("*")
        if path.is_file()
    }


def _outside_harness_tree(root: Path, harness_dir: Path) -> set[str]:
    """Every file under the temp root *not* under the harness dir -- a write here escaped."""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and harness_dir not in path.parents
    }


def _minimal_env() -> dict[str, str]:
    # Only PATH is carried through; no PYTHONPATH, so the child cannot reach the repository source.
    env = {"PATH": os.environ.get("PATH", "")}
    home = os.environ.get("HOME")
    if home:
        env["HOME"] = home
    return env


def run_isolated_buyer_evaluation(*, workdir: str | Path) -> IsolationReport:
    """Build the harness, run the buyer client isolated, and produce the isolation report."""
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    harness_dir = build_harness(root / "harness")
    checks: list[IsolationCheck] = []

    source_free_problems = scan_source_free(harness_dir)
    checks.append(
        IsolationCheck(
            "harness_source_free",
            not source_free_problems,
            "no strategy source/wheel/bytecode/raw-data/private-URL"
            if not source_free_problems
            else "; ".join(source_free_problems),
        )
    )
    double_ok = double_build_is_identical(root / "double_build")
    checks.append(
        IsolationCheck(
            "harness_double_builds_identical",
            double_ok,
            "two builds are byte-identical" if double_ok else "builds differ",
        )
    )
    # Scan the on-disk client that will actually run (not just the in-memory constant), so the
    # stdlib-only proof is bound to the executed artifact and rejects any dynamic import.
    client_source = (harness_dir / CLIENT_FILENAME).read_text(encoding="utf-8")
    imports = client_import_modules(client_source)
    stdlib_only = imports <= CLIENT_STDLIB_ALLOWLIST
    checks.append(
        IsolationCheck(
            "client_imports_only_stdlib",
            stdlib_only,
            f"client imports {sorted(imports)} (all stdlib, no dynamic import)"
            if stdlib_only
            else f"client imports non-stdlib/dynamic {sorted(imports - CLIENT_STDLIB_ALLOWLIST)}",
        )
    )

    before = _harness_tree(harness_dir)
    gateway = open_vendor_gateway()
    contract_before = gateway.contract().fingerprint()
    available_before = gateway.available()

    client = harness_dir / CLIENT_FILENAME
    stderr_path = root / "buyer_stderr.log"
    with stderr_path.open("wb") as stderr_file:
        # Baseline the temp root *after* the parent's own stderr log exists, so only the child's own
        # out-of-harness writes count as an escape.
        root_before = _outside_harness_tree(root, harness_dir)
        proc = subprocess.Popen(
            [sys.executable, *ISOLATION_FLAGS, str(client)],
            cwd=str(harness_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            env=_minimal_env(),
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        # Drive the vendor session on a watchdog thread: a hostile child that opens a frame and
        # then stalls would otherwise block the parent's read forever. On timeout we kill the
        # child, which closes the pipe and unblocks the read; the run is then a failed check.
        session_box: list[SessionSummary] = []

        def _drive() -> None:
            session_box.append(
                serve_session(
                    gateway,
                    cast(BinaryIO, proc.stdout),
                    cast(BinaryIO, proc.stdin),
                    max_requests=MAX_REQUESTS_PER_SESSION,
                )
            )

        driver = threading.Thread(target=_drive, daemon=True)
        driver.start()
        driver.join(timeout=_CHILD_TIMEOUT_SECONDS)
        timed_out = driver.is_alive()
        if timed_out:
            proc.kill()
            driver.join(timeout=_JOIN_TIMEOUT_SECONDS)
        try:
            proc.stdin.close()
            proc.stdout.close()
        except OSError:  # pragma: no cover - pipe already closed after a kill
            pass
        returncode = proc.wait(timeout=_CHILD_TIMEOUT_SECONDS)
        session = session_box[0] if session_box else _EMPTY_SESSION

    contract_after = gateway.contract().fingerprint()
    checks.append(
        IsolationCheck(
            "vendor_non_interference",
            contract_before == contract_after and available_before == gateway.available(),
            "vendor evaluation surface unchanged by the buyer session"
            if contract_before == contract_after
            else "vendor contract fingerprint changed",
        )
    )

    transcript_path = harness_dir / _TRANSCRIPT_NAME
    ran_ok = returncode == 0 and transcript_path.is_file()
    checks.append(
        IsolationCheck(
            "buyer_ran_isolated",
            ran_ok,
            "buyer client ran to completion in its temp root"
            if ran_ok
            else f"returncode={returncode}, transcript={transcript_path.is_file()}",
        )
    )
    transcript: dict[str, object] = {}
    if transcript_path.is_file():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    entries = transcript.get("transcript", [])
    withheld_served = isinstance(entries, list) and any(
        isinstance(e, dict)
        and e.get("item") == _WITHHELD_PROBE
        and e.get("response_kind") == "artifact"
        for e in entries
    )
    withheld_refused = isinstance(entries, list) and any(
        isinstance(e, dict)
        and e.get("item") == _WITHHELD_PROBE
        and e.get("response_kind") == "refused"
        for e in entries
    )
    checks.append(
        IsolationCheck(
            "buyer_got_only_redacted",
            (not withheld_served) and withheld_refused and session.artifacts_served > 0,
            "withheld item refused; only redacted artifacts served"
            if ((not withheld_served) and withheld_refused)
            else f"withheld_served={withheld_served} withheld_refused={withheld_refused}",
        )
    )

    after = _harness_tree(harness_dir)
    new_in_harness = after - before
    escaped = _outside_harness_tree(root, harness_dir) - root_before
    confined = new_in_harness == {_TRANSCRIPT_NAME} and not escaped
    checks.append(
        IsolationCheck(
            "buyer_writes_confined_to_temp_root",
            confined,
            "only the transcript was written into the temp root (no writes outside the harness dir)"
            if confined
            else f"unexpected in harness={sorted(new_in_harness)}; escaped={sorted(escaped)}",
        )
    )

    return IsolationReport(
        checks=tuple(checks),
        session=session,
        transcript=transcript,
        passed=all(check.passed for check in checks),
    )


__all__ = [
    "ISOLATION_FLAGS",
    "IsolationCheck",
    "IsolationReport",
    "run_isolated_buyer_evaluation",
]
