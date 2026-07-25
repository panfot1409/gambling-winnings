"""The acceptance-layer probe truth table.

Five mandatory controls plus the coordinated-attack set. Every attack gets the
maximal attacker: the mutation is COMMITTED (so the file-set policy's clean-tree
precheck cannot shadow the invariant under test, and because an attacker with
repository write access would commit), then every seal the attacker can reach is
regenerated with the project's own primitives, then the reseal is committed too.
A refusal is therefore a semantic refusal and never a forgotten digest.

The original 41-probe matrix from the earlier Auditor B pass was never persisted
as machine-readable evidence, so nothing here cites it. Every row below is
re-measured now, against the current head.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from probe_lib import (
    ACC,
    AUTHORITY_SRC,
    BUNDLE_DIR,
    COMP,
    PROPOSAL_DIR,
    PY,
    REGISTRY,
    Probe,
    read_json,
    refresh_catalog_pins,
    run,
)

FULL = ("pins", "binding", "self_hashes", "registry")
PINS = ("pins", "self_hashes", "registry")
BIND = ("binding", "self_hashes", "registry")
SEAL: tuple[str, ...] = ("self_hashes", "registry")
#: leave the chain exactly as the attack left it
NONE: tuple[str, ...] = ()


def steps(value: tuple[str, ...]) -> dict[str, Any]:
    return {"reseal_steps": value}


# ---------------------------------------------------------------------------
# small editing primitives
# ---------------------------------------------------------------------------


def edit_json(root: Path, relpath: str, fn: Any) -> None:
    path = root / relpath
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def edit_text(root: Path, relpath: str, old: str, new: str, count: int = 1) -> None:
    path = root / relpath
    text = path.read_text()
    if old not in text:
        raise AssertionError(f"mutation target absent in {relpath}: {old[:90]!r}")
    path.write_text(text.replace(old, new, count))


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# CONTROLS — each must be ACCEPTED by all four readers
# ---------------------------------------------------------------------------


def c_untouched(root: Path) -> dict[str, Any]:
    return {"coordinated": False}


def c_identity_reseal(root: Path) -> dict[str, Any]:
    from probe_lib import reseal

    return {"coordinated": False, **reseal(root, FULL)}


def c_growth_fixture(root: Path) -> dict[str, Any]:
    rc, txt = run(
        [
            PY,
            "-m",
            "pytest",
            "tests/test_m3f_growable.py",
            "-q",
            "--no-header",
            "-p",
            "no:randomly",
        ],
        root,
        src_path=True,
        timeout=1800,
    )
    return {"coordinated": False, "fixture_suite_exit": rc, "fixture_tail": txt[-200:]}


def c_lawful_proposal(root: Path) -> dict[str, Any]:
    rc, txt = run(
        [
            PY,
            "-c",
            "import sys;sys.path.insert(0,'src');"
            "from eth_research.m3e.verify_m3e_program import verify_landed_update as v;"
            f"print(len(v('.', '{PROPOSAL_DIR}')))",
        ],
        root,
    )
    return {"coordinated": False, "landed_update_exit": rc, "landed_update_out": txt[-200:]}


def c_lawful_accepted_state(root: Path) -> dict[str, Any]:
    rc, txt = run(
        [
            PY,
            "-c",
            "import sys;sys.path.insert(0,'src');"
            "from eth_research.m3f.growable import read_acceptance_state as r;"
            "v=r('.');print(v.count, v.row_count)",
        ],
        root,
    )
    return {"coordinated": False, "accepted_state_exit": rc, "accepted_state_out": txt[-200:]}


# ---------------------------------------------------------------------------
# ROOT — the root of authority
# ---------------------------------------------------------------------------


def a_root_repoint_tree(root: Path) -> dict[str, Any]:
    edit_text(
        root,
        AUTHORITY_SRC,
        'TRUSTED_BASELINE_TREE = "35ed0d5b157047a63e04d91f8e1a4bfc64c9e127"',
        'TRUSTED_BASELINE_TREE = "ef26510e41ac1f3727abce2e1f9bd5fe2e69edfe"',
    )
    return {"coordinated": True}


def a_root_maximal_reroot(root: Path) -> dict[str, Any]:
    """The maximal re-root: rewrite BOTH authority tables on disk, the registry's
    genesis root, and every downstream seal — the attack the earlier audit
    recorded as accepted by all three readers."""
    for relpath in (
        "docs/M3C_M3E_STACK_FREEZE_TABLE.json",
        "research/v2ab/stack_freeze_table.json",
    ):
        edit_json(root, relpath, lambda d: d.__setitem__("__reroot_marker__", "attacker"))
    lines = (root / REGISTRY).read_text().splitlines()
    genesis = json.loads(lines[0])
    genesis["genesis_root"] = hashlib.sha256(b"attacker-chosen-root").hexdigest()
    lines[0] = json.dumps(genesis, separators=(",", ":"), sort_keys=True)
    (root / REGISTRY).write_text("\n".join(lines) + "\n")
    return {"coordinated": True, "rewrote_both_authority_tables": True}


def a_root_table_digest(root: Path) -> dict[str, Any]:
    """Rewrite an authority table AND repoint its pinned digest in source."""
    import re as _re

    path = root / "docs/M3C_M3E_STACK_FREEZE_TABLE.json"
    data = json.loads(path.read_text())
    data["__attacker__"] = 1
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    new = hashlib.sha256(path.read_bytes()).hexdigest()
    src = (root / AUTHORITY_SRC).read_text()
    m = _re.search(r'"docs/M3C_M3E_STACK_FREEZE_TABLE\.json":\s*\(?\s*"([0-9a-f]{64})"', src)
    if not m:
        raise AssertionError("could not find the freeze-table pin in the authority source")
    edit_text(root, AUTHORITY_SRC, m.group(1), new)
    return {"coordinated": True, "old_pin": m.group(1), "new_pin": new}


def a_root_baseline_commit(root: Path) -> dict[str, Any]:
    edit_text(
        root,
        AUTHORITY_SRC,
        'TRUSTED_BASELINE_COMMIT = "ba2dcc1d63f29a009d3660be2d960388a9615da0"',
        'TRUSTED_BASELINE_COMMIT = "779df6bb6c7ab4ac312e9d8fe7028392581db237"',
    )
    return {"coordinated": True}


# ---------------------------------------------------------------------------
# GIT — identity and genealogy
# ---------------------------------------------------------------------------


def _repoint_head(root: Path, value: str) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d.__setitem__("proposal_head_commit", value))
    return {"coordinated": True, "new_head_value": value}


def a_git_unrelated_commit(root: Path) -> dict[str, Any]:
    return _repoint_head(root, git(root, "rev-parse", "HEAD~1"))


def a_git_uppercase(root: Path) -> dict[str, Any]:
    return _repoint_head(root, "779DF6BB6C7AB4AC312E9D8FE7028392581DB237")


def a_git_abbreviated(root: Path) -> dict[str, Any]:
    return _repoint_head(root, "779df6bb")


def a_git_revision_syntax(root: Path) -> dict[str, Any]:
    return _repoint_head(root, "779df6bb6c7ab4ac312e9d8fe7028392581db237^0")


def a_git_shallow(root: Path) -> dict[str, Any]:
    (root / ".git/shallow").write_text(git(root, "rev-parse", "HEAD") + "\n")
    return {"coordinated": False, "shallow_marker_written": True}


def a_git_graft(root: Path) -> dict[str, Any]:
    info = root / ".git/info"
    info.mkdir(parents=True, exist_ok=True)
    head = "779df6bb6c7ab4ac312e9d8fe7028392581db237"
    (info / "grafts").write_text(f"{head}\n")
    return {"coordinated": False, "graft_written": head}


def a_git_replace(root: Path) -> dict[str, Any]:
    other = git(root, "rev-parse", "HEAD~1")
    subprocess.run(
        ["git", "update-ref", "refs/replace/779df6bb6c7ab4ac312e9d8fe7028392581db237", other],
        cwd=root,
        check=True,
    )
    return {"coordinated": False, "replaced_with": other}


def a_git_direction_swap(root: Path) -> dict[str, Any]:
    def swap(d: dict[str, Any]) -> None:
        d["expected_parent_commit"] = "779df6bb6c7ab4ac312e9d8fe7028392581db237"
        d["proposal_head_commit"] = "ba2dcc1d63f29a009d3660be2d960388a9615da0"

    edit_json(root, ACC, swap)
    return {"coordinated": True}


# ---------------------------------------------------------------------------
# FILE — the closed proposal file set
# ---------------------------------------------------------------------------


def a_file_smuggle(root: Path) -> dict[str, Any]:
    """Smuggle an extra member into the m3d bundle and pin it.

    The m3d side is chosen deliberately: A04's closed-set check only globs the
    m3e proposal directory, so this is exactly where a pin-is-the-allowlist bug
    would still be exploitable.
    """
    smuggled = f"{BUNDLE_DIR}/attacker_payload.json"
    (root / smuggled).write_text('{"attacker": true}\n')
    digest = hashlib.sha256((root / smuggled).read_bytes()).hexdigest()
    edit_json(root, ACC, lambda d: d["new_accepted"]["created"].__setitem__(smuggled, digest))
    return {"coordinated": True, "smuggled_path": smuggled}


def a_file_omit(root: Path) -> dict[str, Any]:
    record = read_json(root, ACC)
    victim = sorted(p for p in record["new_accepted"]["created"] if p.startswith(BUNDLE_DIR))[0]
    edit_json(root, ACC, lambda d: d["new_accepted"]["created"].pop(victim))
    return {"coordinated": True, "omitted_path": victim}


def a_file_relabel_role(root: Path) -> dict[str, Any]:
    def swap(d: dict[str, Any]) -> None:
        b = d["file_set_binding"]
        b["raw_member_paths_sha256"], b["governance_member_paths_sha256"] = (
            b["governance_member_paths_sha256"],
            b["raw_member_paths_sha256"],
        )

    edit_json(root, ACC, swap)
    return {"coordinated": True}


def a_file_widen_count(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["file_set_binding"].__setitem__("allowed_member_count", 25))
    return {"coordinated": True}


def a_file_unknown_binding_field(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["file_set_binding"].__setitem__("attacker_escape_hatch", "ok"))
    return {"coordinated": True}


def a_file_smuggle_accepted_dir(root: Path) -> dict[str, Any]:
    path = f"{PROPOSAL_DIR}/attacker_note.json"
    (root / path).write_text('{"attacker": true}\n')
    return {"coordinated": True, "smuggled_path": path}


# ---------------------------------------------------------------------------
# CHAIN — the acceptance hash chain
# ---------------------------------------------------------------------------


def a_chain_drop_genesis(root: Path) -> dict[str, Any]:
    lines = (root / REGISTRY).read_text().splitlines()
    (root / REGISTRY).write_text("\n".join(lines[1:]) + "\n")
    return {"coordinated": False, "dropped": "genesis line"}


def a_chain_reorder(root: Path) -> dict[str, Any]:
    lines = (root / REGISTRY).read_text().splitlines()
    (root / REGISTRY).write_text("\n".join(reversed(lines)) + "\n")
    return {"coordinated": False, "reordered": True}


def a_chain_duplicate(root: Path) -> dict[str, Any]:
    lines = (root / REGISTRY).read_text().splitlines()
    (root / REGISTRY).write_text("\n".join([*lines, lines[-1]]) + "\n")
    return {"coordinated": False, "duplicated_last_line": True}


def a_chain_second_acceptance(root: Path) -> dict[str, Any]:
    """Append a properly re-chained SECOND acceptance of the same proposal."""
    src = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from eth_research.m3e.acceptance import (
    ACCEPTANCE_REGISTRY_PATH, ACCEPTANCE_SCHEMA_VERSION, M3E_PACKAGE_VERSION,
    build_genesis_record,
)
from eth_research.m3d.chain import chained_line_bytes, render_ledger_bytes
ROOT = Path(".").resolve()
PID = "20260715-20260724-315846f9ec5196b4"
acc = json.loads((ROOT / "research/m3e/acceptances" / PID / "acceptance.json").read_text())
entry = {
    "schema_version": ACCEPTANCE_SCHEMA_VERSION, "entry_kind": "acceptance",
    "proposal_id": PID, "acceptance_sha256": acc["acceptance_sha256"],
    "package_version": M3E_PACKAGE_VERSION,
}
bodies = [build_genesis_record(ROOT), {**entry, "sequence": 1}, {**entry, "sequence": 2}]
(ROOT / ACCEPTANCE_REGISTRY_PATH).write_bytes(render_ledger_bytes(chained_line_bytes(bodies)))
print("appended a second, correctly chained acceptance")
"""
    rc, txt = run([PY, "-c", src], root)
    return {"coordinated": True, "append_exit": rc, "append_out": txt[-200:]}


