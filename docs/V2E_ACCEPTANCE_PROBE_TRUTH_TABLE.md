# V2E acceptance-layer probe truth table

Head under test: `ecfa8e7607c9fd093ce9da2c4e78a82f9c9d41c0`. Machine-readable evidence: [`V2E_ACCEPTANCE_PROBE_TRUTH_TABLE.json`](V2E_ACCEPTANCE_PROBE_TRUTH_TABLE.json).

## What this is, and what it replaces

The earlier Auditor B 41-probe matrix was never persisted as machine-readable evidence,
so nothing here cites it. Every row below was re-measured against the head named above,
and this table supersedes any earlier probe count.

Four readers run on every probe:

| reader | entry point | independence |
| --- | --- | --- |
| `production` | `verify_acceptance_program` (library call) | the writer's own verifier |
| `public entry` | `python -m eth_research.m3e.acceptance check` | the CLI a reviewer runs |
| `M3F` | `python -m eth_research.m3f.audit` | isolated package; re-implements what it checks |
| `stdlib` | `tools/m3f_independent_verify.py` | imports no `eth_research` module at all |

These are **enforcement paths, not independent trust anchors**: all four read the same
repository and the same git objects. Running four separately written implementations
improves implementation coverage — a wrong regex or a mis-ordered digest in one shows up
as disagreement with the others — but it creates no external trust.

## Method

Each probe runs in its own disposable clone; the real worktree is never mutated. Every
attack gets the **maximal attacker**: the mutation is committed first, so the file-set
policy's clean-tree precheck cannot shadow the invariant under test, and so the attacker
has the repository write access a real one would. Then every seal the attacker can reach
is regenerated with the project's own primitives — record pins, the file-set binding, both
self-hashes, the registry hash chain, the recovery capsule and drill, and the Fable 5
governed surface — and the reseal is committed too. A refusal is therefore a *semantic*
refusal and never a digest someone forgot to refresh.

Two surfaces are deliberately **not** resealed. The M3F freeze-catalog pins are the
append-only historical baseline that the growth proof is anchored to, not a seal the
attacker gets for free — refreshing them is itself an attack, probed as `GOV-01`. And the
M3F registration builder cannot run at this state at all: it reads blobs from source-freeze
commit `b7d24e82`, which predates the growable cohort update.

A probe counts as **caught** only when the mutation is confirmed by git, a valid control
passes, a reader refuses, *and* the refusal names the intended guard. A refusal by some
other guard is recorded as `REFUSED_BY_ANOTHER_GUARD` — it is still a refusal, but it is
not evidence about the invariant the probe was aimed at.

## Controls

Every control must be accepted by all four readers, or no attack row means anything.

| control | what it establishes | production | public entry | M3F | stdlib |
| --- | --- | --- | --- | --- | --- |
| `CTRL-01` | no mutation at all | accept | accept | accept | accept |
| `CTRL-02` | lawful identity reseal: recompute every pin, the file-set binding, both self-hashes and the registry chain | accept | accept | accept | accept |
| `CTRL-03` | lawful accepted-growth fixture (M3F growable suite) | accept | accept | accept | accept |
| `CTRL-04` | lawful current proposal re-proves end to end | accept | accept | accept | accept |
| `CTRL-05` | lawful current accepted state loads and reconciles | accept | accept | accept | accept |

All 5 controls passed on all four readers. `CTRL-02` is the important one:
re-deriving every pin, the binding, both self-hashes and the chain reproduces the committed
bytes **exactly** (`files_changed: 0`), so the reseal machinery adds nothing of its own to
the attack rows.

## Attacks

