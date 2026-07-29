# V2F item 7 — research-partition verdict

The directive asks for an explicit verdict from a fixed set, bound to actual data paths,
provenance, cutoff, rights classification, non-overlap proof, and the sealed-partition firewall.

---

## VERDICT: `EXTERNAL_RIGHTS_REQUIRED`

Chosen over `NO_VALID_PARTITION` deliberately, and the distinction is not cosmetic.

* Of the partitions that **exist today**, none is lawful and unconsumed. On the existing set alone
  the answer is `NO_VALID_PARTITION`, and that sub-finding is recorded below.
* But a path forward does exist and it has one gating condition: a **third-party market-data
  rights determination**. `research/v2/research_partition_closure.json` states the closure "is
  permanent for the legacy partitions" and that future research "requires a separately-authorized,
  new prospective dataset or domain under its own governance". Acquiring that new dataset is what
  `governance/v2f/containment.json` currently blocks, and it blocks it because the redistribution
  question is open, not because acquisition is forbidden in principle.

`NO_VALID_PARTITION` would say nothing could unlock this. That would be false, and false in the
direction that discourages the one action that would actually help. `EXTERNAL_RIGHTS_REQUIRED`
names the real gate.

Neither reading changes what happens next: **the one-shot is not registered and not spent.**

---

## The bindings the verdict rests on

| requirement | bound to | state |
| --- | --- | --- |
| **data paths** | the five legacy partitions enumerated in `docs/V2F_RESEARCH_PARTITION_DETERMINATION.md` §1–8 | all five disqualified |
| **provenance** | `research/m3d/research_train_exhaustion.json` | `classification: "exhausted_for_new_candidate_research"` |
| **cutoff** | the accepted prospective cohort's `last_open`, verified by `verify_accepted_base` on every dashboard build | immature; `evaluation_authorized` is `false` and the dashboard refuses to build if it is not |
| **rights classification** | `governance/v2f/containment.json` | `active: true`; Coinbase data is `internal_research_only_pending_written_redistribution_permission` |
| **non-overlap proof** | the development gate's fingerprint | byte-identical to the already-consumed `m2b_validation`, aliased in `exhaustion.py` so renaming cannot evade it — it is **not** virgin data |
| **sealed-partition firewall** | `research/m3a/development_gate_access.jsonl` | **0 bytes**, and `fable5 verify` re-checks `sealed_ledgers_byte_empty` on every run |

Two independent closure records agree: the M3D exhaustion decision and
`research/v2/research_partition_closure.json`. The closure forbids `evaluate_new_candidate` and
`recombine_and_claim_new_trial` **by name**, and a mixture over rejected families is precisely the
second one. That is not an interpretation — it is the recorded prohibition matching the recorded
design.

---

## Consequences, applied

Directive item 9 governs: *"If no valid partition: do not register or spend the one-shot; finish
all safe paper-platform, dashboard, recovery, deployment, and security work; then issue the
hard-stop verdict with precise missing evidence."*

- **Not registered, not spent.** `one_shot_spent: false` in both preregistration records.
- Items 8, 10 and 11 are unreachable: there is no E→R→P→Q to run, no rejection to record, and no
  activation to perform. **Paper trading stays disabled** — which is also the correct outcome under
  item 10 regardless.
- The safe work item 9 names has been done: the two implementation-controlled activation
  requirements are closed, the dashboard claim-binding proof is committed, and the candidate's
  semantics were red-teamed and corrected before any freeze.

## The precise missing evidence

1. A completed third-party market-data rights assessment resolving **redistribution** of Coinbase
   data. Until it exists, containment stays active and no new partition can be acquired.
2. A human recording `active: false` with `lifted_by` and `lifted_on` in
   `governance/v2f/containment.json`. The gate refuses on absence, on a bare `active: false`, and
   on an unattributed lift; only a fully attributed lift opens it.
3. Repository privacy verified through the GitHub API **at the time of lift**, not from the
   existing committed observation.
4. A separately-authorized new prospective dataset under its own governance, plus a new single-use
   evaluation ledger.
5. A separate human authorization for the evaluation itself.

Items 1 and 5 are the ones no amount of engineering can produce.