def a_chain_reseed(root: Path) -> dict[str, Any]:
    lines = [json.loads(ln) for ln in (root / REGISTRY).read_text().splitlines()]
    lines[0]["previous_line_sha256"] = hashlib.sha256(b"attacker-seed").hexdigest()
    (root / REGISTRY).write_text(
        "\n".join(json.dumps(x, separators=(",", ":"), sort_keys=True) for x in lines) + "\n"
    )
    return {"coordinated": False, "reseeded_genesis_previous_line": True}


# ---------------------------------------------------------------------------
# DATA — the data the acceptance is about
# ---------------------------------------------------------------------------


def a_data_relabel_append(root: Path) -> dict[str, Any]:
    """Relabel the append accounting so it stays ARITHMETICALLY CONSISTENT.

    prior 3 -> 1 and new 12 -> 10, leaving appended at 9. Both the row arithmetic
    (prior + appended == new) and the day-span check still hold, so neither can
    shadow the invariant actually under test: whether the prior row count is
    MEASURED against the cohort or merely asserted.
    """

    def relabel(d: dict[str, Any]) -> None:
        d["append_only_proof"]["prior_row_count"] = 1
        d["previous_accepted"]["row_count"] = 1
        d["new_accepted"]["row_count"] = 10

    edit_json(root, ACC, relabel)
    return {"coordinated": True}