| probe | mutation | changed | intended invariant | production | public entry | M3F | stdlib | guard reached | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ROOT-01` | repoint TRUSTED_BASELINE_TREE at the proposal's own tree | 6f +8/-8 | ROOT-01 | refuse | refuse | refuse | refuse | yes | caught |
| `ROOT-02` | maximal re-root: rewrite BOTH authority tables, the registry genesis root, and every downstream seal | 6f +10/-8 | ROOT-03 | refuse | refuse | accept | accept | yes | caught |
| `ROOT-03` | rewrite an authority table and repoint its pinned digest in committed source | 6f +8/-7 | ROOT-02 | refuse | refuse | refuse | refuse | yes | caught |
| `ROOT-04` | swap TRUSTED_BASELINE_COMMIT for the proposal head | 3f +3/-3 | ROOT-01 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-01` | repoint proposal_head_commit at an unrelated real commit | 7f +12/-12 | BIND-01 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-02` | uppercase the pinned commit id | 7f +12/-12 | GIT-01 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-03` | abbreviate the pinned commit id to 8 hex | 7f +13/-13 | GIT-01 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-04` | append revision syntax (^0) to the pinned commit id | 7f +13/-13 | GIT-01 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-05` | truncate history with a .git/shallow marker | 0f +0/-0 | GIT-05 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-06` | fabricate parentage with .git/info/grafts | 0f +0/-0 | GIT-05 | refuse | refuse | refuse | refuse | yes | caught |
| `GIT-07` | substitute the pinned commit via refs/replace | 0f +0/-0 | GIT-05 | refuse | refuse | refuse | refuse | no | refused by another guard |
| `GIT-08` | swap parent and child so the proposal precedes its baseline | 7f +13/-13 | GIT-04/PROV-01 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-01` | commit a smuggled member into the m3d bundle and pin it | 6f +18/-12 | FILE-01/FILE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-02` | omit a legal member from the pinned set | 5f +9/-11 | FILE-01/FILE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-03` | swap the raw and governance role digests in the binding | 7f +13/-13 | FILE-02 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-04` | widen allowed_member_count from 19 to 25 | 7f +12/-12 | FILE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-05` | add an unknown field to the file-set binding | 7f +13/-12 | FILE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `FILE-06` | smuggle an unpinned file into the accepted proposal directory | 5f +15/-9 | FILE-04 | refuse | refuse | refuse | refuse | yes | caught |
| `CHAIN-01` | delete the registry genesis line | 5f +9/-10 | CHAIN-01 | refuse | refuse | refuse | refuse | yes | caught |
| `CHAIN-02` | reverse the registry line order | 5f +9/-9 | CHAIN-01/CHAIN-03 | refuse | refuse | refuse | refuse | yes | caught |
| `CHAIN-03` | duplicate the final registry line | 5f +10/-9 | CHAIN-03 | refuse | refuse | refuse | refuse | yes | caught |
| `CHAIN-04` | append a correctly re-chained SECOND acceptance of the same proposal | 5f +10/-9 | CHAIN-03 | refuse | refuse | refuse | refuse | yes | caught |
| `CHAIN-05` | re-chain the registry from an attacker-chosen seed | 5f +9/-9 | CHAIN-01 | refuse | refuse | refuse | refuse | yes | caught |
| `DATA-01` | relabel prior 3->1 and new 12->10, keeping both the row arithmetic and the day span consistent | 7f +14/-14 | DATA-03 | refuse | refuse | accept | accept | yes | caught |
| `DATA-01b` | the louder relabel: prior 3->1 AND appended 9->11 | 7f +18/-18 | DATA-02 | refuse | refuse | refuse | refuse | yes | caught |
| `DATA-02` | delete a settled row from the cohort and reseal | 8f +16/-17 | DATA-03 | refuse | refuse | refuse | accept | yes | caught |
| `DATA-03` | change a prior row while claiming prior_rows_changed == 0 | 8f +16/-16 | DATA-03 | refuse | refuse | refuse | accept | yes | caught |
| `DATA-04` | claim 40 rows in a 9-day append window | 7f +16/-16 | DATA-01 | refuse | refuse | refuse | refuse | yes | caught |
| `DATA-05` | attest two runners with divergent raw payload digests | 7f +15/-15 | DATA-04 | refuse | refuse | refuse | refuse | yes | caught |
| `DATA-06` | delete pinned created evidence and drop its pin | 3f +7/-13 | DATA-05/STATE-02 | refuse | refuse | refuse | refuse | yes | caught |
| `STATE-01` | empty the new_accepted.state map so it asserts nothing | 5f +10/-18 | STATE-01 | refuse | refuse | refuse | refuse | yes | caught |
| `STATE-02` | drop one of the six transitioned state paths | 5f +9/-11 | STATE-01 | refuse | refuse | refuse | refuse | yes | caught |
| `SAFE-01` | write a line into a sealed evaluation ledger | 2f +5/-4 | SAFE-01 | refuse | refuse | refuse | refuse | yes | caught |
| `SAFE-02` | flip governance flag strategy_evaluated to true | 7f +16/-16 | SAFE-02 | refuse | refuse | refuse | refuse | yes | caught |
| `SAFE-03` | delete the money_moved governance flag key | 7f +15/-16 | SAFE-02 | refuse | refuse | refuse | refuse | yes | caught |
| `SAFE-04` | set evaluation_authorized to true | 7f +16/-16 | SAFE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `SAFE-05` | claim maturity_state=mature with row_count 400 | 7f +17/-17 | SAFE-03 | refuse | refuse | refuse | refuse | yes | caught |
| `PROV-01` | rewrite the proposal manifest on disk and repin it | 8f +15/-14 | PROV-01 | refuse | refuse | refuse | refuse | yes | caught |
| `PROV-02` | backdate acceptance_time inside the append window | 7f +15/-15 | PROV-02 | refuse | refuse | refuse | refuse | yes | caught |
| `PROV-03` | name a publication commit that does not exist | 5f +7/-7 | PROV-03 | refuse | refuse | refuse | refuse | yes | caught |
| `PROV-04` | create a second production proposal no acceptance covers | 5f +12/-6 | PROV-04 | refuse | refuse | accept | accept | yes | caught |
| `GOV-01` | refresh the frozen catalog's pins to today's bytes, erasing the append-only baseline | 3f +14/-8 | M3F-CATALOG (outside the acceptance invariant catalog) | accept | accept | refuse | refuse | yes | caught |
| `GOV-02` | edit research/m3e/accepted_base.json and repin it everywhere | 8f +16/-15 | DATA-03 | refuse | refuse | accept | accept | yes | caught |

