"""Guard-deletion mutants: prove each guard is what actually catches its probe.

For each (probe, guard, owning reader) triple: reproduce the probe's mutation in
a fresh clone, delete exactly that guard from the clone's source, and re-run the
readers. The owning reader MUST stop refusing. A guard whose deletion changes
nothing was not the catcher, and the probe's "caught" verdict would be resting on
some other check.

The deletions target the guards THIS milestone added — the ones whose
load-bearingness is actually in question. Long-standing guards (the hash chain,
the sealed ledgers) already carry their own regression tests.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_lib import (
    SCRATCH,
    byte_delta,
    clone,
    commit_all,
    require_clean_repo,
    reseal,
    reseal_governance,
    run_readers,
)
from probe_matrix import PROBES

OUT = SCRATCH / "guard_deletions.json"

ACC_PY = "src/eth_research/m3e/acceptance.py"
GROW_PY = "src/eth_research/m3f/growable.py"
STDLIB = "tools/m3f_independent_verify.py"

A08_BLOCK = """        try:
            verify_record_binding(root, binding, proposal_id=entry.proposal_id)
        except ProposalFilePolicyError as exc:
            raise AcceptanceError(
                f"acceptance {entry.proposal_id}: file-set binding does not re-derive: {exc}"
            ) from exc
"""

A09_BLOCK = """    if (root / ".git").exists():
        genealogy = verify_commit_genealogy(root)
        record("A09_commit_genealogy", f"checks={len(genealogy)}")
    else:
        record("A09_commit_genealogy", "no git repository: genealogy NOT verified")
"""

BIND_BLOCK = """        for field, bound in (
            ("expected_parent_commit", "proposal_parent_commit"),
            ("proposal_head_commit", "proposal_commit"),
        ):
            want = require_str(f"{entry.proposal_id}.{field}", entry.record.get(field))
            got = require_str(f"{entry.proposal_id}.binding.{bound}", binding.get(bound))
            if got != want:
                raise AcceptanceError(
                    f"acceptance {entry.proposal_id}: file-set binding certifies "
                    f"{bound}={got[:12]}\u2026 but the record names {field}={want[:12]}\u2026"
                )
"""

# (deletion id, probe id, relpath, exact text to remove, replacement, reader that owns it)
DELETIONS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("D-BIND", "GIT-01", ACC_PY, BIND_BLOCK, "", "production"),
    ("D-A08", "FILE-04", ACC_PY, A08_BLOCK, "", "production"),
    ("D-A08b", "FILE-01", ACC_PY, A08_BLOCK, "", "production"),
    (
        "D-A09",
        "GIT-06",
        ACC_PY,
        A09_BLOCK,
        '    record("A09_commit_genealogy", "DELETED")\n',
        "production",
    ),
    (
        "D-M3F-FILESET",
        "FILE-04",
        GROW_PY,
        "            verify_record_file_set(root, record, proposal_id=proposal_id)\n",
        "            pass\n",
        "m3f",
    ),
    (
        "D-M3F-PROV",
        "PROV-01",
        GROW_PY,
        "            verify_record_provenance(root, record, completion, proposal_id=proposal_id)\n",
        "            pass\n",
        "m3f",
    ),
    (
        "D-M3F-SPAN",
        "DATA-01b",
        GROW_PY,
        "        if span != appended:\n",
        "        if False:\n",
        "m3f",
    ),
    (
        "D-M3F-FLAGKEYS",
        "SAFE-03",
        GROW_PY,
        "        if frozenset(str(k) for k in flags) != ACCEPTANCE_GOVERNANCE_FLAGS:\n",
        "        if False:\n",
        "m3f",
    ),
    (
        "D-M3F-ROOT",
        "ROOT-01",
        GROW_PY,
        "        verify_genesis_root(root, genesis)\n",
        "        pass\n",
        "m3f",
    ),
    (
        "D-STD-FILESET",
        "FILE-04",
        STDLIB,
        "            _check_file_set_binding(root, record, proposal_id)\n",
        "",
        "stdlib",
    ),
    (
        "D-STD-PROV",
        "PROV-01",
        STDLIB,
        "            _check_record_provenance(root, record, completion, proposal_id)\n",
        "",
        "stdlib",
    ),
    (
        "D-STD-ROOT",
        "ROOT-01",
        STDLIB,
        "        _check_genesis_root(root, genesis)\n",
        "        pass\n",
        "stdlib",
    ),
)

BY_ID = {p.probe_id: p for p in PROBES}


def apply_probe(root: Path, probe_id: str) -> dict:
    probe = BY_ID[probe_id]
    applied = probe.apply(root)
    if probe.commit_chain:
        if byte_delta(root)["files_changed"]:
            commit_all(root, f"guard-deletion base: {probe_id} mutation")
        applied.update(reseal(root, probe.extra.get("reseal_steps", ("pins", "binding"))))
        if byte_delta(root)["files_changed"]:
            commit_all(root, f"guard-deletion base: {probe_id} reseal")
    return applied


def main() -> int:
    require_clean_repo()
    rows = []
    for did, pid, relpath, old, new, owner in DELETIONS:
        t0 = time.monotonic()
        root = clone(f"gd_{did.lower().replace('-', '_')}")
        row = {"deletion_id": did, "probe_id": pid, "file": relpath, "owning_reader": owner}
        try:
            apply_probe(root, pid)
            path = root / relpath
            text = path.read_text()
            if old not in text:
                row["error"] = f"deletion target absent: {old[:70]!r}"
                rows.append(row)
                print(f"{did:15} TARGET ABSENT in {relpath}")
                continue
            path.write_text(text.replace(old, new, 1))
            row["deleted_lines"] = old.count("\n")
            # The drill record hashes the source, so a source edit makes it stale.
            # Rebuild it, or the reader "catches" the deletion via capsule drift
            # instead of via the invariant, which proves nothing.
            row["capsule_rebuild"] = reseal_governance(root)
            row["readers"] = run_readers(root)
            after = row["readers"][owner]["exit"]
            row["owner_exit_after_deletion"] = after
            row["guard_is_load_bearing"] = after == 0
            # When the owner still refuses, name the check that caught instead —
            # "some other guard also fires" is only useful if you say which one.
            row["caught_instead_by"] = "" if after == 0 else row["readers"][owner]["message"][:280]
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["seconds"] = round(time.monotonic() - t0, 1)
        rows.append(row)
        shutil.rmtree(root, ignore_errors=True)
        verdict = (
            "LOAD-BEARING"
            if row.get("guard_is_load_bearing")
            else ("ERROR" if row.get("error") else "NOT the catcher")
        )
        print(f"{did:15} probe={pid:9} owner={owner:12} -> {verdict} ({row['seconds']}s)")
        OUT.write_text(json.dumps({"deletions": rows}, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
