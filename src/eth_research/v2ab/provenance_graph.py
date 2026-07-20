"""Raw-to-result provenance graph for the V2B cross-asset program (read-only, offline).

This builds and verifies the full derivation DAG that carries the committed evidence from the
two raw BTC acquisitions all the way to the published decision, the commercial-readiness
posture, and the append-only registry's terminal event:

    BTC raw (genesis + audit) -> BTC canonical dataset -> aligned ETH/BTC partition
      -> V2B protocol identity -> V2B results -> decision -> results manifest
      -> registry ``completed`` -> commercial-readiness posture,

binding along the way the ETH dataset identity, the accepted V2A null, the research-family
catalog, the rejected-family index, the cumulative multiplicity state, the candidate source
freeze, and the package version.

Every edge is verified *semantically* -- the child identity is recomputed from the parent
bytes (re-derive the canonical BTC series from raw, re-align the partition, recompute the
protocol fingerprint over the committed component hashes, re-canonicalise the results to
their fingerprint, re-read the hash-chained registry) rather than by trusting a hash printed
by one possibly-forged document. In ``deep=True`` mode the reconstruction is additionally
pinned to the accepted external anchors frozen at acceptance time (the joint-partition
fingerprint ``6a37a95e...``, the V2B results fingerprint ``d0b668f4...``, and the V2A results
fingerprint ``6327de21...``), so an attacker who rewrites one whole subgraph -- even
self-consistently -- is still caught because those anchors cannot be rewritten here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import eth_research
from eth_research.v2.registry import read_events as v2_read_events
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_mapping,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2ab import (
    V2A_RESULTS_FINGERPRINT,
    V2B_PROTOCOL_FINGERPRINT,
    V2B_RESULTS_FINGERPRINT,
)
from eth_research.v2ab.acquisition_audit import ACCEPTED_BTC_DATASET_FINGERPRINT
from eth_research.v2b.acquisition import AUDIT_ATTEMPT_ID, GENESIS_ATTEMPT_ID
from eth_research.v2b.buyer_evidence import verify_buyer_evidence
from eth_research.v2b.candidate_source_freeze import (
    CANDIDATE_SOURCE_FREEZE_RELPATH,
    verify_candidate_source_freeze,
)
from eth_research.v2b.governance import (
    COMPLETED,
    V2B_PROTOCOL_RELPATH,
    V2B_REGISTRY_RELPATH,
    protocol_fingerprint,
    read_events,
    verify_protocol_identity,
    verify_registry_bound,
)
from eth_research.v2b.multiplicity import MULTIPLICITY_STATE_RELPATH, verify_multiplicity
from eth_research.v2b.partition import JOINT_PARTITION_IDENTITY_RELPATH, build_joint_partition
from eth_research.v2b.publication import MANIFEST_NAME, RESULTS_NAME, verify_publication
from eth_research.v2b.research_memory import MEMORY_STATE_RELPATH, verify_research_memory
from eth_research.v2b.results import summarize_committed
from eth_research.v2b.scenarios import EXECUTION_SCENARIOS_RELPATH, verify_scenario_declaration

#: The accepted external anchors, frozen at acceptance time (deep mode pins to these).
ACCEPTED_JOINT_PARTITION_FINGERPRINT: str = (
    "6a37a95e1f1faeb182834fce2b52d97b4e56f133a9a1fe9892dddf32087191e4"
)
ACCEPTED_ETH_DATASET_FINGERPRINT: str = (
    "sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033"
)
ACCEPTED_PACKAGE_VERSION: str = "2.0.0.dev1"

V2B_RESULTS_RELPATH: str = f"research/v2b/{RESULTS_NAME}"
V2B_MANIFEST_RELPATH: str = f"research/v2b/{MANIFEST_NAME}"
RESEARCH_FAMILY_CATALOG_RELPATH: str = "research/v2b/research_family_catalog.json"
REJECTED_FAMILY_INDEX_RELPATH: str = "research/v2b/rejected_family_index.json"
V2A_RESULTS_RELPATH: str = "research/v2a/results.json"
V2A_MANIFEST_RELPATH: str = "research/v2a/results_manifest.json"
V2A_REGISTRY_RELPATH: str = "research/v2a/research_registry.jsonl"

EXPECTED_ROW_COUNT: int = 2221


class ProvenanceGraphError(V2ValidationError):
    """The raw-to-result provenance graph failed a structural or semantic invariant."""


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    """One artifact in the derivation DAG plus its recomputed identity."""

    node_id: str
    kind: str
    identity: str


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """A parent -> child derivation edge and whether it verified semantically."""

    parent: str
    child: str
    relation: str
    verified: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    """The whole provenance DAG, its per-edge verification, and any problems found."""

    nodes: tuple[ProvenanceNode, ...]
    edges: tuple[ProvenanceEdge, ...]
    problems: tuple[str, ...]
    deep: bool

    @property
    def ok(self) -> bool:
        return not self.problems

    def edge(self, parent: str, child: str) -> ProvenanceEdge | None:
        for e in self.edges:
            if e.parent == parent and e.child == child:
                return e
        return None


@dataclass
class _Builder:
    """Mutable accumulator for nodes, edges, and problems during one evaluation."""

    nodes: list[ProvenanceNode] = field(default_factory=list)
    edges: list[ProvenanceEdge] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def node(self, node_id: str, kind: str, identity: str) -> None:
        self.nodes.append(ProvenanceNode(node_id, kind, identity))

    def edge(
        self, parent: str, child: str, relation: str, verified: bool, detail: str = ""
    ) -> None:
        self.edges.append(ProvenanceEdge(parent, child, relation, verified, detail))
        if not verified:
            self.problems.append(f"edge {parent} -> {child} ({relation}) failed: {detail or 'no'}")


def _load_map(path: Path) -> dict[str, object]:
    return dict(require_mapping(path.name, strict_json_loads(path.read_bytes())))


def _sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _wrap(problems: list[str], label: str, fn: object, root: Path) -> None:
    """Run a ``None``-returning verifier that raises on drift; record its failure."""
    assert callable(fn)
    try:
        fn(root)
    except (V2ValidationError, OSError) as exc:
        problems.append(f"{label}: {exc}")


def _evaluate(root: Path, *, deep: bool) -> ProvenanceGraph:
    b = _Builder()

    # ------------------------------------------------------------------ #
    # BTC raw (genesis + audit) -> BTC canonical dataset -> joint partition #
    # ------------------------------------------------------------------ #
    # build_joint_partition re-derives the canonical BTC series from the raw bundles
    # (re-proving genesis == audit and refusing equal workflow run ids), reconstructs the
    # research-train ETH leg through the firewalled loader, aligns them, and recomputes every
    # fingerprint -- one semantic reduction of raw -> canonical -> aligned partition.
    eth_fp = ""
    btc_fp = ""
    joint_fp = ""
    jp_rows = 0
    try:
        jp = build_joint_partition(root)
        eth_fp = jp.eth_dataset_fingerprint
        btc_fp = jp.btc_dataset_fingerprint
        joint_fp = jp.combined_partition_fingerprint
        jp_rows = jp.row_count
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"joint-partition: {exc}")

    g_run, g_commit = _receipt_identity(root, GENESIS_ATTEMPT_ID, b)
    a_run, a_commit = _receipt_identity(root, AUDIT_ATTEMPT_ID, b)
    independent = bool(g_run) and bool(a_run) and g_run != a_run and g_commit != a_commit

    b.node("btc_raw_genesis", "raw_acquisition", g_run)
    b.node("btc_raw_audit", "raw_acquisition", a_run)
    b.node("btc_canonical_dataset", "dataset", btc_fp)
    b.node("eth_research_train", "dataset", eth_fp)
    b.node("joint_partition", "partition", joint_fp)
    b.edge(
        "btc_raw_genesis",
        "btc_canonical_dataset",
        "reduces_to_canonical",
        bool(btc_fp),
        "genesis raw reduces to the re-derived canonical daily series",
    )
    b.edge(
        "btc_raw_audit",
        "btc_canonical_dataset",
        "reproduces_canonical",
        bool(btc_fp) and independent,
        "an independent audit run reproduces the identical canonical series",
    )
    b.edge(
        "btc_canonical_dataset",
        "joint_partition",
        "aligned_into_partition",
        bool(joint_fp)
        and jp_rows == EXPECTED_ROW_COUNT
        and btc_fp == ACCEPTED_BTC_DATASET_FINGERPRINT,
        "the partition's BTC leg equals the re-derived canonical fingerprint",
    )
    b.edge(
        "eth_research_train",
        "joint_partition",
        "aligned_into_partition",
        bool(joint_fp) and eth_fp == ACCEPTED_ETH_DATASET_FINGERPRINT,
        "the partition's ETH leg equals the accepted ETH dataset identity",
    )
    # The committed joint identity's recorded fingerprints must equal the recomputed ones;
    # any other byte-change to that file is caught transitively by the protocol sha binding.
    _bind_committed_joint(root, b, eth_fp=eth_fp, btc_fp=btc_fp, joint_fp=joint_fp)

    # ------------------------------------------------------------------ #
    # research memory: family catalog + rejected index bound by sha        #
    # ------------------------------------------------------------------ #
    b.problems.extend(f"research-memory: {p}" for p in verify_research_memory(root))
    _bind_research_memory(root, b)

    # ------------------------------------------------------------------ #
    # partition + freeze + scenarios + multiplicity -> protocol identity   #
    # ------------------------------------------------------------------ #
    proto_fp = ""
    try:
        proto_fp = protocol_fingerprint(root)
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"protocol: {exc}")
    _wrap(b.problems, "protocol", verify_protocol_identity, root)
    _wrap(b.problems, "candidate-source-freeze", verify_candidate_source_freeze, root)
    _wrap(b.problems, "execution-scenarios", verify_scenario_declaration, root)
    b.problems.extend(f"multiplicity: {p}" for p in verify_multiplicity(root))
    b.node("protocol_identity", "protocol", proto_fp)
    _bind_protocol_components(root, b, proto_fp)

    # ------------------------------------------------------------------ #
    # protocol + evaluation evidence -> results -> decision                #
    # ------------------------------------------------------------------ #
    results_fp = ""
    nominated: str | None = None
    verdict = ""
    pkg_version = ""
    try:
        results_bytes = (root / V2B_RESULTS_RELPATH).read_bytes()
        summary = summarize_committed(results_bytes)
        results_fp = summary.fingerprint
        nominated = summary.nominated_candidate_id
        verdict = summary.verdict
        results_doc = _load_map(root / V2B_RESULTS_RELPATH)
        pkg_version = str(results_doc.get("package_version", ""))
        results_proto = summary.protocol_fingerprint
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"v2b-results: {exc}")
        results_proto = ""
    b.node("v2b_results", "results", results_fp)
    b.node("v2b_decision", "decision", "nominated=None" if nominated is None else nominated)
    b.node("package_version", "version", pkg_version)
    b.edge(
        "protocol_identity",
        "v2b_results",
        "produced_under_protocol",
        bool(results_fp) and bool(proto_fp) and results_proto == proto_fp,
        "results carry the committed protocol fingerprint",
    )
    b.edge(
        "v2b_results",
        "v2b_decision",
        "contains_decision",
        bool(results_fp),
        "the pure decision is embedded in the results",
    )
    b.edge(
        "package_version",
        "v2b_results",
        "stamps_version",
        bool(results_fp) and pkg_version == eth_research.__version__ == ACCEPTED_PACKAGE_VERSION,
        "results are stamped with the running package version",
    )

    # ------------------------------------------------------------------ #
    # results -> manifest -> registry completed                            #
    # ------------------------------------------------------------------ #
    pub_problems = verify_publication(root)
    b.problems.extend(f"publication: {p}" for p in pub_problems)
    b.node("v2b_results_manifest", "manifest", results_fp)
    b.edge(
        "v2b_results",
        "v2b_results_manifest",
        "published_as",
        not pub_problems,
        "the manifest binds the committed results sha + fingerprint",
    )

    reg_problems = verify_registry_bound(root)
    b.problems.extend(f"registry: {p}" for p in reg_problems)
    completed_fp = _registry_completed_fingerprint(root, b)
    b.node("registry_completed", "registry_event", completed_fp)
    b.edge(
        "v2b_results",
        "registry_completed",
        "bound_by_fingerprint",
        bool(results_fp) and completed_fp == results_fp,
        "the completed event binds exactly the published results fingerprint",
    )
    b.edge(
        "protocol_identity",
        "registry_completed",
        "registered_under_protocol",
        not reg_problems,
        "every registry event carries the committed protocol fingerprint",
    )

    # ------------------------------------------------------------------ #
    # decision + registry -> commercial-readiness posture                  #
    # ------------------------------------------------------------------ #
    buyer_ok = True
    try:
        verify_buyer_evidence(root)
    except (V2ValidationError, OSError) as exc:
        buyer_ok = False
        b.problems.append(f"commercial-readiness: {exc}")
    b.node("commercial_readiness", "posture", "not_sell_ready")
    b.edge(
        "v2b_decision",
        "commercial_readiness",
        "informs_posture",
        buyer_ok and nominated is None,
        "the null nomination preserves the not-sell-ready posture",
    )
    b.edge(
        "registry_completed",
        "commercial_readiness",
        "terminal_state",
        buyer_ok and not reg_problems,
        "the terminal completed event backs the commercial posture",
    )

    # ------------------------------------------------------------------ #
    # accepted V2A null -> multiplicity + commercial readiness             #
    # ------------------------------------------------------------------ #
    v2a_fp = _bind_v2a_accepted_null(root, b, buyer_ok)

    # ------------------------------------------------------------------ #
    # deep mode: pin the reconstruction to the accepted external anchors    #
    # ------------------------------------------------------------------ #
    if deep:
        _deep_anchor_checks(
            b,
            btc_fp=btc_fp,
            eth_fp=eth_fp,
            joint_fp=joint_fp,
            joint_rows=jp_rows,
            proto_fp=proto_fp,
            results_fp=results_fp,
            nominated=nominated,
            verdict=verdict,
            v2a_fp=v2a_fp,
        )

    return ProvenanceGraph(
        nodes=tuple(b.nodes),
        edges=tuple(b.edges),
        problems=tuple(b.problems),
        deep=deep,
    )


def _bind_research_memory(root: Path, b: _Builder) -> None:
    cat = root / RESEARCH_FAMILY_CATALOG_RELPATH
    rej = root / REJECTED_FAMILY_INDEX_RELPATH
    mem_path = root / MEMORY_STATE_RELPATH
    cat_sha = ""
    rej_sha = ""
    mem: dict[str, object] = {}
    try:
        cat_sha = _sha(cat)
        rej_sha = _sha(rej)
        mem = _load_map(mem_path)
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"research-memory-binding: {exc}")
    b.node("research_family_catalog", "catalog", cat_sha)
    b.node("rejected_family_index", "index", rej_sha)
    b.node("research_memory_state", "state", str(mem.get("milestone", "")))
    b.edge(
        "research_family_catalog",
        "research_memory_state",
        "bound_by_sha",
        bool(cat_sha) and mem.get("family_catalog_sha256") == cat_sha,
        "the memory state binds the family catalog by sha",
    )
    b.edge(
        "rejected_family_index",
        "research_memory_state",
        "bound_by_sha",
        bool(rej_sha) and mem.get("rejected_family_index_sha256") == rej_sha,
        "the memory state binds the rejected-family index by sha",
    )


def _bind_protocol_components(root: Path, b: _Builder, proto_fp: str) -> None:
    """Recompute each protocol input's sha and confirm the committed protocol binds it."""
    try:
        components = require_mapping(
            "protocol.components", _load_map(root / V2B_PROTOCOL_RELPATH).get("components")
        )
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"protocol-components: {exc}")
        components = {}
    bindings = (
        (
            "candidate_source_freeze",
            CANDIDATE_SOURCE_FREEZE_RELPATH,
            "candidate_source_freeze_sha256",
        ),
        ("joint_partition", JOINT_PARTITION_IDENTITY_RELPATH, "joint_partition_identity_sha256"),
        ("execution_scenarios", EXECUTION_SCENARIOS_RELPATH, "execution_scenarios_sha256"),
        ("multiplicity_state", MULTIPLICITY_STATE_RELPATH, "multiplicity_state_sha256"),
    )
    b.node("candidate_source_freeze", "freeze", _safe_sha(root / CANDIDATE_SOURCE_FREEZE_RELPATH))
    b.node("execution_scenarios", "scenarios", _safe_sha(root / EXECUTION_SCENARIOS_RELPATH))
    b.node("multiplicity_state", "state", _safe_sha(root / MULTIPLICITY_STATE_RELPATH))
    for node_id, relpath, comp_key in bindings:
        live = _safe_sha(root / relpath)
        b.edge(
            node_id,
            "protocol_identity",
            "bound_by_sha",
            bool(proto_fp) and bool(live) and components.get(comp_key) == live,
            f"the protocol binds {relpath} by sha",
        )