def a_data_relabel_append_loud(root: Path) -> dict[str, Any]:
    """The louder relabel the earlier audit recorded as accepted by all three
    readers: prior 3 -> 1 AND appended 9 -> 11, which the committed proposal
    manifest in the same tree contradicts."""

    def relabel(d: dict[str, Any]) -> None:
        d["append_only_proof"]["prior_row_count"] = 1
        d["previous_accepted"]["row_count"] = 1
        d["append_interval"]["row_count"] = 11

    edit_json(root, ACC, relabel)
    return {"coordinated": True}


def a_data_shrink_cohort(root: Path) -> dict[str, Any]:
    path = root / "research/m3d/prospective_segments.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    return {"coordinated": True, "removed_segment_lines": 1}


def a_data_change_prior_row(root: Path) -> dict[str, Any]:
    path = root / "research/m3d/prospective_manifest.json"
    data = json.loads(path.read_text())
    data["cohort_start"] = "2026-07-13T00:00:00Z"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return {"coordinated": True, "claimed_prior_rows_changed": 0}


def a_data_window_inconsistent(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["append_interval"].__setitem__("row_count", 40))
    return {"coordinated": True}


def a_data_runners_differ(root: Path) -> dict[str, Any]:
    def differ(d: dict[str, Any]) -> None:
        raw = d["runner_evidence"]["runner_b"]["raw_response_sha256"]
        raw[next(iter(raw))] = hashlib.sha256(b"runner-b-divergent").hexdigest()

    edit_json(root, ACC, differ)
    return {"coordinated": True}


