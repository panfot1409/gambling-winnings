"""V2C section 30: the intellectual-property dossier (catalog, not disclosure).

Catalogs the *categories* of intellectual property the programme holds -- the research methodology,
the candidate families that were evaluated and did not qualify, the operational-qualification
platform, the process-isolated buyer boundary, and the offline prospective governance -- **without
disclosing any of them**. Every category is marked private and not publicly disclosed; no candidate
id, strategy rule, or sealed value appears. The dossier also states plainly what protects the IP
and, more importantly, what does **not**: it carries the honest reverse-engineering exposure --
process isolation and redaction do not prove the core IP cannot be reverse engineered.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_bool,
    require_choice,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

IP_DOSSIER_SCHEMA_VERSION: int = 1

#: The only protection state a category may declare: the source is withheld and kept private.
PROTECTION_PRIVATE_WITHHELD: str = "private_source_withheld"


class IPDossierError(V2ValidationError):
    """An IP dossier category or the dossier as a whole violated its contract."""


@dataclass(frozen=True, slots=True)
class IPCategory:
    """One category of IP, described generically and never disclosed."""

    category_id: str
    description: str
    protection: str
    disclosed_publicly: bool

    @staticmethod
    def parse(label: str, value: object) -> IPCategory:
        obj = require_mapping(label, value)
        require_exact_keys(
            label, obj, {"category_id", "description", "protection", "disclosed_publicly"}
        )
        disclosed = require_bool(f"{label}.disclosed_publicly", obj["disclosed_publicly"])
        if disclosed:
            raise IPDossierError(f"{label}.disclosed_publicly must be false; the IP is private")
        return IPCategory(
            category_id=require_slug(f"{label}.category_id", obj["category_id"]),
            description=require_nonempty_str(f"{label}.description", obj["description"]),
            protection=require_choice(
                f"{label}.protection", obj["protection"], frozenset({PROTECTION_PRIVATE_WITHHELD})
            ),
            disclosed_publicly=disclosed,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "category_id": self.category_id,
            "description": self.description,
            "protection": self.protection,
            "disclosed_publicly": self.disclosed_publicly,
        }


@dataclass(frozen=True, slots=True)
class IPDossier:
    """The fixed IP dossier: categories + what protects them + the honest exposure statement."""

    categories: tuple[IPCategory, ...]
    protected_by: tuple[str, ...]
    not_protected_by: tuple[str, ...]
    reverse_engineering_exposure: str
    honest_limitation: str

    @staticmethod
    def current() -> IPDossier:
        return IPDossier(
            categories=(
                IPCategory(
                    category_id="research_methodology",
                    description=(
                        "The pre-registered, cost-aware, bootstrapped research methodology and its "
                        "firewalled partitions and governance ledgers."
                    ),
                    protection=PROTECTION_PRIVATE_WITHHELD,
                    disclosed_publicly=False,
                ),
                IPCategory(
                    category_id="evaluated_candidate_families",
                    description=(
                        "The candidate families evaluated on the research-train partition and the "
                        "negative evidence that none was nominated; described only in aggregate."
                    ),
                    protection=PROTECTION_PRIVATE_WITHHELD,
                    disclosed_publicly=False,
                ),
                IPCategory(
                    category_id="operational_qualification_platform",
                    description=(
                        "The signal-only shadow platform and virtual-time qualification harness, "
                        "including the fault taxonomy and offline SLO model."
                    ),
                    protection=PROTECTION_PRIVATE_WITHHELD,
                    disclosed_publicly=False,
                ),
                IPCategory(
                    category_id="buyer_evaluation_boundary",
                    description=(
                        "The process-isolated buyer boundary, redaction policy, and reference "
                        "evaluation gateway that serve only a redacted surface."
                    ),
                    protection=PROTECTION_PRIVATE_WITHHELD,
                    disclosed_publicly=False,
                ),
                IPCategory(
                    category_id="prospective_governance",
                    description=(
                        "The offline prospective-proposal lifecycle, maturity policy, and "
                        "source-independent update-proposal format."
                    ),
                    protection=PROTECTION_PRIVATE_WITHHELD,
                    disclosed_publicly=False,
                ),
            ),
            protected_by=(
                "private_repository_visibility",
                "redaction_policy_on_the_buyer_surface",
                "source_free_buyer_harness",
                "no_public_publication_vector",
                "process_isolation_of_the_buyer_client",
            ),
            not_protected_by=(
                "no_patent",
                "no_registered_trademark",
                "no_license_granted",
                "no_in_code_enforcement_of_any_nda_or_contract",
                "no_guarantee_against_reverse_engineering",
            ),
            reverse_engineering_exposure=(
                "A buyer who runs the vendor process observes only the redacted evaluation surface "
                "(factsheet, claims catalog, readiness scorecard, contract) and never the private "
                "source. That is process isolation and redaction, not a guarantee: it does not "
                "prove the core IP cannot be reverse engineered from observed behaviour over time."
            ),
            honest_limitation=(
                "This dossier is a catalog of IP categories, not the IP itself. It discloses no "
                "candidate id, strategy rule, or sealed value. Its purpose is an honest inventory "
                "of what is held and how weakly or strongly it is protected."
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": IP_DOSSIER_SCHEMA_VERSION,
            "dossier_id": "v2c_ip_dossier",
            "categories": [c.to_canonical() for c in self.categories],
            "protected_by": list(self.protected_by),
            "not_protected_by": list(self.not_protected_by),
            "reverse_engineering_exposure": self.reverse_engineering_exposure,
            "honest_limitation": self.honest_limitation,
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> IPDossier:
        obj = require_mapping("ip_dossier", raw)
        require_exact_keys(
            "ip_dossier",
            obj,
            {
                "schema_version",
                "dossier_id",
                "categories",
                "protected_by",
                "not_protected_by",
                "reverse_engineering_exposure",
                "honest_limitation",
            },
        )
        if (
            require_int("ip_dossier.schema_version", obj["schema_version"])
            != IP_DOSSIER_SCHEMA_VERSION
        ):
            raise IPDossierError("schema_version drifted from the fixed definition")
        categories = tuple(
            require_list("ip_dossier.categories", obj["categories"], IPCategory.parse)
        )
        if not categories:
            raise IPDossierError("ip_dossier must have at least one category")
        protected = tuple(
            require_nonempty_str(f"ip_dossier.protected_by[{i}]", item)
            for i, item in enumerate(
                require_list("ip_dossier.protected_by", obj["protected_by"], lambda _l, v: v)
            )
        )
        not_protected = tuple(
            require_nonempty_str(f"ip_dossier.not_protected_by[{i}]", item)
            for i, item in enumerate(
                require_list(
                    "ip_dossier.not_protected_by", obj["not_protected_by"], lambda _l, v: v
                )
            )
        )
        dossier = IPDossier(
            categories=categories,
            protected_by=protected,
            not_protected_by=not_protected,
            reverse_engineering_exposure=require_nonempty_str(
                "ip_dossier.reverse_engineering_exposure", obj["reverse_engineering_exposure"]
            ),
            honest_limitation=require_nonempty_str(
                "ip_dossier.honest_limitation", obj["honest_limitation"]
            ),
        )
        if dossier.fingerprint() != IPDossier.current().fingerprint():
            raise IPDossierError("ip dossier drifted from the fixed definition")
        return dossier


__all__ = [
    "IP_DOSSIER_SCHEMA_VERSION",
    "PROTECTION_PRIVATE_WITHHELD",
    "IPCategory",
    "IPDossier",
    "IPDossierError",
]