def _registry_completed_fingerprint(root: Path, b: _Builder) -> str:
    try:
        events = read_events(root / V2B_REGISTRY_RELPATH)
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"registry-read: {exc}")
        return ""
    completed = [e for e in events if e.event == COMPLETED]
    if not completed:
        return ""
    fp = completed[-1].payload.get("results_fingerprint")
    return fp if isinstance(fp, str) else ""


def _bind_v2a_accepted_null(root: Path, b: _Builder, buyer_ok: bool) -> str:
    v2a_fp = ""
    manifest_ok = False
    registry_ok = False
    try:
        v2a_fp = canonical_sha256(strict_json_loads((root / V2A_RESULTS_RELPATH).read_bytes()))
        manifest = _load_map(root / V2A_MANIFEST_RELPATH)
        manifest_ok = (
            manifest.get("results_fingerprint") == v2a_fp
            and manifest.get("nominated_candidate_id") is None
        )
        v2a_events = v2_read_events(root / V2A_REGISTRY_RELPATH)
        v2a_completed = [e for e in v2a_events if e.event == "completed"]
        payload_fp = v2a_completed[-1].payload.get("results_fingerprint") if v2a_completed else None
        registry_ok = payload_fp == v2a_fp
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"v2a-accepted-null: {exc}")
    b.node("v2a_accepted_null", "results", v2a_fp)
    b.edge(
        "v2a_accepted_null",
        "commercial_readiness",
        "preserved_negative",
        buyer_ok and manifest_ok and registry_ok,
        "the accepted V2A null is a manifest- and registry-bound negative",
    )
    b.edge(
        "v2a_accepted_null",
        "multiplicity_state",
        "feeds_cumulative_correction",
        manifest_ok and registry_ok,
        "the prior V2A family count feeds the cumulative correction",
    )
    return v2a_fp


