# V2F — HARD STOP

Work halted at `ca534cc` on `claude/v2e-proposal-acceptance-001`. The V2F one-shot was never
created, so it has not been consumed. No selector research began. No paper trading was activated.
All three sealed ledgers remain byte-empty.

This document records why, with the evidence, so the decisions below can be made on facts.

## Why this is a stop and not a to-do list

The V2F directive authorizes continuing autonomously while safe work remains, and enumerates the
conditions that require stopping. Three of them are met simultaneously:

* **a Class A defect** — a paper-activation safety gate reports the permissive answer for a
  condition that is false;
* **Class D governance defects** — the repository's public visibility contradicts its own operative
  distribution policy, and third-party data is being redistributed with no assessment;
* **an unavoidable external human decision** — two of the four blocking items are the owner's to
  make (legal/redistribution, and repository visibility), and one requires repository settings the
  agent cannot change.

Each is stated below with what was verified by execution rather than inferred.

---

## STOP-1 (Class A) — the `repository_private` paper-activation gate is satisfied by a PyPI classifier

`src/eth_research/v2/fable5/paper_readiness.py:149`:

```python
def _repository_private(root: Path) -> bool:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    return "Private :: Do Not Upload" in pyproject.read_text(encoding="utf-8")
```

`"Private :: Do Not Upload"` is a **PyPI trove classifier**. It controls whether the Python Package
Index rejects an upload. It carries no information whatsoever about GitHub repository visibility.

`repository_private` is a member of `PAPER_ACTIVATION_GATES`, and authorization is
`all(gates[g] for g in PAPER_ACTIVATION_GATES)`. Measured at HEAD:

```
repository_private gate = True
actual GitHub visibility = public   (private=false, verified via the GitHub API)
```

So the gate that exists to keep zero-capital paper trading off a public repository **returns True
for a public repository**. Every other activation gate is currently false for unrelated reasons, so
nothing has been activated — but this milestone's entire purpose is to satisfy those other gates.
Had the rest of V2F completed, paper signals and positions would have been published to the world
by a system that believed it was private.

The gate is not merely imprecise; it measures a different thing than its name, its docstring and
every consumer assume. Fixing it is not a one-line edit: the correct replacement depends on
STOP-3, so it is deliberately **not** patched here rather than half-fixed under a guess.

## STOP-2 (Class D) — public redistribution of third-party market data, unassessed

Measured at HEAD:

| measure | value |
| --- | --- |
| committed raw market-data files | 57 |
| approximate third-party OHLCV records committed | 12,167 |
| provider | Coinbase Exchange public market data |
| committed assessment of the provider's redistribution terms | **none** |

Every license artifact in the repository addresses software copyright. None addresses redistributing
a third party's market data. The repository is public, so these records are being served to anyone.

Per the directive: *"Do not fabricate a legal conclusion. Mark uncertainty as requiring human legal
review."* This is marked as exactly that. **A human legal decision is required.** No copies were
added, and no history was rewritten.

## STOP-3 (Class D) — public visibility contradicts the repository's own operative policy

`release/private/v1.1.0/private_distribution_policy.json`, the governing distribution artifact:

```
distribution_classification      = "private"
public_github_release_allowed    = false
public_package_registry_allowed  = false
public_pypi_allowed              = false
license_present                  = false
```

The repository is public, forkable, and ships no LICENSE. Public visibility does not itself grant an
open-source license — third parties have no granted rights to this code, while being able to read
all of it.

Two coherent resolutions exist and **only the owner can choose**:

1. return the repository to private, which restores agreement with the policy; or
2. keep it public and rewrite the distribution policy, which requires the STOP-2 legal answer first
   and a deliberate license decision (which this project has always held as an external human gate).

## STOP-4 (Class D, active and compounding) — a live weekly workflow keeps growing the public dataset

`.github/workflows/m3e-prospective-update.yml` is **enabled**:

```yaml
on:
  schedule:
    - cron: "17 2 * * 1"   # Mondays 02:17 UTC
  workflow_dispatch:
```

Every Monday it fetches Coinbase market data and opens a PR adding more of it. While STOP-2 and
STOP-3 are unresolved, the exposure grows on a schedule without anyone deciding that it should.

This workflow was **not disabled**, because doing so alters governed scheduled behaviour that a
prior milestone deliberately activated, and the right response depends on the owner's answer to
STOP-2/STOP-3. It is flagged here as the most time-sensitive item: it is the only finding that gets
worse on its own.

## STOP-5 — the directed research has no authorized data partition

The directive names exactly one candidate, `adaptive_expert_mixer_v1`, and requires qualifying it on
*genuinely new* research information, forbidding use of the development gate, the final holdout, any
sealed partition, and the accepted/proposed prospective cohort values.