def a_data_delete_evidence(root: Path) -> dict[str, Any]:
    record = read_json(root, ACC)
    victim = sorted(p for p in record["new_accepted"]["created"] if p.startswith(BUNDLE_DIR))[-1]
    (root / victim).unlink()
    return {"coordinated": True, "deleted_path": victim}


# ---------------------------------------------------------------------------
# STATE — the transitioned state
# ---------------------------------------------------------------------------


def a_state_empty_map(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["new_accepted"].__setitem__("state", {}))
    return {"coordinated": True}


def a_state_drop_one(root: Path) -> dict[str, Any]:
    record = read_json(root, ACC)
    victim = sorted(record["new_accepted"]["state"])[0]
    edit_json(root, ACC, lambda d: d["new_accepted"]["state"].pop(victim))
    return {"coordinated": True, "dropped_state_path": victim}


# ---------------------------------------------------------------------------
# SAFE — the safety posture
# ---------------------------------------------------------------------------


def a_safe_unseal_ledger(root: Path) -> dict[str, Any]:
    path = root / "research/m3d/prospective_evaluations.jsonl"
    path.write_text('{"evaluated": true}\n')
    return {"coordinated": True, "unsealed": "research/m3d/prospective_evaluations.jsonl"}


def a_safe_flip_flag(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["governance_flags"].__setitem__("strategy_evaluated", True))
    return {"coordinated": True}