def _safe_sha(path: Path) -> str:
    try:
        return _sha(path)
    except OSError:
        return ""


def _deep_anchor_checks(
    b: _Builder,
    *,
    btc_fp: str,
    eth_fp: str,
    joint_fp: str,
    joint_rows: int,
    proto_fp: str,
    results_fp: str,
    nominated: str | None,
    verdict: str,
    v2a_fp: str,
) -> None:
    """Pin the reconstruction to the accepted anchors; a stale subgraph fails here."""
    checks: tuple[tuple[str, str, str], ...] = (
        ("BTC dataset", btc_fp, ACCEPTED_BTC_DATASET_FINGERPRINT),
        ("ETH dataset", eth_fp, ACCEPTED_ETH_DATASET_FINGERPRINT),
        ("joint partition", joint_fp, ACCEPTED_JOINT_PARTITION_FINGERPRINT),
        ("V2B protocol", proto_fp, V2B_PROTOCOL_FINGERPRINT),
        ("V2B results", results_fp, V2B_RESULTS_FINGERPRINT),
        ("V2A results", v2a_fp, V2A_RESULTS_FINGERPRINT),
    )
    for label, got, anchor in checks:
        if not got:
            b.problems.append(f"deep: {label} could not be reconstructed from committed bytes")
        elif got != anchor:
            b.problems.append(f"deep: {label} fingerprint {got} != accepted anchor {anchor}")
    if joint_rows != EXPECTED_ROW_COUNT:
        b.problems.append(
            f"deep: reconstructed {joint_rows} aligned rows, expected {EXPECTED_ROW_COUNT}"
        )
    if results_fp:
        if nominated is not None:
            b.problems.append("deep: a candidate was nominated, but the accepted result is null")
        if "NOT SELL-READY" not in verdict.upper():
            b.problems.append("deep: reconstructed verdict is not the accepted not-sell-ready")