The architecture map found no partition that satisfies all of those constraints: the legacy
partitions are permanently closed to exactly this operation, and the only successor dataset is the
prospective cohort at **12 of 365 rows** with a byte-empty, sealed evaluation ledger.

§6 of the directive anticipates this: *"If no safe/licensed/reproducible data path exists, stop
before registration. Synthetic data may test infrastructure but cannot qualify the strategy."*
Acquiring a new public dataset is possible in principle, but doing so now would commit **more**
third-party data to a public repository whose redistribution position is exactly what STOP-2 says is
undetermined.

---

## Also found, not blocking the stop but requiring fixes

Six read-only specialist agents ran in disposable clones (single-writer rule maintained; the real
tree was never written by an agent). 47 findings; every Class A/B/D finding was then given to an
adversarial verifier instructed to refute it. **10 confirmed, 3 refuted** — the refutations are
recorded, not discarded.

Confirmed, beyond the stop items:

| id | class | finding |
| --- | --- | --- |
| A-01 | A | HEAD ships governance evidence asserting private-repository protection, and the guard meant to catch that drift passes green |
| G-2 | A | The dashboard hardcodes and publishes `Visibility: private / local-only` about a public repository |
| G-3 | A | The mandated V2E rehearsal banner exists only on a code path no operator can reach; the "zero-exposure rehearsal" evidence is produced by tests alone |
| B-A1 | A | `README.md:125` tells every public reader "market data is never committed" while 12,167 records are committed — the first data statement a visitor encounters |
| H3 | A | Stdlib verifier check `09_acceptance_chain` reports **PASSED** after silently skipping its entire git-object binding half when `.git` is absent |
| H1 | B | The suite does not pass at HEAD: 12 failed / 4027 passed / 12 skipped on a fresh clone; CI is red |
| H2 | B | The `m3f-replay` `independent-verifier` job runs a full-history check on a shallow checkout, so it can never pass |
| H4 | D | **No branch is protected, including `main`**; none of the 18 workflows is required for merge (owner-side setting) |
| F-01 | D | The GA-baseline vs growable-cohort collision, independently found and recorded as G-1 in `docs/V2E_BUG_LOG.md` |

H3 deserves emphasis: it is the same defect class this branch has been fixing all along — a check
that reports success for work it did not do.

### What the public-security audit cleared

Not everything was bad, and the good results are load-bearing for any decision to stay public:

* **No real credential anywhere.** Agent A independently re-derived this over **all 2243 blobs** in
  the object database — including 11 unreachable/orphan blobs the primary agent's 2232-blob
  path-reachable scan did not cover — using 38 detector families (GitHub/Slack/Stripe/GCP/exchange
  key prefixes, ETH private keys, mnemonics, JWTs, connection strings, entropy ≥ 4.4). The only
  hits were the four known synthetic fixtures and 316 false positives from float digits matching a
  card pattern.
* **Zero dangerous files** ever committed — no `.env`, key files, databases, dumps, archives or
  caches, across every path in history.
* **All 43 action references pinned to full 40-hex SHAs**; zero unpinned.
* **Zero `secrets.` references** across all 18 workflows — no secret is reachable from any trigger,
  fork or otherwise. No `pull_request_target`, no `workflow_run`, no `id-token`, no cache.

## State at the stop

| item | state |
| --- | --- |
| V2F one-shot | **never created**, therefore not consumed |
| selector research | not begun |
| paper trading | not activated; no paper record exists |
| sealed ledgers | all three byte-empty, tracked, regular files |
| governance flags | all false |
| history | not rewritten; no force-push, no branch deleted, no tag |
| agent writes to the real tree | none — every agent worked in a disposable clone |

## What is needed to resume

1. **Owner/legal:** may this repository publicly redistribute Coinbase market data? (STOP-2)
2. **Owner:** stay public and rewrite the distribution policy, or return to private? (STOP-3)
3. **Owner:** decide the fate of the weekly data-adding workflow in the interim. (STOP-4)
4. **Owner:** enable branch protection on `main` and mark required checks. (H4)

Once 1–3 are answered, the agent-side work is well defined: fix STOP-1 to measure real visibility or
fail closed, correct the false public statements (A-01, G-2, G-3, B-A1), fix the vacuous verifier
check (H3), resolve the twelve failures including the F-01 governance collision, obtain unanimous
auditor acceptance, and only then consider whether a lawful new data path exists for the selector.

## Terminal verdict

`V2F STOPPED — PUBLIC-EXPOSURE, DATA, GOVERNANCE, OR SCIENTIFIC-INTEGRITY HARD STOP; ONE-SHOT NOT EXECUTED; PAPER TRADING BLOCKED; V2 NOT SELL-READY`