def a_safe_delete_flag(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d["governance_flags"].pop("money_moved"))
    return {"coordinated": True}


def a_safe_authorize_evaluation(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d.__setitem__("evaluation_authorized", True))
    return {"coordinated": True}


def a_safe_claim_mature(root: Path) -> dict[str, Any]:
    def mature(d: dict[str, Any]) -> None:
        d["maturity_state"] = "mature"
        d["new_accepted"]["row_count"] = 400

    edit_json(root, ACC, mature)
    return {"coordinated": True}


# ---------------------------------------------------------------------------
# PROV — provenance
# ---------------------------------------------------------------------------


def a_prov_manifest_mismatch(root: Path) -> dict[str, Any]:
    path = root / f"{PROPOSAL_DIR}/proposal_manifest.json"
    data = json.loads(path.read_text())
    data["__attacker__"] = True
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return {"coordinated": True}


def a_prov_time_before_window(root: Path) -> dict[str, Any]:
    edit_json(root, ACC, lambda d: d.__setitem__("acceptance_time", "2026-07-16T00:00:00Z"))
    return {"coordinated": True}


def a_prov_publication_not_ancestor(root: Path) -> dict[str, Any]:
    fake = hashlib.sha1(b"not-a-real-commit").hexdigest()
    edit_json(root, COMP, lambda d: d.__setitem__("publication_commit", fake))
    return {"coordinated": True, "fake_publication_commit": fake}


def a_prov_uncovered_proposal(root: Path) -> dict[str, Any]:
    other = root / "research/m3e/proposals/20260101-20260102-deadbeefdeadbeef"
    other.mkdir(parents=True)
    (other / "proposal_manifest.json").write_text('{"kind": "attacker"}\n')
    return {"coordinated": True, "extra_proposal": other.name}


# ---------------------------------------------------------------------------
# GOV — the governance baseline
# ---------------------------------------------------------------------------


def a_gov_refresh_catalog(root: Path) -> dict[str, Any]:
    """Rewrite the frozen catalog's pins to today's bytes, erasing the
    append-only baseline the growth proof is anchored to."""
    return {"coordinated": True, **refresh_catalog_pins(root)}


def a_gov_accepted_base_drift(root: Path) -> dict[str, Any]:
    edit_json(
        root, "research/m3e/accepted_base.json", lambda d: d.__setitem__("__attacker__", True)
    )
    return {"coordinated": True}


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

