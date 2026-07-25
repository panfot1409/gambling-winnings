"""The acceptance layer's invariants, and which enforcement path states each one.

Three code paths verify the accepted proposal:

* ``production`` — :mod:`eth_research.m3e.acceptance`, the writer's own verifier;
* ``compatibility`` — :mod:`eth_research.m3f.growable` inside the isolated M3F
  package, which may import only ``eth_research._json`` from the rest of the
  package and therefore re-implements what it checks;
* ``independent`` — ``tools/m3f_independent_verify.py``, standard library only,
  importing no ``eth_research`` module at all.

Terminology, stated once and used consistently
----------------------------------------------
These are **enforcement paths**, not independent trust anchors. All three read
the same repository and the same git objects. Running three separately written
implementations improves *implementation coverage* — a transcription error, a
wrong regex or a mis-ordered digest in one is visible as a disagreement with the
others — but it creates no external trust. The ``independent`` path is
independent of the *package*, not of the *repository*. Repeating a mutable table
in more places is not an anchor either; that was the original A-1 defect.

Honest coverage
---------------
``paths`` below records which enforcement paths actually state each invariant
today, as measured, not as aspired to. Several invariants are single-path, and
that is written down rather than smoothed over: an invariant enforced once is
one implementation defect away from being enforced never. Each such entry
carries ``gap`` explaining why.

How the shadow paths reach the root pins without importing them
---------------------------------------------------------------
``ROOT-01..03`` depend on constants in ``eth_research.m3e.proposal_authority``,
which neither shadow path may import. They do not need to. Independence means
interpreting the same frozen evidence with different code, not pretending the
evidence does not exist — so each shadow path parses that committed source with
``ast`` (``literal_eval`` only, never executing it), pulls the pins out of the
syntax tree, and re-derives the genesis root from the trusted commit's git
objects using its own digest primitives. Sharing the frozen constants is the
point; sharing the code that interprets them would be the circularity.
"""

from __future__ import annotations

import dataclasses
from typing import Final

PATH_PRODUCTION: Final[str] = "production"
PATH_COMPATIBILITY: Final[str] = "compatibility"
PATH_INDEPENDENT: Final[str] = "independent"

ALL_PATHS: Final[tuple[str, ...]] = (PATH_PRODUCTION, PATH_COMPATIBILITY, PATH_INDEPENDENT)

CATALOG_SCHEMA_VERSION: Final[int] = 1


@dataclasses.dataclass(frozen=True, slots=True)
class Invariant:
    """One named invariant of the acceptance layer."""

    invariant_id: str
    statement: str
    #: Enforcement paths that actually state this invariant today.
    paths: tuple[str, ...]
    #: Why the coverage is not all three, when it is not. Empty when it is.
    gap: str = ""

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError(f"{self.invariant_id}: an invariant with no enforcement is not one")
        unknown = sorted(set(self.paths) - set(ALL_PATHS))
        if unknown:
            raise ValueError(f"{self.invariant_id}: unknown path(s) {unknown}")
        if len(self.paths) < len(ALL_PATHS) and not self.gap:
            raise ValueError(
                f"{self.invariant_id}: partial coverage must state its gap, not leave it implicit"
            )
        if len(self.paths) == len(ALL_PATHS) and self.gap:
            raise ValueError(f"{self.invariant_id}: full coverage cannot also declare a gap")


_ALL = ALL_PATHS
_P = (PATH_PRODUCTION,)

