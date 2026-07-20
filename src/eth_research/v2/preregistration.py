"""The V2A one-shot pre-registration: the committed, hash-pinned statement of what will be run.

Written and committed *before* the single governed research run (checkpoint ``R``), the
pre-registration binds — by fingerprint — the exact protocol, candidate set, constitution, one-shot
budget, and buyer contract the run will use, together with the package version and the planned run
identity. Because it is committed while the registry and results are still absent (the *pristine*
state), it fixes the rules and the plan before any outcome is known: the published results
(checkpoint ``P``) can then be checked, fingerprint for fingerprint, against exactly what was
pre-registered.

It carries no wall-clock and is a pure function of the frozen source, so it reproduces byte-for-byte
and :func:`V2APreRegistration.parse` re-asserts every fingerprint against the current source: a
committed pre-registration that no longer matches the code it was made against is rejected.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from eth_research import __version__
from eth_research.buyer.contract import EvaluationContract
from eth_research.v2.budget import OneShotResearchBudget
from eth_research.v2.candidates import V2A_CANDIDATES
from eth_research.v2.constitution import CommercialEvidenceConstitution
from eth_research.v2.protocol import ResearchProtocol
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
    load_canonical_json,
    require_exact_keys,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

PREREGISTRATION_SCHEMA_VERSION: int = 1

# Governed artifacts live under this directory (same as the published results + registry).
V2A_DIR: str = "research/v2a"
PREREGISTRATION_NAME: str = "pre_registration.json"

_PREREGISTRATION_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "package_version",
        "protocol_fingerprint",
        "constitution_fingerprint",
        "budget_fingerprint",
        "contract_fingerprint",
        "candidate_fingerprints",
    }
)


class PreRegistrationError(V2ValidationError):
    """A pre-registration artifact was malformed or drifted from the frozen source."""


@dataclass(frozen=True, slots=True)
class V2APreRegistration:
    """The committed, hashable pre-registration of the V2A one-shot run."""

    schema_version: int
    run_id: str
    package_version: str
    protocol_fingerprint: str
    constitution_fingerprint: str
    budget_fingerprint: str
    contract_fingerprint: str
    candidate_fingerprints: dict[str, str]

    @staticmethod
    def build(run_id: str) -> V2APreRegistration:
        """Pin the current protocol / constitution / budget / contract / candidate fingerprints."""
        return V2APreRegistration(
            schema_version=PREREGISTRATION_SCHEMA_VERSION,
            run_id=require_slug("pre_registration.run_id", run_id),
            package_version=__version__,
            protocol_fingerprint=ResearchProtocol.current().fingerprint(),
            constitution_fingerprint=CommercialEvidenceConstitution.current().fingerprint(),
            budget_fingerprint=OneShotResearchBudget.current().fingerprint(),
            contract_fingerprint=EvaluationContract.current().fingerprint(),
            candidate_fingerprints={s.candidate_id: s.fingerprint() for s in V2A_CANDIDATES},
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "package_version": self.package_version,
            "protocol_fingerprint": self.protocol_fingerprint,
            "constitution_fingerprint": self.constitution_fingerprint,
            "budget_fingerprint": self.budget_fingerprint,
            "contract_fingerprint": self.contract_fingerprint,
            "candidate_fingerprints": dict(sorted(self.candidate_fingerprints.items())),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> V2APreRegistration:
        """Strictly decode a committed pre-registration and re-assert it matches the frozen source.

        Every pinned fingerprint must still equal the current source's fingerprint; one that no
        longer matches the code it was made against is rejected (drift is never accepted).
        """
        obj = require_mapping("pre_registration", raw)
        require_exact_keys("pre_registration", obj, _PREREGISTRATION_KEYS)
        cf_obj = require_mapping(
            "pre_registration.candidate_fingerprints", obj["candidate_fingerprints"]
        )
        candidate_fingerprints = {
            require_slug("pre_registration.candidate_fingerprints.key", k): require_hex64(
                f"pre_registration.candidate_fingerprints.{k}", v
            )
            for k, v in cf_obj.items()
        }
        prereg = V2APreRegistration(
            schema_version=require_int("pre_registration.schema_version", obj["schema_version"]),
            run_id=require_slug("pre_registration.run_id", obj["run_id"]),
            package_version=require_nonempty_str(
                "pre_registration.package_version", obj["package_version"]
            ),
            protocol_fingerprint=require_hex64(
                "pre_registration.protocol_fingerprint", obj["protocol_fingerprint"]
            ),
            constitution_fingerprint=require_hex64(
                "pre_registration.constitution_fingerprint", obj["constitution_fingerprint"]
            ),
            budget_fingerprint=require_hex64(
                "pre_registration.budget_fingerprint", obj["budget_fingerprint"]
            ),
            contract_fingerprint=require_hex64(
                "pre_registration.contract_fingerprint", obj["contract_fingerprint"]
            ),
            candidate_fingerprints=candidate_fingerprints,
        )
        expected = V2APreRegistration.build(prereg.run_id)
        if prereg.fingerprint() != expected.fingerprint():
            raise PreRegistrationError(
                "pre-registration drifted from the frozen source (a pinned fingerprint no longer "
                "matches the current protocol/constitution/budget/contract/candidate set)"
            )
        return prereg


def _stage(path: Path, data: bytes) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return tmp


def _fsync_dir(path: Path) -> None:
    with suppress(OSError):  # pragma: no cover - best-effort directory durability
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_preregistration(repo_root: str | Path, prereg: V2APreRegistration) -> Path:
    """Durably write the pre-registration under ``research/v2a`` and return its path."""
    out_dir = Path(repo_root) / V2A_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / PREREGISTRATION_NAME
    tmp = _stage(path, canonical_json_bytes(prereg.to_canonical()))
    os.replace(tmp, path)
    _fsync_dir(out_dir)
    return path


def load_preregistration(repo_root: str | Path) -> V2APreRegistration:
    """Load and strictly re-verify the committed pre-registration (raises if absent or drifted)."""
    path = Path(repo_root) / V2A_DIR / PREREGISTRATION_NAME
    if not path.exists():
        raise PreRegistrationError(f"no pre-registration found at {V2A_DIR}/{PREREGISTRATION_NAME}")
    return V2APreRegistration.parse(load_canonical_json(path))


def verify_preregistration(repo_root: str | Path) -> list[str]:
    """Return problems with the committed pre-registration (empty if absent or valid)."""
    path = Path(repo_root) / V2A_DIR / PREREGISTRATION_NAME
    if not path.exists():
        return []  # pristine (pre-R) state; nothing pre-registered yet.
    try:
        V2APreRegistration.parse(load_canonical_json(path))
    except V2ValidationError as exc:
        return [f"pre_registration.json is invalid: {exc}"]
    return []