**42 of 43 attacks caught by the intended guard; 1 refused by a different guard; 0 accepted by all four readers.**

### Refused, but not by the guard under test

* **`GIT-07`** — expected wording `GEN-04`; actually refused with: eth_research.m3e.acceptance.AcceptanceError: proposal_head_commit 779df6bb6c7a… is not an ancestor of HEAD

`GIT-07` is the interesting one. A `refs/replace` entry substituting the pinned commit
is refused by all four readers, but not by GEN-04, the check written for exactly this
attack: the earlier ancestry check in `A06` resolves the replaced object and fails
first, so GEN-04 never runs. That is a defence-ordering observation, not a hole — the
attack is still refused everywhere, and GEN-04 is probed directly in
`tests/test_m3e_commit_genealogy.py`.

## Where the four readers disagree

Disagreement is the finding. These rows are recorded as measured, not smoothed over.

| probe | production | M3F | stdlib | what the gap means |
| --- | --- | --- | --- | --- |
| `ROOT-02` | refuse | accept | accept | the maximal re-root — rewriting both authority tables plus the registry's genesis root — is caught only by the production path's working-tree-vs-history cache check. Neither shadow path re-derives that comparison. |
| `DATA-01` | refuse | accept | accept | an arithmetically consistent relabel of the prior row count is caught only by production, which re-measures the cohort. This is invariant DATA-03, the one the catalog already records as production-only. |
| `DATA-02` | refuse | refuse | accept | deleting a settled cohort row is caught by production and M3F but not by the stdlib reader, which checks the record's own counters rather than re-measuring. |
| `DATA-03` | refuse | refuse | accept | same gap as DATA-02: the stdlib reader cannot re-measure the prior-row prefix. |
| `PROV-04` | refuse | accept | accept | an uncovered second proposal is caught only by production; neither shadow path enumerates production proposals to check acceptance coverage. |
| `GOV-01` | accept | refuse | refuse | erasing the frozen catalog's append-only baseline is an M3F-layer concern; the acceptance verifier does not read that artifact, so production accepting it is by design rather than a miss. |
| `GOV-02` | refuse | accept | accept | editing the accepted base and repinning it is caught only by production. |