CATALOG: Final[tuple[Invariant, ...]] = (
    # --- root of authority -------------------------------------------------
    Invariant(
        "ROOT-01",
        "the chain's genesis root is derived from source constants plus bytes read "
        "out of a pinned historical commit, never from the working tree",
        _ALL,
    ),
    Invariant(
        "ROOT-02",
        "each authority table, as stored at the trusted baseline commit, hashes to "
        "the digest pinned in committed source",
        _ALL,
    ),
    Invariant(
        "ROOT-03",
        "working-tree copies of the authority tables are treated as derived caches "
        "and verified one way, from history to disk, never consulted as authority",
        _ALL,
    ),
    # --- git identity and genealogy ---------------------------------------
    Invariant(
        "GIT-01",
        "every pinned commit id is a literal full lowercase 40-hex object id; "
        "uppercase, abbreviations and revision syntax (^ ~ :path @{...}) are refused",
        _ALL,
    ),
    Invariant(
        "GIT-02",
        "every pinned id names an object that exists and whose type is commit",
        _ALL,
    ),
    Invariant(
        "GIT-03",
        "the proposal head's tree is exactly the expected content (right commit id, "
        "wrong content is refused)",
        _ALL,
    ),
    Invariant(
        "GIT-04",
        "the proposal head has exactly one parent and it is exactly the parent the "
        "acceptance names",
        _ALL,
    ),
    Invariant(
        "GIT-05",
        "history is complete and unsubstituted: not shallow, no graft file, no "
        "refs/replace over a pinned object",
        _ALL,
    ),
    # --- the closed proposal file set --------------------------------------
    Invariant(
        "FILE-01",
        "the legal file set is derived by policy from the two pinned commits; the "
        "record's own member list is never used as the allowlist",
        _ALL,
    ),
    Invariant(
        "FILE-02",
        "every member's role is decided from its path and the proposal identity alone, "
        "with no channel through which a manifest or a pin could reach the decision",
        _ALL,
    ),
    Invariant(
        "FILE-03",
        "the record's file-set binding re-derives exactly: a widened, narrowed or "
        "relabelled member set is refused, as is an unknown binding field",
        _ALL,
    ),
    Invariant(
        "FILE-04",
        "the accepted proposal directory on disk is a closed set: exactly the pinned "
        "members, no more and no fewer",
        _ALL,
    ),
    # --- the acceptance chain ----------------------------------------------
    Invariant(
        "CHAIN-01",
        "the registry is an intact hash chain from the empty-string seed, with a "
        "well-formed genesis sentinel",
        _ALL,
    ),
    Invariant(
        "CHAIN-02",
        "the acceptance record and its completion each verify their own domain-separated "
        "self-hash, and the completion binds the record it completes",
        _ALL,
    ),
    Invariant(
        "CHAIN-03",
        "sequence numbers are contiguous from one with no duplicate, reordered or "
        "gapped entry, and no proposal is accepted twice",
        _ALL,
    ),
    # --- the data the acceptance is about ----------------------------------
    Invariant(
        "DATA-01",
        "row arithmetic is true, not merely present: previous + appended == new",
        _ALL,
    ),
    Invariant(
        "DATA-02",
        "the append window is arithmetically consistent: [first_open, last_open] spans "
        "exactly as many days as the record claims rows",
        _ALL,
    ),
    Invariant(
        "DATA-03",
        "the prior canonical rows are MEASURED to be an exact prefix of the grown rows, "
        "recomputed from the raw bundles rather than asserted",
        _P,
        gap="re-measuring requires the M3E row-reconstruction code; the shadow paths "
        "check the record's own counters (changed == deleted == 0) instead, which is "
        "an assertion about a measurement, not the measurement.",
    ),
    Invariant(
        "DATA-04",
        "two runners are attested with byte-identical raw payloads",
        _ALL,
    ),
    Invariant(
        "DATA-05",
        "the working tree equals the chain-head expected state byte for byte",
        _ALL,
    ),
    # --- transitioned state -------------------------------------------------
    Invariant(
        "STATE-01",
        "the new accepted state pins exactly the six transitioned paths — the key set "
        "is checked, so an emptied map cannot assert nothing",
        _ALL,
    ),
    Invariant(
        "STATE-02",
        "every created-evidence path exists and hashes to exactly its pin",
        _ALL,
    ),
    # --- safety -------------------------------------------------------------
    Invariant(
        "SAFE-01",
        "all three sealed ledgers are byte-empty, checked from the files themselves "
        "and not from the record's description of them",
        _ALL,
    ),
    Invariant(
        "SAFE-02",
        "the five governance flags are present as an exact key set and every value is "
        "exactly False",
        _ALL,
    ),
    Invariant(
        "SAFE-03",
        "the record claims no evaluation authority and no maturity: "
        "evaluation_authorized is False, maturity_state is immature, rows < 365",
        _ALL,
    ),
    # --- provenance ---------------------------------------------------------
    Invariant(
        "PROV-01",
        "the recorded proposal head actually CARRIES this proposal's manifest: the blob "
        "at that commit hashes to the record's pin, and the manifest's own self-hash "
        "field is the one the record attests — two distinct digests, bound separately",
        _ALL,
    ),
    Invariant(
        "PROV-02",
        "the acceptance time is inside the lawful window: not before its own append "
        "window closed, and before the governed horizon",
        _ALL,
    ),
    Invariant(
        "PROV-03",
        "the publication commit named by the completion is a real commit and an ancestor of HEAD",
        _ALL,
    ),
    Invariant(
        "PROV-04",
        "every created production proposal is covered by exactly one acceptance and "
        "every acceptance covers a created proposal — neither set may exceed the other",
        _ALL,
    ),
)

BY_ID: Final[dict[str, Invariant]] = {inv.invariant_id: inv for inv in CATALOG}


def invariants_for(path: str) -> tuple[Invariant, ...]:
    """Every invariant the named enforcement path states."""
    if path not in ALL_PATHS:
        raise ValueError(f"unknown enforcement path: {path!r}")
    return tuple(inv for inv in CATALOG if path in inv.paths)


def coverage_gaps() -> tuple[Invariant, ...]:
    """Invariants that fewer than all three paths state. Never empty today."""
    return tuple(inv for inv in CATALOG if len(inv.paths) < len(ALL_PATHS))


def as_json() -> dict[str, object]:
    """The catalog as a plain mapping, for committing and for diffing."""
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "enforcement_paths": list(ALL_PATHS),
        "terminology": (
            "enforcement paths, not independent trust anchors: all three read the same "
            "repository, so this is implementation coverage rather than external trust"
        ),
        "invariant_count": len(CATALOG),
        "fully_covered_count": len(CATALOG) - len(coverage_gaps()),
        "invariants": [
            {
                "invariant_id": inv.invariant_id,
                "statement": inv.statement,
                "paths": list(inv.paths),
                "gap": inv.gap,
            }
            for inv in CATALOG
        ],
    }


__all__ = [
    "ALL_PATHS",
    "BY_ID",
    "CATALOG",
    "CATALOG_SCHEMA_VERSION",
    "PATH_COMPATIBILITY",
    "PATH_INDEPENDENT",
    "PATH_PRODUCTION",
    "Invariant",
    "as_json",
    "coverage_gaps",
    "invariants_for",
]
