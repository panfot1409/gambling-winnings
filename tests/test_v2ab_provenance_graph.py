"""Clean + tamper tests for the raw-to-result provenance graph.

Tamper tests mutate a *copy* of the committed evidence under ``tmp_path`` and point the
verifier at that copy, so no accepted artifact is touched. They demonstrate that a tampered
results document breaks a semantic edge in shallow mode, and that ``deep=True`` additionally
catches a *fully self-consistent* subgraph rewrite because the accepted external anchors
cannot be rewritten by the verifier.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from eth_research.v2.strict import (
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2ab import V2A_RESULTS_FINGERPRINT, V2B_RESULTS_FINGERPRINT
from eth_research.v2ab.provenance_graph import build_provenance_graph, verify_provenance_graph
from eth_research.v2b.governance import append_event, protocol_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]

_CORE_NODES = frozenset(
    {
        "btc_raw_genesis",
        "btc_raw_audit",
        "btc_canonical_dataset",
        "eth_research_train",
        "joint_partition",
        "protocol_identity",
        "v2b_results",
        "v2b_decision",
        "v2b_results_manifest",
        "registry_completed",
        "commercial_readiness",
        "v2a_accepted_null",
        "package_version",
        "research_family_catalog",
        "rejected_family_index",
        "multiplicity_state",
    }
)


def _copy_repo(tmp_path: Path) -> Path:
    """Copy every tree the provenance graph reads into a throwaway repo root.

    The candidate source freeze binds specific ``src/`` files and the hypothesis-review doc,
    so the copy must include ``src/`` and ``docs/`` alongside ``research/`` and the workflows.
    """
    root = tmp_path / "repo"
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO_ROOT / "research", root / "research", ignore=ignore)
    shutil.copytree(REPO_ROOT / "src", root / "src", ignore=ignore)
    shutil.copytree(REPO_ROOT / "docs", root / "docs")
    shutil.copytree(REPO_ROOT / ".github/workflows", root / ".github/workflows")
    return root


def _regenerate_registry(root: Path, results_fp: str) -> None:
    reg = root / "research/v2b/v2b_research_registry.jsonl"
    reg.unlink()
    pf = protocol_fingerprint(root)
    append_event(
        reg, "registered", "v2b_run_001", protocol_fingerprint=pf, timestamp="2026-07-20T00:00:00Z"
    )
    append_event(
        reg, "started", "v2b_run_001", protocol_fingerprint=pf, timestamp="2026-07-20T00:10:00Z"
    )
    append_event(
        reg,
        "completed",
        "v2b_run_001",
        protocol_fingerprint=pf,
        timestamp="2026-07-20T00:10:00Z",
        payload={"results_fingerprint": results_fp},
    )


# --------------------------------------------------------------------------- #
# clean                                                                         #
# --------------------------------------------------------------------------- #
def test_real_repo_shallow_and_deep_clean() -> None:
    assert verify_provenance_graph(REPO_ROOT) == []
    assert verify_provenance_graph(REPO_ROOT, deep=True) == []


def test_graph_spans_raw_to_result_with_every_edge_verified() -> None:
    g = build_provenance_graph(REPO_ROOT)
    assert g.ok
    node_ids = {n.node_id for n in g.nodes}
    assert node_ids >= _CORE_NODES
    assert all(e.verified for e in g.edges)
    # the spine: raw -> canonical -> partition -> protocol -> results -> registry.
    assert g.edge("btc_raw_genesis", "btc_canonical_dataset") is not None
    assert g.edge("btc_canonical_dataset", "joint_partition") is not None
    assert g.edge("joint_partition", "protocol_identity") is not None
    assert g.edge("protocol_identity", "v2b_results") is not None
    assert g.edge("v2b_results", "registry_completed") is not None


def test_copied_repo_verifies_clean(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    assert verify_provenance_graph(root) == []
    assert verify_provenance_graph(root, deep=True) == []


# --------------------------------------------------------------------------- #
# tamper                                                                        #
# --------------------------------------------------------------------------- #
def test_tampered_results_verdict_breaks_outgoing_edges(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    rp = root / "research/v2b/v2b_results.json"
    obj = json.loads(rp.read_bytes())
    obj["result"]["verdict"] = "V2B TAMPERED VERDICT"
    rp.write_bytes(json.dumps(obj).encode())
    g = build_provenance_graph(root)
    assert not g.ok
    manifest_edge = g.edge("v2b_results", "v2b_results_manifest")
    registry_edge = g.edge("v2b_results", "registry_completed")
    assert manifest_edge is not None
    assert not manifest_edge.verified
    assert registry_edge is not None
    assert not registry_edge.verified


def test_tampered_results_protocol_fp_breaks_incoming_edge(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    rp = root / "research/v2b/v2b_results.json"
    obj = json.loads(rp.read_bytes())
    obj["protocol_fingerprint"] = "00" * 32  # a wrong-but-valid 64-hex fingerprint
    rp.write_bytes(json.dumps(obj).encode())
    g = build_provenance_graph(root)
    assert not g.ok
    produced = g.edge("protocol_identity", "v2b_results")
    assert produced is not None
    assert not produced.verified


def test_tampered_partition_identity_breaks_reproduction(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    jp = root / "research/v2b/joint_partition_identity.json"
    obj = json.loads(jp.read_bytes())
    obj["combined_partition_fingerprint"] = "00" * 32
    jp.write_bytes(json.dumps(obj).encode())
    problems = verify_provenance_graph(root)
    assert any("joint-partition" in p for p in problems)


def test_tampered_v2a_null_breaks_binding_and_deep_anchor(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    v2a = root / "research/v2a/results.json"
    obj = json.loads(v2a.read_bytes())
    obj["package_version"] = "2.0.0.devX"  # shifts the V2A results fingerprint
    v2a.write_bytes(json.dumps(obj).encode())
    g = build_provenance_graph(root)
    assert not g.ok
    preserved = g.edge("v2a_accepted_null", "commercial_readiness")
    assert preserved is not None
    assert not preserved.verified
    deep = verify_provenance_graph(root, deep=True)
    assert any("V2A results" in p and V2A_RESULTS_FINGERPRINT in p for p in deep)


def test_deep_catches_consistent_results_subgraph_rewrite(tmp_path: Path) -> None:
    root = _copy_repo(tmp_path)
    new_verdict = "V2B COMPLETE - REWRITTEN SUBGRAPH; V2 NOT SELL-READY"

    # Rewrite the results, the manifest, AND the hash-chained registry consistently, so a
    # SHALLOW verification finds nothing wrong.
    rp = root / "research/v2b/v2b_results.json"
    obj = json.loads(rp.read_bytes())
    obj["result"]["verdict"] = new_verdict
    new_bytes = canonical_json_bytes(obj)
    rp.write_bytes(new_bytes)
    new_fp = canonical_sha256(strict_json_loads(new_bytes))

    man = root / "research/v2b/v2b_results_manifest.json"
    m = json.loads(man.read_bytes())
    m["results_fingerprint"] = new_fp
    m["results_sha256"] = sha256_bytes(new_bytes)
    m["verdict"] = new_verdict
    man.write_bytes(canonical_json_bytes(m))

    _regenerate_registry(root, new_fp)

    # The rewritten subgraph is internally consistent...
    assert build_provenance_graph(root).ok
    assert verify_provenance_graph(root) == []
    # ...but deep mode pins to the acceptance-time anchor the attacker cannot rewrite.
    assert new_fp != V2B_RESULTS_FINGERPRINT
    deep = verify_provenance_graph(root, deep=True)
    assert any("V2B results" in p and V2B_RESULTS_FINGERPRINT in p for p in deep)
