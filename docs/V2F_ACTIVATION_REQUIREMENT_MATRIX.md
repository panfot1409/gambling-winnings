# V2F — the 17 paper-activation requirements, classified

Derived live from `eth_research.v2e.paper.derive_requirements`, which reads the eleven
`eth_research.v2.fable5.paper_readiness` gates plus two artifact-presence checks. Every value
below was printed by executing that function, not read from a document.

**Current strict state: 6 of 17 true, 11 false.** The reported lifecycle resting state is
`disabled`.

*(First derived at `d18fc89` as 4 of 17. #14 and #15 were the only implementation-controlled
false values; both were closed by the qualification commit that accompanies this table. Nothing
else moved, and nothing about the authorization outcome changed — see the last section.)*

The point of this table is to stop "13 requirements are false" from being read as "13 things are
wrong". Most of them are false *because the one-shot has not run*, which is the correct state for
a candidate that has deliberately not been evaluated. Only two are false for a reason I can act
on, and exactly one is false for a reason only the owner can act on.

---

## Category legend

| category | meaning |
| --- | --- |
| **impl** | implementation-controlled — I can satisfy it by doing engineering work |
| **owner** | owner-controlled — requires a human act I must not perform |
| **eval** | evaluation-dependent — becomes true only when a one-shot nominates a candidate |
| **activation** | activation-dependent — only meaningful once activation is being attempted |
| **external** | external/legal — requires a third party outside this repository |

## The matrix

| # | requirement | value | evidence source | phase | category | expected false pre-one-shot? | blocks | exact action to satisfy | action authorized now? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `eligible_nominated_candidate` | **False** | `_eligible_candidate_present` ← `decision.nominated_candidate_id` in the committed V2A and V2B results | P | **eval** | **YES** | P, Q, activation | A one-shot must nominate a candidate. Both accepted results nominate nothing — that is their recorded negative finding. | ❌ no partition (§7) |
| 2 | `immutable_candidate_fingerprint` | **False** | `strategy_specification_immutable` gate, derived `= eligible` | P | **eval** | **YES** | P, Q, activation | Same as #1; this gate is an alias of eligibility. | ❌ |
| 3 | `valid_lineage` | **False** | `candidate_lineage_valid` gate, derived `= eligible` | P | **eval** | **YES** | P, Q, activation | Same as #1. | ❌ |
| 4 | `candidate_not_previously_rejected` | **False** | `= eligible` (fails closed: with no candidate there is nothing to be un-rejected) | P | **eval** | **YES** | P, Q, activation | Same as #1. | ❌ |
| 5 | `paper_protocol_preregistered` | **False** | `freeze_present AND eligible` | E, P | **eval** | **YES** | Q, activation | Write `governance/v2/paper_release_freeze.json` **and** have an eligible candidate. The artifact is impl; the gate is gated on #1. | ⚠️ artifact yes, gate no |
| 6 | `risk_parameters_frozen` | **False** | `= release_frozen` (a section of the same freeze artifact) | E | **eval** | **YES** | Q, activation | Same as #5. | ⚠️ |
| 7 | `data_feed_configuration_frozen` | **False** | `= release_frozen` | E | **eval** | **YES** | Q, activation | Same as #5. | ⚠️ |
| 8 | `cost_model_frozen` | **False** | `= release_frozen` | E | **eval** | **YES** | Q, activation | Same as #5. | ⚠️ |
| 9 | `execution_simulator_frozen` | **False** | `= release_frozen` | E | **eval** | **YES** | Q, activation | Same as #5. | ⚠️ |
| 10 | `fable5_acceptance` | **True** ✅ | `platform_audit_complete AND platform_hardened` ← frozen remediation state + audit manifest | pre-E | **impl** | no | — | Already satisfied. Must not regress. | n/a |
| 11 | `no_unresolved_class_abd_defect` | **True** ✅ | `no_unresolved_class_abd_finding` gate | pre-E | **impl** | no | — | Already satisfied. Must not regress. | n/a |
| 12 | `paper_release_source_freeze` | **False** | `= release_frozen` | E | **eval** | **YES** | Q, activation | Same as #5. | ⚠️ |
| 13 | `human_approval_artifact` | **False** | presence of `governance/v2/paper_activation_approval.json` | activation | **owner** | **YES** | activation only | **A human must write that file.** I must not; §2.11/§2.17 reserve it, and writing it myself is the exact self-authorization the gate exists to prevent. | ❌ **owner action** |
| 14 | `kill_switch_qualified` | **True** ✅ | `governance/v2e/kill_switch_qualification.json`, built by `eth_research.v2f.qualification` from 5 executed probes | pre-activation | **impl** | no — this was a real gap | — | **Done.** The latching kill switch was qualified against `eth_research.shadow.kill_switch`: armed permits, tripped blocks, a re-trip neither un-latches nor overwrites the first reason, reset refuses an empty reason, an explicit reset re-arms. | n/a |
| 15 | `monitoring_qualified` | **True** ✅ | `governance/v2e/monitoring_qualification.json`, built from 5 executed probes | pre-activation | **impl** | no — this was a real gap | — | **Done.** Every alert generator qualified at, below and above its boundary, plus a canonical round-trip through the strict parser. | n/a |
| 16 | `sealed_ledgers_intact` | **True** ✅ | `sealed_partitions_untouched` ← all three access ledgers byte-empty | standing | **impl** | no | — | Already satisfied. Must stay true — breaking it is a hard stop, not a step forward. | n/a |
| 17 | `repository_private` | **True** ✅ | `repository_private` gate ← committed visibility record | standing | **owner** | no | — | Already satisfied. Owner restored privacy on 2026-07-28; must not regress. | n/a |

