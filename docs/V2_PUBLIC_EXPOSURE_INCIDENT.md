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

Measured by walking the Git index and parsing every raw acquisition file:

| acquisition | candle rows |
| --- | --- |
| `research/m2b/raw/coinbase/coinbase-eth-usd-001` | 3,702 |
| `research/m2b/raw/coinbase/coinbase-eth-usd-audit-002` | 3,702 |
| `research/v2b/raw/coinbase/coinbase-btc-usd-research-audit-002` | 2,221 |
| `research/v2b/raw/coinbase/coinbase-btc-usd-research-genesis-001` | 2,221 |
| `research/m2b/raw/coinbase/discovery-001` | 257 |
| `research/m3d/raw/coinbase/…prospective-update-20260715-20260723-…` | 9 |
| `research/m3d/raw/coinbase/coinbase-eth-usd-prospective-genesis-001` | 3 |
| `research/m3d/raw/coinbase/coinbase-eth-usd-prospective-audit-002` | 3 |
| **total** | **12,118 rows across 57 raw JSON files** |

Provider: Coinbase Exchange public market data. Derived datasets, cohort manifests and
proposal bundles carry the same values onward, so 12,118 raw candle rows is a **lower
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

| branch | head |
| --- | --- |
| `bot/m3e-prospective-update/20260715-20260724-315846f9ec5196b4` | `779df6bb` |
| `bot/m3e-prospective-update/20260715-20260727-bf52161f7935a5e2` | `5f924e04` |

Neither has an associated pull request. Both remain in place as evidence.

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
* `tools/v2f_containment_gate.py` refuses ahead of every network step in all four jobs,
  so `workflow_dispatch` cannot fetch while containment is active. It is stdlib-only so
  it runs before any environment sync, and **absence of the record refuses**: deleting
  `governance/v2f/containment.json` must not be a way to resume egress.
* `tests/test_m3e_workflow_security.py` previously asserted the cron was *present*; it
  now asserts its *absence*, so restoring the schedule cannot pass CI unnoticed.

Disabling the workflow in the Actions UI and removing its schedule from the default
branch are **independent** controls, and both are now in force. Either alone would stop
the timer; together, re-enabling requires both a UI action and a reviewed commit.

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
