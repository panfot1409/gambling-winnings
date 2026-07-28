# V2 — public-exposure incident record

Opened 2026-07-28. **Append-only**: corrections go in a new dated section, never by
editing an earlier one.

This record states what was **measured**, separated from what is **undecided**. It
deliberately reaches no legal conclusion; see §5.

> Some of the analysis behind this record was produced on the unmerged working branch
> `claude/v2e-proposal-acceptance-001`, which also carries an unaccepted data proposal
> and must not be merged wholesale. This document is written to stand alone: every fact
> below is restated here rather than cited across branches.

---

## 1. Visibility — verified live, twice

Queried against the GitHub REST API, never inferred from a PyPI classifier, package
metadata, a README statement, a committed policy document, a cached audit, or a branch
name:

| observation | `private` | `visibility` | measured |
| --- | --- | --- | --- |
| during the incident | `false` | `public` | 2026-07-28 (V2F-R phase 0) |
| after owner remediation | **`true`** | **`private`** | 2026-07-28T11:33:55Z (V2F-R2 phase 0) |

Constant across both: `allow_forking: true`, `forks_count: 0`, `default_branch: main`,
`created_at: 2026-07-11T00:22:16Z`, `stargazers_count: 1`.

**The repository is private as of this writing.**

*Not established:* **when** it became public. The REST API exposes current visibility,
not visibility history. Only the owner can answer this, from the account security log
(Settings → Security log, filter `repo.access`). Until then the exposure window is
unknown, and this record does not guess at one.

`forks_count: 0` and `stargazers_count: 1` are weak evidence of low reach, and are
recorded as weak: neither counts anonymous clones, and GitHub retains clone traffic for
only 14 days (Insights → Traffic), visible to the owner alone.

### Privacy restoration is not recall

Returning the repository to private **cannot** retrieve anything already taken. It does
not reach:

* clones and mirrors made while it was public;
* forks (none are currently recorded, but a fork made and deleted leaves no count);
* search-engine, proxy or CDN caches;
* screenshots, notes, or copies made by any reader;
* third-party code-indexing and dataset-scraping services.

Anything published while public must be treated as permanently outside the owner's
control. Containment limits *future* exposure only.

## 2. Third-party market data published

Measured by walking the Git index **of this branch** (`security/v2f-private-containment`,
whose `research/` subtree is byte-identical to `main`) and parsing every raw acquisition
file. The ref matters and is stated because these totals differ by ref — see the note
below.

| acquisition | candle rows |
| --- | --- |
| `research/m2b/raw/coinbase/coinbase-eth-usd-001` | 3,702 |
| `research/m2b/raw/coinbase/coinbase-eth-usd-audit-002` | 3,702 |
| `research/v2b/raw/coinbase/coinbase-btc-usd-research-audit-002` | 2,221 |
| `research/v2b/raw/coinbase/coinbase-btc-usd-research-genesis-001` | 2,221 |
| `research/m2b/raw/coinbase/discovery-001` | 257 |
| `research/m3d/raw/coinbase/coinbase-eth-usd-prospective-genesis-001` | 3 |
| `research/m3d/raw/coinbase/coinbase-eth-usd-prospective-audit-002` | 3 |
| **total on `main` / this branch** | **12,109 rows** |

Those rows live in **45 candle-bearing files**, among 54 files total under
`research/**/raw/coinbase/`; the other 9 are acquisition receipts and request plans
carrying no market data.

**Ref-dependence, stated explicitly.** Two unmerged refs — the bot branch
`bot/m3e-prospective-update/20260715-20260724-315846f9ec5196b4` and the working branch
`claude/v2e-proposal-acceptance-001` that merged it — additionally carry a
prospective-update acquisition of **9 candle rows**. That acquisition adds **3 files**,
of which exactly **one** is candle-bearing
(`coinbase-eth-usd-1d-update_0000_20260715_20260724.json`); the other two are an
acquisition plan and a receipt. Those refs therefore carry **12,118 rows in 46
candle-bearing files, of 57 files total**. Both were public while the repository was
public, so the exposed maximum is 12,118 rows even though `main` carries 12,109.

> **Erratum 1, 2026-07-28.** An earlier revision of this section reported "12,118 rows
> across 57 raw JSON files" as the figure for this branch. That total is correct for the
> two unmerged refs above, not for `main` or for the branch carrying this document, and
> the "57 files" count silently included non-candle receipt/plan files. Corrected above.
> Found by an independent read-only auditor re-deriving the figure rather than reading it.

> **Erratum 2, 2026-07-28.** The correction above then repeated the very conflation it
> apologised for. It said the extra rows sat "across 3 files", counting the plan and
> receipt as if they carried market data, and gave no candle-bearing count for those
> refs at all. A second independent auditor caught it; both figures are re-derived above
> by parsing every blob at `779df6bb` rather than by counting filenames. The lesson is
> recorded rather than quietly fixed: a file count and a *data-bearing* file count are
> different numbers, and writing an erratum is not a guarantee of getting it right.

Provider: Coinbase Exchange public market data. Derived datasets, cohort manifests and
proposal bundles carry the same values onward, so the raw candle-row count is a **lower
bound** on what was published. No raw market-data values are reproduced in this record.