def _receipt_identity(root: Path, attempt_id: str, b: _Builder) -> tuple[str, str]:
    """Cheaply read one acquisition receipt's (workflow_run_id, source_commit)."""
    path = root / "research/v2b/raw/coinbase" / attempt_id / "acquisition_receipt.json"
    try:
        obj = _load_map(path)
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"btc-receipt: {attempt_id}: {exc}")
        return ("", "")
    return (str(obj.get("workflow_run_id", "")), str(obj.get("source_commit", "")))


def _bind_committed_joint(
    root: Path, b: _Builder, *, eth_fp: str, btc_fp: str, joint_fp: str
) -> None:
    """The committed joint identity's recorded fingerprints equal the recomputed ones."""
    try:
        committed = _load_map(root / JOINT_PARTITION_IDENTITY_RELPATH)
    except (V2ValidationError, OSError) as exc:
        b.problems.append(f"joint-partition: committed identity unreadable: {exc}")
        return
    for key, recomputed in (
        ("eth_dataset_fingerprint", eth_fp),
        ("btc_dataset_fingerprint", btc_fp),
        ("combined_partition_fingerprint", joint_fp),
    ):
        if recomputed and committed.get(key) != recomputed:
            b.problems.append(f"joint-partition: committed {key} != the recomputed identity")


def build_provenance_graph(repo_root: str | Path) -> ProvenanceGraph:
    """Build + semantically verify the raw-to-result provenance DAG (shallow mode)."""
    return _evaluate(Path(repo_root), deep=False)


def verify_provenance_graph(repo_root: str | Path, *, deep: bool = False) -> list[str]:
    """Return every provenance problem (empty == the whole graph binds; deep pins anchors)."""
    return list(_evaluate(Path(repo_root), deep=deep).problems)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B raw-to-result provenance graph (offline).")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on any problem.")
    parser.add_argument("--deep", action="store_true", help="Pin to the accepted anchors.")
    args = parser.parse_args(argv)
    problems = verify_provenance_graph(args.repo_root, deep=args.deep)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 1 if problems and args.check else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ACCEPTED_ETH_DATASET_FINGERPRINT",
    "ACCEPTED_JOINT_PARTITION_FINGERPRINT",
    "ACCEPTED_PACKAGE_VERSION",
    "ProvenanceEdge",
    "ProvenanceGraph",
    "ProvenanceGraphError",
    "ProvenanceNode",
    "build_provenance_graph",
    "verify_provenance_graph",
]
