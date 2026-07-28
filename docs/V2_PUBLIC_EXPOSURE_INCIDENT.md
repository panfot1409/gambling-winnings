# V2 — public-exposure incident record

Opened 2026-07-28 under MILESTONE V2F-R. Append-only: corrections go in a new
dated section, never by editing an earlier one.

This record states what was **measured**, separated from what is **undecided**. It
deliberately reaches no legal conclusion; see §5.

---

## 1. Visibility — verified live, not inferred

Queried against the GitHub REST API on 2026-07-28, per the V2F-R Phase 0 rule that
visibility must never be inferred from a PyPI classifier, package metadata, a README
statement, a committed policy document, a cached earlier audit, or a branch name:

| field | value |
| --- | --- |
| `private` | `false` |
| `visibility` | `"public"` |
| `allow_forking` | `true` |
| `forks_count` | `0` |
| `stargazers_count` | `1` |
| `default_branch` | `main` |
| `created_at` | `2026-07-11T00:22:16Z` |

**The repository is public as of this writing.**

*Not established:* **when** it became public. The REST API exposes current visibility,
not visibility history. Only the owner can answer this, from the account security log
(Settings → Security log, filtering `repo.access`). Until then, the exposure window is
unknown, and this record does not guess at one. The window matters, because it bounds
who could have cloned or forked the repository while it was open.

`forks_count: 0` and `stargazers_count: 1` are weak evidence of low reach, and are
recorded as weak: neither counts anonymous clones, and GitHub does not expose clone
traffic for a window this far back to anyone but the owner (Insights → Traffic, 14-day
retention).

## 2. Third-party market data published

Measured at `6fdb6d1` by walking the Git index and parsing every raw acquisition file:

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
proposal bundles carry the same values onward; the 12,118 figure counts raw candle rows
only and is therefore a **lower bound** on what is published.

> **Erratum to `docs/V2F_HARD_STOP.md` §STOP-2.** That document reported "approximately
> 12,167" records. The exact re-derived count of raw candle rows is **12,118**. The
> earlier figure was approximate and slightly high; the conclusion it supported is
> unchanged. Recorded here rather than by editing the hard-stop document, which is
> append-only.

## 3. The scheduled collector was live and unattended

`.github/workflows/m3e-prospective-update.yml` ran weekly on `cron: "17 2 * * 1"`.

The most recent scheduled run — id `30270242877`, 2026-07-27 — is marked `failure` in
the Actions UI. **That marking is misleading and was initially misread.** Job-level
results:

| job | conclusion |
| --- | --- |
| `gate_and_plan` (V2D activation gate, offline planning) | success |
| `runner_a` — fetch Coinbase candles | success |
| `runner_b` — fetch Coinbase candles | success |
| `assemble_and_publish` — **push bot branch** | success |
| `open_draft_pr` | **failure** |

So the run fetched third-party market data and **pushed it to a public branch**. Only
the final step — opening the review PR — failed. The consequence is worse than a clean
failure would have been: the data landed, and the human-review notification did not.

> **Erratum to `docs/V2F_HARD_STOP.md` §STOP-4.** That document described the workflow
> as one that "fetches Coinbase market data and opens a PR adding more of it". The
> second half has not been true since at least 2026-07-24: it fetches and pushes, and
> the PR step fails. The finding was correct and the mechanism was, if anything, less
> supervised than described.

### Branches carrying data with no review trail

Inventoried, **not deleted**, per authoritative decision 5:

| branch | head |
| --- | --- |
| `bot/m3e-prospective-update/20260715-20260724-315846f9ec5196b4` | `779df6bb` |
| `bot/m3e-prospective-update/20260715-20260727-bf52161f7935a5e2` | `5f924e04` |

Neither has an associated pull request. Both remain in place as evidence.

## 4. Containment applied 2026-07-28

Under authoritative decision 4 — *"Immediately suspend the scheduled Coinbase
prospective-update workflow while containment and rights review are underway."*

* `governance/v2f/containment.json` records the suspension, its authority, and what
  lifting it requires.
* The `schedule:` trigger is **removed** from the workflow — not commented out. A
  commented cron is one careless uncomment from resuming.
* `tools/v2f_containment_gate.py` refuses ahead of every network step in all four jobs,
  so `workflow_dispatch:` cannot fetch while containment is active. It is stdlib-only so
  it runs before any environment sync, and **absence of the record refuses**: deleting
  `governance/v2f/containment.json` must not be a way to resume egress.
* `tests/test_m3e_workflow_security.py` previously asserted the cron was *present*. It
  now asserts its *absence*, so restoring the schedule cannot pass CI unnoticed.

**Known limitation, stated plainly.** GitHub evaluates `schedule:` only from the default
branch. This change lives on `claude/v2e-proposal-acceptance-001`. **Until it reaches
`main`, the weekly trigger is still armed there.** Next fire: Monday 2026-08-03 02:17
UTC. Containment is not in force until that merge happens — see §6.

## 5. Data rights — undecided, and not decidable here

No committed artifact assesses whether this repository may redistribute Coinbase market
data. Every licence artifact in the tree addresses software copyright; none addresses a
third party's market data.

Per authoritative decision 3, redistribution stays blocked unless written permission or
a clearly applicable redistribution licence has been **independently verified**. That
verification has not occurred.

Two things are deliberately *not* done here:

* **No legal conclusion is invented.** This record does not assert that redistribution
  is permitted, nor that it is prohibited. It asserts only that the question is open and
  belongs to a human with legal advice.
* **Availability is not permission.** Coinbase's endpoint being public and unauthenticated
  is not a redistribution licence, and is not treated as one.

No `LICENSE` file was added, and no licence decision was made on the owner's behalf.

## 6. Open items requiring the repository owner

Ordered by time-sensitivity.

1. **Land containment on `main`.** The change above is inert until then. This is the only
   item with a deadline: 2026-08-03 02:17 UTC.
2. **Return the repository to private** (decision 2). No API control available to this
   session can change repository visibility; it is Settings → General → Danger Zone →
   Change visibility → Make private. Verify afterwards that the API reports
   `"private": true` — do not accept the UI banner as proof.
3. **Establish the exposure window** from the account security log (§1).
4. **Obtain the data-rights answer** (§5), with legal advice.
5. **Enable branch protection on `main`**, which is currently `protected: false`, and mark
   required checks (carried finding H4).

## 7. What was deliberately not done

Per authoritative decision 5 — *"Do not rewrite Git history, delete branches, delete
Actions artifacts, purge evidence, or force-push merely to conceal the incident."*

| action | status |
| --- | --- |
| history rewritten | no |
| force-push | no |
| branch deleted | no — the two bot branches are inventoried and intact |
| Actions run or artifact deleted | no |
| commit amended, rebased or squashed | no |
| tag created or moved | no |

Removing the published data from history would require a history rewrite. That is
explicitly reserved for a separate human authorization informed by legal advice, and is
**not** performed here. Preserving the evidence takes precedence over reducing exposure,
because the exposure is already recorded in clones and forks that a rewrite could not
reach anyway.