## 3. The scheduled collector was live and unattended

`.github/workflows/m3e-prospective-update.yml` ran weekly on `cron: "17 2 * * 1"`.

The last scheduled run — id `30270242877`, 2026-07-27 — is marked `failure` in the
Actions UI. **That marking is misleading.** Job-level results:

| job | conclusion |
| --- | --- |
| `gate_and_plan` (V2D activation gate, offline planning) | success |
| `runner_a` — fetch Coinbase candles | success |
| `runner_b` — fetch Coinbase candles | success |
| `assemble_and_publish` — **push bot branch** | success |
| `open_draft_pr` | **failure** |

So the run fetched third-party market data and **pushed it to a public branch**. Only
the final step — opening the review PR — failed. The consequence is worse than a clean
failure: the data landed, and the human-review notification did not.

### Branches carrying data with no review trail

Inventoried, **not deleted**:

| branch | head | verifiable from |
| --- | --- | --- |
| `bot/m3e-prospective-update/20260715-20260724-315846f9ec5196b4` | `779df6bb` | this repository (the object is present locally) |
| `bot/m3e-prospective-update/20260715-20260727-bf52161f7935a5e2` | `5f924e04` | **GitHub API branch listing only** — the object is not in a local clone unless separately fetched |

Neither has an associated pull request. Both remain in place as evidence. The
provenance column is recorded because the second head cannot be confirmed by
`git cat-file` in a fresh clone; anyone re-deriving this table offline will find only
the first, and that is expected rather than a discrepancy.

## 4. Containment

**Owner actions, verified live from the GitHub API rather than taken on trust:**

| action | verified state | when |
| --- | --- | --- |
| repository returned to private | `private: true` | 2026-07-28T11:33:55Z |
| `M3E Prospective Update` disabled in Actions | `state: "disabled_manually"` | 2026-07-28T11:31:40Z |

No workflow run was queued or in progress at verification time.

**Repository-content containment (this change):**

* `governance/v2f/containment.json` records the suspension, its authority, and what
  lifting it requires.
* The `schedule:` trigger is **removed** from the workflow — not commented out. A
  commented cron is one careless uncomment from resuming.
* `tools/v2f_containment_gate.py` refuses ahead of every network, push and PR step in
  all **five** jobs, so `workflow_dispatch` cannot fetch while containment is active. It
  is stdlib-only so it runs before any environment sync, and **absence of the record
  refuses**: deleting `governance/v2f/containment.json` must not be a way to resume
  egress.
* The gate rule is stated over **every job that checks out the repository**, not over a
  list of the jobs that exist today. A named list is a blacklist: adding `runner_c` with
  a checkout and a fetch would have passed every other check while looking, in a review
  diff, exactly like its gated siblings.
* `tests/test_m3e_workflow_security.py` previously asserted the cron was *present*; it
  now asserts its *absence*, so restoring the schedule cannot pass CI unnoticed.
* The gate itself is also checked for *integrity*, in every job: a step wearing
  `continue-on-error: true`, `if: false`, `|| true`, or a second `--repo-root` is
  present but refuses nothing, and each of those was reproduced passing the earlier
  substring check before this was tightened.

Disabling the workflow in the Actions UI and removing its schedule from the default
branch are **independent** controls, and both are now in force. Either alone would stop
the timer; together, re-enabling requires both a UI action and a reviewed commit.

### Correction: two committed claims about these controls were false

Recorded here because commit messages cannot be rewritten without a history rewrite,
which is not authorized, and because a false security claim left standing is worse than
the defect it describes.

Commit `e111788` said the trigger check was "pinned by **EXACT MATCH** — a whitelist,
not a blacklist", and commit `5a06788` said "step integrity applies to every gate in
every job, including jobs added later". **Neither was true of the code it shipped.**

* The trigger check was `TRIGGER_BLOCK not in directives`. `in` is *substring
  containment*, not equality: appending `schedule:` **after** `workflow_dispatch:` left
  the pinned substring intact and restored a live weekly Coinbase fetch with no
  violation reported. Two independent auditors found this separately.
* "Every job" held only for jobs whose header line ended exactly at the colon and whose
  steps sat at exactly six spaces. A trailing space, a trailing comment, or eight-space
  indentation made a job invisible to every job-level rule while GitHub ran it.

Both are fixed, and the fix is not a better scanner: the whole suspended workflow is now
pinned by SHA-256 in `governance/v2f/containment.json`. The structural checks are
retained as a secondary control and were corrected, but the reason to trust the
suspension is the digest, which has no parser and therefore no blind spot.

The general lesson, stated because it caused both defects: **checking that good text is
present says nothing about whether bad text is also present.** A whitelist has to
compare the whole region, not search it.

### What the refuter changed

Every Class A/B/D finding was handed to a second agent instructed to **refute** it. That pass is
recorded here because it did not merely confirm — it moved two conclusions, and the record would be
misleading without them.

