"""V2C sections 24 & 26: run the buyer client isolated, and prove non-interference.

Spawns the source-free buyer client as a child process from a temp root, with **fixed argv,
``shell=False``, an isolated interpreter (``-I``), and a minimal environment** (no ``PYTHONPATH`` to
the repository). The parent acts as the vendor: it drives the same length-prefixed session server
(:func:`serve_session`) over the child's pipes, serving only redacted artifacts. Afterwards it
proves the child ran source-free and stdlib-only, received only redacted artifacts (withheld items
were refused), wrote nothing outside its temp root but the transcript, and did not perturb the
vendor's evaluation surface (contract fingerprint unchanged).

Honest limitation: the vendor process still holds the private implementation. This proves process
isolation, redaction, and non-interference -- not independent deployment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
_WITHHELD_PROBE: str = "source_code"


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
    imports = client_import_modules()
    stdlib_only = imports <= CLIENT_STDLIB_ALLOWLIST
    checks.append(
        IsolationCheck(
            "client_imports_only_stdlib",
            stdlib_only,
            f"client imports {sorted(imports)} (all stdlib)"
            if stdlib_only
            else f"client imports non-stdlib {sorted(imports - CLIENT_STDLIB_ALLOWLIST)}",
        )
    )

    before = set(os.listdir(harness_dir))
    gateway = open_vendor_gateway()
    contract_before = gateway.contract().fingerprint()
    available_before = gateway.available()

    client = harness_dir / CLIENT_FILENAME
    stderr_path = root / "buyer_stderr.log"
    with stderr_path.open("wb") as stderr_file:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-B", str(client)],
            cwd=str(harness_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            env=_minimal_env(),
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        try:
            session = serve_session(
                gateway,
                cast(BinaryIO, proc.stdout),
                cast(BinaryIO, proc.stdin),
                max_requests=MAX_REQUESTS_PER_SESSION,
            )
        finally:
            proc.stdin.close()
            proc.stdout.close()
        returncode = proc.wait(timeout=_CHILD_TIMEOUT_SECONDS)

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

    after = set(os.listdir(harness_dir))
    new_files = after - before
    confined = new_files == {_TRANSCRIPT_NAME}
    checks.append(
        IsolationCheck(
            "buyer_writes_confined_to_temp_root",
            confined,
            "only the transcript was written into the temp root"
            if confined
            else f"unexpected new files: {sorted(new_files)}",
        )
    )

    return IsolationReport(
        checks=tuple(checks),
        session=session,
        transcript=transcript,
        passed=all(check.passed for check in checks),
    )


__all__ = [
    "IsolationCheck",
    "IsolationReport",
    "run_isolated_buyer_evaluation",
]
