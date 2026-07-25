"""Shared machinery for the acceptance-layer probe truth table.

Every probe runs in its own disposable clone (§0: no test runs against source that
is concurrently being edited, and no probe mutates the real worktree). Each probe
gets the *maximal* attacker: after the semantic mutation, every digest the
attacker can reach is recomputed with the project's own primitives, so a probe
that is caught is caught by a semantic invariant and not by a seal the attacker
simply forgot to refresh.

The four readers, run identically for every probe:

  production   eth_research.m3e.acceptance.verify_acceptance_program (library call)
  public_entry python -m eth_research.m3e.acceptance --repo-root . check (the CLI)
  m3f          python -m eth_research.m3f.audit (compatibility path)
  stdlib       tools/m3f_independent_verify.py (no eth_research at all)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRATCH = (
    Path(os.environ.get("ACCEPTANCE_PROBE_WORKDIR", tempfile.gettempdir()))
    / "acceptance-probe-runs"
)
PY = str(REPO / ".venv/bin/python")
BRANCH = "claude/v2e-proposal-acceptance-001"
PROPOSAL_ID = "20260715-20260724-315846f9ec5196b4"

ACC_DIR = f"research/m3e/acceptances/{PROPOSAL_ID}"
ACC = f"{ACC_DIR}/acceptance.json"
COMP = f"{ACC_DIR}/acceptance_completion.json"
REGISTRY = "research/m3e/acceptance_registry.jsonl"
PROPOSAL_DIR = f"research/m3e/proposals/{PROPOSAL_ID}"
MANIFEST = f"{PROPOSAL_DIR}/proposal_manifest.json"
ACCEPTED_BASE = "research/m3e/accepted_base.json"
BUNDLE_DIR = (
    "research/m3d/raw/coinbase/"
    "coinbase-eth-usd-prospective-update-20260715-20260723-315846f9ec5196b4"
)
AUTHORITY_SRC = "src/eth_research/m3e/proposal_authority.py"

READERS: tuple[tuple[str, list[str], bool], ...] = (
    # (label, argv, needs PYTHONPATH=src)
    (
        "production",
        [
            PY,
            "-c",
            "import sys;sys.path.insert(0,'src');"
            "from eth_research.m3e.acceptance import verify_acceptance_program as v;"
            "v('.')",
        ],
        False,
    ),
    ("public_entry", [PY, "-m", "eth_research.m3e.acceptance", "--repo-root", ".", "check"], True),
    ("m3f", [PY, "-m", "eth_research.m3f.audit", "--repo-root", "."], True),
    ("stdlib", [PY, "tools/m3f_independent_verify.py", "--repo-root", "."], False),
)


# ---------------------------------------------------------------------------
# disposable clones
# ---------------------------------------------------------------------------


def require_clean_repo() -> str:
    """The real worktree must be clean before any probe runs (§0 single writer)."""
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        raise SystemExit(
            f"REFUSING: real worktree is dirty, probes would test unknown source:\n{dirty}"
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def clone(name: str) -> Path:
    dest = SCRATCH / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(REPO), str(dest)], check=True
    )
    subprocess.run(["git", "checkout", "--quiet", BRANCH], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.email", "probe@example.invalid"], cwd=dest, check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=dest, check=True)
    return dest


def run(argv: list[str], cwd: Path, src_path: bool = False, timeout: int = 900) -> tuple[int, str]:
    env = dict(os.environ)
    if src_path:
        env["PYTHONPATH"] = "src"
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def read_json(root: Path, relpath: str) -> Any:
    return json.loads((root / relpath).read_text())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def byte_delta(root: Path) -> dict[str, int]:
    """Exactly what the mutation changed, measured from git rather than claimed."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    changed = [rec[3:] for rec in out.split("\0") if rec.strip()]
    numstat = (
        subprocess.run(
            ["git", "diff", "--numstat", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    added = deleted = 0
    for line in numstat:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            deleted += int(parts[1])
    return {"files_changed": len(changed), "lines_added": added, "lines_deleted": deleted}


# ---------------------------------------------------------------------------
# maximal attacker reseal
# ---------------------------------------------------------------------------

RESEAL_SRC = r"""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, "src")

from eth_research.m3e.acceptance import (
    ACCEPTANCE_REGISTRY_PATH, ACCEPTANCE_SCHEMA_VERSION, M3E_PACKAGE_VERSION,
    build_genesis_record, completion_self_hash, record_self_hash,
)
from eth_research.m3e.proposal_file_policy import (
    build_record_binding, verify_proposal_file_policy,
)
from eth_research.m3d.chain import chained_line_bytes, render_ledger_bytes
from eth_research.m3e.validation import canonical_json_bytes

ROOT = Path(".").resolve()
PROPOSAL_ID = %(pid)r
ACC_DIR = ROOT / "research/m3e/acceptances" / PROPOSAL_ID
STEPS = set(json.loads(%(steps)r))
done = []

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

record = json.loads((ACC_DIR / "acceptance.json").read_text())
completion = json.loads((ACC_DIR / "acceptance_completion.json").read_text())

# --- 1. the proposal manifest's own self-hash, if the bundle moved -----------
if "manifest" in STEPS:
    mpath = ROOT / "research/m3e/proposals" / PROPOSAL_ID / "proposal_manifest.json"
    man = json.loads(mpath.read_text())
    field = "manifest_sha256" if "manifest_sha256" in man else "proposal_manifest_sha256"
    body = {k: v for k, v in man.items() if k != field}
    for key in ("files", "members", "member_sha256"):
        if isinstance(man.get(key), dict):
            man[key] = {
                k: (sha(ROOT / k) if (ROOT / k).is_file() else v) for k, v in man[key].items()
            }
            body = {k: v for k, v in man.items() if k != field}
    digest = hashlib.sha256(
        b"m3e/proposal_manifest\n" + canonical_json_bytes(body)
    ).hexdigest()
    man[field] = digest
    mpath.write_bytes(canonical_json_bytes(man) + b"\n")
    record["proposal_manifest_sha256"] = sha(mpath)
    done.append("manifest")

# --- 2. every created/state pin, recomputed from what is actually on disk ----
if "pins" in STEPS:
    created = record["new_accepted"]["created"]
    record["new_accepted"]["created"] = {
        k: sha(ROOT / k) for k in sorted(created) if (ROOT / k).is_file()
    }
    # ONLY new_accepted.state is a statement about the tree as it is now.
    # previous_accepted.state describes the pre-update world and is historical;
    # recomputing it from disk would be a transcription error, not an attack.
    st = record["new_accepted"].get("state")
    if isinstance(st, dict):
        record["new_accepted"]["state"] = {
            k: (sha(ROOT / k) if (ROOT / k).is_file() else v) for k, v in st.items()
        }
    if (ROOT / "research/m3e/accepted_base.json").is_file():
        record["new_accepted"]["accepted_base_file_sha256"] = sha(
            ROOT / "research/m3e/accepted_base.json"
        )
    done.append("pins")

# --- 3. the file-set binding, re-derived by the attacker with the same policy -
if "binding" in STEPS:
    verified = verify_proposal_file_policy(
        ROOT,
        proposal_id=PROPOSAL_ID,
        parent_commit=record["expected_parent_commit"],
        head_commit=record["proposal_head_commit"],
        declared_paths={
            "created_pins": sorted(record["new_accepted"]["created"]),
            "state_pins": sorted(record["new_accepted"]["state"]),
        },
        require_full_cover=True,
    )
    record["file_set_binding"] = build_record_binding(ROOT, verified)
    done.append("binding")

# --- 4/5. the record's and completion's self-hashes --------------------------
# Conditional, like every other step: a probe that attacks the CHAIN must not
# have its mutation silently rebuilt away by the reseal that is supposed to be
# helping the attacker, not undoing them.
if "self_hashes" in STEPS:
    body = {k: v for k, v in record.items() if k != "acceptance_sha256"}
    record = dict(body)
    record["acceptance_sha256"] = record_self_hash(body)
    (ACC_DIR / "acceptance.json").write_bytes(canonical_json_bytes(record) + b"\n")

    cbody = {k: v for k, v in completion.items() if k != "completion_sha256"}
    cbody["acceptance_sha256"] = record["acceptance_sha256"]
    completion = dict(cbody)
    completion["completion_sha256"] = completion_self_hash(cbody)
    (ACC_DIR / "acceptance_completion.json").write_bytes(
        canonical_json_bytes(completion) + b"\n"
    )
    done.append("self_hashes")

# --- 6. the registry hash chain ---------------------------------------------
if "registry" in STEPS:
    bodies = [build_genesis_record(ROOT)]
    bodies.append({
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "entry_kind": "acceptance",
        "sequence": 1,
        "proposal_id": PROPOSAL_ID,
        "acceptance_sha256": record["acceptance_sha256"],
        "package_version": M3E_PACKAGE_VERSION,
    })
    (ROOT / ACCEPTANCE_REGISTRY_PATH).write_bytes(
        render_ledger_bytes(chained_line_bytes(bodies))
    )
    done.append("registry")

print(json.dumps({"resealed": done, "acceptance_sha256": record["acceptance_sha256"]}))
"""


def reseal(
    root: Path,
    steps: tuple[str, ...] = ("pins", "binding"),
    governance: bool = True,
) -> dict[str, Any]:
    """Recompute every seal the attacker controls. Returns what was resealed."""
    script = RESEAL_SRC % {"pid": PROPOSAL_ID, "steps": json.dumps(list(steps))}
    rc, out = run([PY, "-c", script], root)
    result: dict[str, Any] = {"acceptance_reseal_exit": rc}
    if rc == 0:
        try:
            result.update(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            result["acceptance_reseal_raw"] = out[-400:]
    else:
        result["acceptance_reseal_error"] = out[-600:]
    if governance:
        result.update(reseal_governance(root))
    return result


CATALOG_SRC = r"""
import hashlib, json, sys
from pathlib import Path

ROOT = Path(".").resolve()
CAT = ROOT / "research/m3f/freeze_catalog.json"
cat = json.loads(CAT.read_text())
touched = []
for art in cat["artifacts"]:
    p = ROOT / art["path"]
    if not p.is_file():
        continue
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if digest != art.get("sha256"):
        art["sha256"] = digest
        art["byte_count"] = p.stat().st_size
        touched.append(art["path"])
if touched:
    CAT.write_bytes(
        json.dumps(cat, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    )
print(json.dumps({"catalog_pins_refreshed": sorted(touched)}))
"""


def refresh_catalog_pins(root: Path) -> dict[str, Any]:
    """Rewrite the M3F freeze-catalog pins to whatever is on disk now.

    This is an ATTACK step, not a reseal, and it is opt-in for exactly that
    reason. The catalog's pins for the growable paths are the historical baseline
    that ``m3f.growable`` proves the live chain still extends; refreshing them
    would erase the very anchor the append-only proof rests on. Measured: doing so
    is refused by both shadow readers (see probe GOV-01).
    """
    out: dict[str, Any] = {}
    rc, txt = run([PY, "-c", CATALOG_SRC], root)
    out["catalog_refresh_exit"] = rc
    if rc == 0:
        try:
            out.update(json.loads(txt.strip().splitlines()[-1]))
        except Exception:
            out["catalog_refresh_raw"] = txt[-300:]
    else:
        out["catalog_refresh_error"] = txt[-400:]
    return out


def reseal_governance(root: Path) -> dict[str, Any]:
    """Rebuild the Fable 5 governed surface, which IS the attacker's to refresh.

    Two governance surfaces are deliberately NOT rebuilt here:

    * the M3F *registration* artifacts — their builder reads blobs from the
      source-freeze commit ``b7d24e82``, which predates the growable cohort
      update, so it cannot run at this state at all;
    * the M3F freeze-catalog pins — they are the append-only baseline, not a
      seal (see :func:`refresh_catalog_pins`).

    Everything the attacker CAN legitimately regenerate is regenerated, so no
    probe is ever scored "caught" merely because a derived digest went stale.
    """
    out: dict[str, Any] = {}
    rc0, txt0 = run([PY, "-c", CAPSULE_SRC], root)
    out["capsule_reseal_exit"] = rc0
    if rc0 != 0:
        out["capsule_reseal_error"] = txt0[-300:]
    for cmd in (["build", "--write"], ["freeze-build", "--write"]):
        rc2, txt2 = run(
            [PY, "-m", "eth_research.v2.fable5", *cmd, "--repo-root", "."], root, src_path=True
        )
        out[f"fable5_{cmd[0]}_exit"] = rc2
        if rc2 != 0:
            out[f"fable5_{cmd[0]}_error"] = txt2[-300:]
    return out


CAPSULE_SRC = r"""
import sys
from pathlib import Path
sys.path.insert(0, "src")
from eth_research.m3f.bundle import (
    CAPSULE_MANIFEST_RELPATH, CAPSULE_NOTICE_RELPATH,
    build_manifest, render_capsule_notice, render_manifest_bytes,
)
from eth_research.m3f.register import write_drill_record

ROOT = Path(".").resolve()
(ROOT / CAPSULE_MANIFEST_RELPATH).write_bytes(render_manifest_bytes(build_manifest(ROOT)))
(ROOT / CAPSULE_NOTICE_RELPATH).write_bytes(render_capsule_notice())
write_drill_record(ROOT)
print("capsule manifest, notice and drill rebuilt")
"""


def _numstat(root: Path, base: str, head: str) -> tuple[int, int, int]:
    """Files/lines the committed part of the mutation actually moved."""
    out = (
        subprocess.run(
            ["git", "diff", "--numstat", base, head],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    files = added = deleted = 0
    for line in out:
        parts = line.split("\t")
        files += 1
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            deleted += int(parts[1])
    return files, added, deleted


def commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", message], cwd=root, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# probe definition + execution
# ---------------------------------------------------------------------------


@dataclass
class Probe:
    probe_id: str
    family: str
    mutation: str
    invariant: str
    expected_code: str
    apply: Callable[[Path], dict[str, Any]]
    #: (relpath, exact source text to delete) proving the named guard is the catcher.
    guard_deletion: tuple[str, str] | None = None
    #: A control is expected to PASS everywhere; an attack is expected to FAIL.
    expect: str = "refused"
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    #: Commit the mutation before resealing and again afterwards. Required for any
    #: probe touching research/m3d or research/m3e: the file-set policy refuses a
    #: dirty tree outright, so an uncommitted mutation dies at that precheck and
    #: never reaches the invariant under test. Committing is also what a real
    #: attacker with repository write access would do.
    commit_chain: bool = True


def first_failure(text: str) -> str:
    """The most informative line: prefer an explicit failure over a traceback frame.

    The stdlib verifier prints a "FAIL: N checks, M failures" summary and then the
    detail lines as ``- <check>: <reason>``. The summary carries no information, so
    detail lines win; a JSON payload from the m3f reader is unpacked to its
    ``failures`` list for the same reason.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    details = [ln for ln in lines if ln.startswith("- ")]
    if details:
        return " | ".join(d[2:] for d in details)[:400]
    for line in lines:
        if line.startswith("{") and '"failures"' in line:
            try:
                failures = json.loads(line).get("failures") or []
            except Exception:
                break
            if failures:
                return " | ".join(str(f) for f in failures)[:400]
    for line in reversed(lines):
        low = line.lower()
        if any(
            tok in low
            for tok in ("error:", "fail", "hard stop", "refus", "does not", "is not", "!=")
        ) and not low.startswith('file "'):
            return line[:400]
    return lines[-1][:400] if lines else ""


def run_readers(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for label, argv, needs_src in READERS:
        rc, txt = run(argv, root, src_path=needs_src)
        out[label] = {
            "exit": rc,
            "verdict": "PASS" if rc == 0 else "REFUSED",
            "message": "" if rc == 0 else first_failure(txt),
        }
    return out


def execute(probe: Probe, keep: bool = False) -> dict[str, Any]:
    root = clone(f"p_{probe.probe_id.replace('-', '_').lower()}")
    row: dict[str, Any] = {
        "probe_id": probe.probe_id,
        "family": probe.family,
        "mutation": probe.mutation,
        "intended_invariant": probe.invariant,
        "expected_code": probe.expected_code,
        "expectation": probe.expect,
        "notes": probe.notes,
    }
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    try:
        applied = probe.apply(root)
        if probe.commit_chain and probe.expect != "accepted":
            delta = byte_delta(root)
            if delta["files_changed"]:
                applied["mutation_commit"] = commit_all(root, f"probe {probe.probe_id}: mutation")
            applied.update(reseal(root, probe.extra.get("reseal_steps", ("pins", "binding"))))
            if byte_delta(root)["files_changed"]:
                applied["reseal_commit"] = commit_all(root, f"probe {probe.probe_id}: reseal")
    except Exception as exc:
        row["setup_error"] = f"{type(exc).__name__}: {exc}"
        row["mutation_confirmed"] = False
        return row
    row.update(applied)
    row["changed_bytes"] = byte_delta(root)
    head_now = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    if head_now != base:
        row["changed_bytes"] = {
            **row["changed_bytes"],
            **dict(
                zip(
                    ("committed_files", "committed_added", "committed_deleted"),
                    _numstat(root, base, head_now),
                    strict=True,
                )
            ),
        }
    row["mutation_confirmed"] = bool(
        row["changed_bytes"]["files_changed"] or head_now != base or applied.get("committed")
    )
    row["readers"] = run_readers(root)

    refused = [k for k, v in row["readers"].items() if v["exit"] != 0]
    row["refused_by"] = refused

    # An attacker who cannot even MINT the seal has been stopped by the policy at
    # build time, which is a stronger result than being caught at verify time —
    # not a miss. Score the reseal refusal alongside the four readers.
    seal_refusal = str(row.get("acceptance_reseal_error", ""))
    row["seal_could_not_be_minted"] = bool(seal_refusal)
    needle = (probe.expected_code or "").lower()
    haystacks = [v["message"].lower() for v in row["readers"].values()]
    if seal_refusal:
        haystacks.append(seal_refusal.lower())
    row["reached_intended_guard"] = bool(needle) and any(needle in h for h in haystacks)

    if probe.expect == "accepted":
        row["outcome"] = "CONTROL_PASSED" if not refused else "CONTROL_FAILED"
    elif not refused:
        row["outcome"] = "ACCEPTED_BY_ALL_READERS"
    elif not row["reached_intended_guard"]:
        row["outcome"] = "REFUSED_BY_ANOTHER_GUARD"
    else:
        row["outcome"] = "CAUGHT"

    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return row