---

## What the table says, in one paragraph

All eleven remaining false values (#1–#9, #12, and #13) are **expected to be false before the
one-shot**. Nine of them are one fact wearing nine names: with no nominated candidate there is no
fingerprint to freeze, no lineage to validate, and no protocol to preregister. Treating those as
nine separate blockers overstates the work by 8. #13 is the owner's activation signature, which is
*supposed* to be absent until the very end.

The two genuinely open implementation items were #14 and #15, and both are now closed. **There is
no remaining implementation-controlled false requirement.** Closing them changed no authorization
outcome — `all_satisfied` is still `False`, the resting state is still `disabled` — which is the
point: they were real safety work, not progress toward activation.

## Consequences by phase

| phase | blocked? | by what |
| --- | --- | --- |
| **E** (source freeze) | not blocked by the matrix | the mixer's semantics must first survive the pre-freeze red team (§4) |
| **R** (registration) | **blocked** | registering the one-shot would commit the budget; §7 says no valid partition |
| **P** (execution) | **blocked** | no lawful partition — the hard blocker, upstream of every eval-dependent row |
| **Q** (verification) | **blocked** | nothing to verify without P |
| **merge** | not blocked | the branch carries no evaluation and no activation |
| **activation** | **blocked** | #1–#9, #12 (eval), #13 (owner). #14–#15 are closed and no longer block. |

## What I am NOT doing, and why

- **Not writing #13.** It is the owner's signature. A gate that the actor can satisfy for itself
  is not a gate.
- **Not writing `paper_release_freeze.json` to flip #5–#9 and #12.** It would not flip them —
  they are `freeze_present AND eligible`, and eligibility is false. Writing the artifact now
  would freeze a release candidate for a candidate that has never been evaluated, which reads as
  progress while being none.
- **Not editing the V2A/V2B results to make #1 true.** Those artifacts record accepted negative
  findings. Editing them to manufacture eligibility would be falsifying results, which is the
  worst thing available to do here.
- **Not writing #14/#15 by hand.** `derive_requirements` satisfies both from a *presence* check,
  so `echo '{}' > …` would have flipped them. The records are instead emitted only by a builder
  that runs the probes and raises rather than writing when any of them misbehaves — proven by
  mutating each mechanism in turn and asserting nothing lands on disk.