PROBES: tuple[Probe, ...] = (
    # --- controls ----------------------------------------------------------
    Probe(
        "CTRL-01",
        "control",
        "no mutation at all",
        "n/a (valid state)",
        "",
        c_untouched,
        expect="accepted",
        commit_chain=False,
        notes="the baseline every attack row is measured against",
    ),
    Probe(
        "CTRL-02",
        "control",
        "lawful identity reseal: recompute every pin, the "
        "file-set binding, both self-hashes and the registry chain",
        "n/a (valid state)",
        "",
        c_identity_reseal,
        expect="accepted",
        commit_chain=False,
        notes="must be a byte-for-byte no-op, else the reseal machinery itself "
        "is what the attack rows would be measuring",
    ),
    Probe(
        "CTRL-03",
        "control",
        "lawful accepted-growth fixture (M3F growable suite)",
        "n/a (valid state)",
        "",
        c_growth_fixture,
        expect="accepted",
        commit_chain=False,
    ),
    Probe(
        "CTRL-04",
        "control",
        "lawful current proposal re-proves end to end",
        "n/a (valid state)",
        "",
        c_lawful_proposal,
        expect="accepted",
        commit_chain=False,
    ),
    Probe(
        "CTRL-05",
        "control",
        "lawful current accepted state loads and reconciles",
        "n/a (valid state)",
        "",
        c_lawful_accepted_state,
        expect="accepted",
        commit_chain=False,
    ),
    # --- root of authority --------------------------------------------------
    Probe(
        "ROOT-01",
        "root",
        "repoint TRUSTED_BASELINE_TREE at the proposal's own tree",
        "ROOT-01",
        "trusted baseline tree",
        a_root_repoint_tree,
        extra=steps(FULL),
    ),
    Probe(
        "ROOT-02",
        "root",
        "maximal re-root: rewrite BOTH authority tables, the "
        "registry genesis root, and every downstream seal",
        "ROOT-03",
        "trusted history says",
        a_root_maximal_reroot,
        extra=steps(FULL),
    ),
    Probe(
        "ROOT-03",
        "root",
        "rewrite an authority table and repoint its pinned digest in committed source",
        "ROOT-02",
        "authority table",
        a_root_table_digest,
        extra=steps(FULL),
    ),
    Probe(
        "ROOT-04",
        "root",
        "swap TRUSTED_BASELINE_COMMIT for the proposal head",
        "ROOT-01",
        "baseline",
        a_root_baseline_commit,
        extra=steps(FULL),
    ),
    # --- git identity and genealogy ----------------------------------------
    Probe(
        "GIT-01",
        "git",
        "repoint proposal_head_commit at an unrelated real commit",
        "BIND-01",
        "certifies",
        a_git_unrelated_commit,
        extra=steps(PINS),
    ),
    Probe(
        "GIT-02",
        "git",
        "uppercase the pinned commit id",
        "GIT-01",
        "not a 40-hex commit id",
        a_git_uppercase,
        extra=steps(PINS),
        notes="GEN-08 states the same rule inside the genealogy checks, but the "
        "record loader's format check runs first and is what fires here; "
        "GEN-08 itself is probed directly in tests/test_m3e_commit_genealogy.py",
    ),
    Probe(
        "GIT-03",
        "git",
        "abbreviate the pinned commit id to 8 hex",
        "GIT-01",
        "not a 40-hex commit id",
        a_git_abbreviated,
        extra=steps(PINS),
    ),
    Probe(
        "GIT-04",
        "git",
        "append revision syntax (^0) to the pinned commit id",
        "GIT-01",
        "not a 40-hex commit id",
        a_git_revision_syntax,
        extra=steps(PINS),
    ),
    Probe(
        "GIT-05",
        "git",
        "truncate history with a .git/shallow marker",
        "GIT-05",
        "shallow clone",
        a_git_shallow,
        commit_chain=False,
    ),
    Probe(
        "GIT-06",
        "git",
        "fabricate parentage with .git/info/grafts",
        "GIT-05",
        "graft file fabricates parentage",
        a_git_graft,
        commit_chain=False,
    ),
    Probe(
        "GIT-07",
        "git",
        "substitute the pinned commit via refs/replace",
        "GIT-05",
        "GEN-04",
        a_git_replace,
        commit_chain=False,
    ),
    Probe(
        "GIT-08",
        "git",
        "swap parent and child so the proposal precedes its baseline",
        "GIT-04/PROV-01",
        "does not carry",
        a_git_direction_swap,
        extra=steps(PINS),
    ),
    # --- the closed file set ------------------------------------------------
    Probe(
        "FILE-01",
        "file",
        "commit a smuggled member into the m3d bundle and pin it",
        "FILE-01/FILE-03",
        "names paths out",
        a_file_smuggle,
        extra=steps(FULL),
        notes="the policy refuses to MINT a binding for an illegal member set, so "
        "the attacker cannot even construct the seal; all four readers then "
        "refuse the unresealed record",
    ),
    Probe(
        "FILE-02",
        "file",
        "omit a legal member from the pinned set",
        "FILE-01/FILE-03",
        "undeclared members",
        a_file_omit,
        extra=steps(BIND),
    ),
    Probe(
        "FILE-03",
        "file",
        "swap the raw and governance role digests in the binding",
        "FILE-02",
        "file-set binding",
        a_file_relabel_role,
        extra=steps(SEAL),
    ),
    Probe(
        "FILE-04",
        "file",
        "widen allowed_member_count from 19 to 25",
        "FILE-03",
        "file-set binding",
        a_file_widen_count,
        extra=steps(SEAL),
    ),
    Probe(
        "FILE-05",
        "file",
        "add an unknown field to the file-set binding",
        "FILE-03",
        "file-set binding",
        a_file_unknown_binding_field,
        extra=steps(SEAL),
    ),
    Probe(
        "FILE-06",
        "file",
        "smuggle an unpinned file into the accepted proposal directory",
        "FILE-04",
        "closed set",
        a_file_smuggle_accepted_dir,
        extra=steps(FULL),
    ),
    # --- the chain ----------------------------------------------------------
    Probe(
        "CHAIN-01",
        "chain",
        "delete the registry genesis line",
        "CHAIN-01",
        "hash chain",
        a_chain_drop_genesis,
        extra=steps(NONE),
    ),
    Probe(
        "CHAIN-02",
        "chain",
        "reverse the registry line order",
        "CHAIN-01/CHAIN-03",
        "hash chain",
        a_chain_reorder,
        extra=steps(NONE),
    ),
    Probe(
        "CHAIN-03",
        "chain",
        "duplicate the final registry line",
        "CHAIN-03",
        "hash chain",
        a_chain_duplicate,
        extra=steps(NONE),
    ),
    Probe(
        "CHAIN-04",
        "chain",
        "append a correctly re-chained SECOND acceptance of the same proposal",
        "CHAIN-03",
        "twice",
        a_chain_second_acceptance,
        extra=steps(NONE),
    ),
    Probe(
        "CHAIN-05",
        "chain",
        "re-chain the registry from an attacker-chosen seed",
        "CHAIN-01",
        "hash chain",
        a_chain_reseed,
        extra=steps(NONE),
    ),
    # --- the data -----------------------------------------------------------
    Probe(
        "DATA-01",
        "data",
        "relabel prior 3->1 and new 12->10, keeping both the row "
        "arithmetic and the day span consistent",
        "DATA-03",
        "row",
        a_data_relabel_append,
        extra=steps(FULL),
    ),
    Probe(
        "DATA-01b",
        "data",
        "the louder relabel: prior 3->1 AND appended 9->11",
        "DATA-02",
        "span",
        a_data_relabel_append_loud,
        extra=steps(FULL),
        notes="recorded by the earlier audit as accepted by all three readers",
    ),
    Probe(
        "DATA-02",
        "data",
        "delete a settled row from the cohort and reseal",
        "DATA-03",
        "rebuilt manifest",
        a_data_shrink_cohort,
        extra=steps(FULL),
    ),
    Probe(
        "DATA-03",
        "data",
        "change a prior row while claiming prior_rows_changed == 0",
        "DATA-03",
        "rebuilt manifest",
        a_data_change_prior_row,
        extra=steps(FULL),
    ),
    Probe(
        "DATA-04",
        "data",
        "claim 40 rows in a 9-day append window",
        "DATA-01",
        "row arithmetic",
        a_data_window_inconsistent,
        extra=steps(FULL),
    ),
    Probe(
        "DATA-05",
        "data",
        "attest two runners with divergent raw payload digests",
        "DATA-04",
        "byte-identical",
        a_data_runners_differ,
        extra=steps(BIND),
    ),
    Probe(
        "DATA-06",
        "data",
        "delete pinned created evidence and drop its pin",
        "DATA-05/STATE-02",
        "created evidence",
        a_data_delete_evidence,
        extra=steps(FULL),
    ),
    # --- transitioned state -------------------------------------------------
    Probe(
        "STATE-01",
        "state",
        "empty the new_accepted.state map so it asserts nothing",
        "STATE-01",
        "state",
        a_state_empty_map,
        extra=steps(BIND),
    ),
    Probe(
        "STATE-02",
        "state",
        "drop one of the six transitioned state paths",
        "STATE-01",
        "state",
        a_state_drop_one,
        extra=steps(BIND),
    ),
    # --- safety -------------------------------------------------------------
    Probe(
        "SAFE-01",
        "safe",
        "write a line into a sealed evaluation ledger",
        "SAFE-01",
        "sealed ledger",
        a_safe_unseal_ledger,
        extra=steps(FULL),
    ),
    Probe(
        "SAFE-02",
        "safe",
        "flip governance flag strategy_evaluated to true",
        "SAFE-02",
        "flag",
        a_safe_flip_flag,
        extra=steps(BIND),
    ),
    Probe(
        "SAFE-03",
        "safe",
        "delete the money_moved governance flag key",
        "SAFE-02",
        "flag",
        a_safe_delete_flag,
        extra=steps(BIND),
    ),
    Probe(
        "SAFE-04",
        "safe",
        "set evaluation_authorized to true",
        "SAFE-03",
        "evaluation",
        a_safe_authorize_evaluation,
        extra=steps(BIND),
    ),
    Probe(
        "SAFE-05",
        "safe",
        "claim maturity_state=mature with row_count 400",
        "SAFE-03",
        "matur",
        a_safe_claim_mature,
        extra=steps(BIND),
    ),
    # --- provenance ---------------------------------------------------------
    Probe(
        "PROV-01",
        "prov",
        "rewrite the proposal manifest on disk and repin it",
        "PROV-01",
        "manifest",
        a_prov_manifest_mismatch,
        extra=steps(FULL),
    ),
    Probe(
        "PROV-02",
        "prov",
        "backdate acceptance_time inside the append window",
        "PROV-02",
        "before its own append window",
        a_prov_time_before_window,
        extra=steps(BIND),
    ),
    Probe(
        "PROV-03",
        "prov",
        "name a publication commit that does not exist",
        "PROV-03",
        "publication_commit",
        a_prov_publication_not_ancestor,
        extra=steps(SEAL),
    ),
    Probe(
        "PROV-04",
        "prov",
        "create a second production proposal no acceptance covers",
        "PROV-04",
        "without an acceptance record",
        a_prov_uncovered_proposal,
        extra=steps(FULL),
    ),
    # --- governance baseline -------------------------------------------------
    Probe(
        "GOV-01",
        "gov",
        "refresh the frozen catalog's pins to today's bytes, erasing the append-only baseline",
        "M3F-CATALOG (outside the acceptance invariant catalog)",
        "prefix",
        a_gov_refresh_catalog,
        extra=steps(NONE),
    ),
    Probe(
        "GOV-02",
        "gov",
        "edit research/m3e/accepted_base.json and repin it everywhere",
        "DATA-03",
        "accepted_base",
        a_gov_accepted_base_drift,
        extra=steps(FULL),
    ),
)