* **The ELOOP finding was overstated, by me.** It was reported as `paper_trading_active` returning
  `false` "while a readable record with real content exists". The refuter swept chain lengths 1–45
  and showed the reader never disagrees with readability *at the governed path*: at the length where
  the check returns false, the record cannot be read through that path either. The realistic version
  of the attack also collapses three other gates and is refused by the inventory's symlink check. The
  reader was still repaired — a function that cannot distinguish "absent" from "could not tell"
  should say so — but it closed a correctness gap, not a live inversion.
* **The EACCES finding was half wrong.** `PermissionError` is an `OSError`, so an unreadable *file*
  already returned `None` as documented. Only an unreadable *parent directory* escaped, and git does
  not track directory permissions, so it cannot arrive through a clone.
* **The parent-directory symlink is real but was already caught** by `fable5 verify`, which runs on
  every push and PR. Fixing the reader is defence in depth, not the only line.

The refuter also found three things the first auditors missed, all now fixed: `_sealed_untouched`
resolved its path outside the `try`, so an unreadable parent raised out of a function contracted to
return a bool; `_path_exists` treated `ENOTDIR` as presence when a regular-file parent means nothing
can be there; and `eligible_candidate_ids: [null]` satisfied a bare length check, flipping three
gates and contradicting this module's own "a null-result candidate is not eligible".

Two documented claims were withdrawn as false rather than defended: the module said its gates derive
from *committed* bytes (nothing consults git — a `.gitignore`d file satisfies a presence gate) and
that no *monkeypatchable* setting could force a result (rebinding `PAPER_ACTIVATION_GATES` or
`ReadinessInputs` does). Both now state the limit instead of the claim.

Not fixed, recorded: `tools/m3f_independent_verify.py:150` has the same final-component-only symlink
pattern. It is outside this containment change and belongs with the governance repair.

### Findings raised against this change and deliberately NOT fixed

Three independent read-only auditors reviewed the containment change in disposable
clones. Every finding acted on below was reproduced first-hand before being fixed. These
are the ones left open — recorded here rather than dropped, because "auditors clean" is
not the same as "findings ignored".

| # | finding | class | disposition |
| --- | --- | --- | --- |
| B‑1 | The visibility record is an **observation with a timestamp**, not a live check. If the repository went public again tomorrow, nothing in the tree would notice and `repository_private` would keep deriving `true` from a stale record. | B | **Open.** Determinism was chosen over freshness: `paper_readiness` derives from committed bytes, offline, and must stay reproducible. The compensating control — a scheduled live re-observation that fails when the API disagrees with the record — is **not built**. Until it is, this gate proves *what was observed*, not *what is true now*. |
| C‑6 | `assemble_and_publish` still declares `contents: write` and `open_draft_pr` still declares `pull-requests: write` while containment is active. | C | **Declined, with reason.** Stripping them would make lifting containment a two-part edit (flip the record *and* restore permissions), so the record's `lift_requires` would no longer describe what lifting actually takes. The generalized rule above is the stronger control: a new job inherits the top-level `contents: read` **and** must gate. |
| D‑2 | `m3f verify_inventory` compares against the M3F freeze commit rather than the live tree, so it cannot detect drift introduced after that freeze. | D | **Open, out of scope here.** Pre-existing and not introduced by containment; belongs to the governance-model repair, not to a change whose whole purpose is to be a minimal, reviewable suspension. |

One further limitation of this branch, found by re-reading its own history rather than
by an auditor: **the commits are not individually self-contained.** The first three leave
`fable5 verify` red, because the governed inventory is rebuilt in a later commit. `main`
never observes that state — the merge takes the branch tip — but the branch is not
bisectable. Fixing it would require rewriting history, which is not authorized.

## 5. Data rights — classified, not concluded

For engineering purposes the owner has classified Coinbase market data as:

    internal_research_only_pending_written_redistribution_permission

This permits no public redistribution, public dashboard, public chart, buyer delivery,
package inclusion, or public research publication.

Two things are deliberately *not* done here:

* **No legal conclusion is invented.** This record does not assert that redistribution
  is permitted, nor that it is prohibited. The question belongs to a human with legal
  advice, and remains open.
* **Availability is not permission.** Coinbase's endpoint being public and
  unauthenticated is not a redistribution licence and is not treated as one.

No `LICENSE` file was added and no licence decision was made on the owner's behalf.
Unresolved redistribution rights block sell-readiness regardless of any later private
paper trading.

## 6. Open items requiring the repository owner

1. **Establish the exposure window** from the account security log (§1).
2. **Obtain the data-rights answer** (§5), with legal advice.
3. **Enable branch protection on `main`**, which was measured `protected: false`, and
   mark required checks.

## 7. What was deliberately not done

| action | status |
| --- | --- |
| history rewritten | no |
| force-push | no |
| branch deleted | no — the two bot branches are inventoried and intact |
| Actions run or artifact deleted | no |
| commit amended, rebased or squashed | no |
| tag created or moved | no |

Removing the published data from history would require a history rewrite. That is
reserved for a separate human authorization informed by legal advice, and is **not**
performed here. Preserving the evidence takes precedence over reducing exposure —
particularly because, per §1, a rewrite could not reach the copies that matter anyway.