No attack in this table was accepted by all four readers.

## Guard deletion

A probe that is refused proves nothing about a particular guard unless removing that guard
changes the answer. Each deletion below reproduces its probe in a fresh clone, removes
exactly one guard, rebuilds the recovery capsule (a source edit staleness that would
otherwise masquerade as a catch), and re-runs the readers.

| deletion | guard removed | probe | owning reader | reader after deletion | verdict |
| --- | --- | --- | --- | --- | --- |
| `D-BIND` | `acceptance.py` (11 lines) | `GIT-01` | production | accepts | **load-bearing** |
| `D-A08` | `acceptance.py` (6 lines) | `FILE-04` | production | accepts | **load-bearing** |
| `D-A08b` | `acceptance.py` (6 lines) | `FILE-01` | production | still refuses | not the catcher |
| `D-A09` | `acceptance.py` (5 lines) | `GIT-06` | production | still refuses | not the catcher |
| `D-M3F-FILESET` | `growable.py` (1 lines) | `FILE-04` | m3f | accepts | **load-bearing** |
| `D-M3F-PROV` | `growable.py` (1 lines) | `PROV-01` | m3f | accepts | **load-bearing** |
| `D-M3F-SPAN` | `growable.py` (1 lines) | `DATA-01b` | m3f | accepts | **load-bearing** |
| `D-M3F-FLAGKEYS` | `growable.py` (1 lines) | `SAFE-03` | m3f | accepts | **load-bearing** |
| `D-M3F-ROOT` | `growable.py` (1 lines) | `ROOT-01` | m3f | accepts | **load-bearing** |
| `D-STD-FILESET` | `m3f_independent_verify.py` (1 lines) | `FILE-04` | stdlib | accepts | **load-bearing** |
| `D-STD-PROV` | `m3f_independent_verify.py` (1 lines) | `PROV-01` | stdlib | accepts | **load-bearing** |
| `D-STD-ROOT` | `m3f_independent_verify.py` (1 lines) | `ROOT-01` | stdlib | accepts | **load-bearing** |

10 of 12 deletions flip their reader from refusing to accepting, so
those guards are what actually catch. The two that do not are honest defence-in-depth, and
the check that fires instead is named rather than left implicit:

* **`D-A08b`** (`FILE-01`) — still refused by: eth_research.m3e.acceptance.AcceptanceError: acceptance record 20260715-20260724-315846f9ec5196b4: self-hash does not match its content
* **`D-A09`** (`GIT-06`) — still refused by: eth_research.m3e.acceptance.AcceptanceError: acceptance 20260715-20260724-315846f9ec5196b4: file-set binding does not re-derive: parent_commit ba2dcc1d63f2 is not an ancestor of head_commit 779df6bb6c

## Limits of this evidence

* Every row is a **data-plane** attack: committed artifacts and committed source are
  rewritten, but trusted history is not. An attacker who can rewrite history, the verifier
  source, the freeze authority and the review controls together is outside what any row
  here measures.
* Four readers is implementation diversity, not four trust anchors. All four read the same
  repository.
* The table is a snapshot at one commit. It is regenerated, not edited, when the acceptance
  layer changes.
