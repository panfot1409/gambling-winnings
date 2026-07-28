# V2F — error-correction log

Append-only. One record per defect, in the order it was closed. Corrections to a record go
in a new dated entry, never by editing an earlier one.

Every record states the **intended guard** — the exact production check that should reject
the attack — because "some nonzero exit occurred" is not a catch. Every record states the
**mutation proof**: the new regression must fail when the new guard is neutralized, or the
assertion is vacuous and the record is worthless.

Records deliberately contain no secrets and no raw market-data values.

---

## Standing corrections carried in from the `fb06d6b` refuter pass

These are withdrawn claims. They must not be resurrected in later documentation.

| # | withdrawn claim | what is actually true |
| --- | --- | --- |
| 1 | The ELOOP defect was a live authorization inversion. | It was a **correctness gap**. A refuter swept symlink-chain lengths 1–45 and showed the reader never disagreed with readability *at the governed path*; the realistic attack collapses three other gates and is refused by the inventory's symlink check. The `os.lstat` repair stands on its own merits. |
| 2 | EACCES escaped the reader and raised. | `PermissionError` **is** an `OSError`, so an unreadable *file* already returned `None` as documented. Only an unreadable *parent directory* escaped, and only because path resolution sat outside the exception boundary. |
| 3 | Gates derive from *committed* bytes. | Nothing in `paper_readiness` consults git. A `.gitignore`d, never-committed file that `git status` does not show satisfies a presence gate. What binds artifacts to the repository is the governed inventory and source freeze, not that module. |
| 4 | No monkeypatchable setting can force a result. | Python module globals are rebindable by in-process code. Rebinding `PAPER_ACTIVATION_GATES` or `ReadinessInputs` does move results. That threat is addressed by source freeze, package verification and deployment isolation — not by anything the module can assert about itself. |
| 5 | Lexical symlink checks eliminate the race. | They do not. `resolve()`-then-`read()` is not atomic. Per-component checks reduce the reachable surface; they do not close TOCTOU. |

---

## V2F-EC-001 — paper activation authorized vacuously over an empty gate collection

| field | value |
| --- | --- |
| **Class** | B — governance / authorization integrity |
| **Reported by** | primary writer, during Section 4 item 10 audit |
| **Refuted by** | prior refuter pass established the *reachability* limit (see below) |
| **Pre-fix SHA** | `220ff47a5a7edb2199bd31650e743ecdeffc54fe` |
| **File** | `src/eth_research/v2/fable5/paper_readiness.py:385` (pre-fix) |
| **Fix commit** | this commit |

### Observation

    authorized = all(gates[g] for g in PAPER_ACTIVATION_GATES)

`all(())` is `True`. The gate *collection* was the authority, and the collection is a
rebindable module-level name.

### Reproduction (executed, literal output)

```
=== CEL-03 passing control (honest derivation) ===
  authorized     : False (want False)
  blocking count : 6 (want 6)
=== CEL-02 reproduce: rebind gate collection to empty ===
  authorized     : True   <-- vacuous all(())
  blocking_gates : ()
  gates still show honest values: {'platform_audit_complete': True, ...}
```

The state is **self-inconsistent**: it authorizes while its own gate vector reports unmet
gates, and reports nothing blocking. That is the shape of defect that reads as fine.

### Passing control

`_authorized(dict.fromkeys(REQUIRED_PAPER_ACTIVATION_GATES, True)) is True`, and the real
repository still derives `paper_activation_authorized = False` with six named blockers.

### Intended guard

None existed — that is the defect. There was no check that the reduced-over collection was
the collection the module actually requires.

### Repair

`REQUIRED_PAPER_ACTIVATION_GATES: frozenset[str]` becomes the authority. `_authorized()`
refuses on any of four independent conditions:

1. the requirement itself is empty — an empty requirement authorizes nothing;
2. the delivered key set is not **exactly** the required set (missing *or* extra);
3. the ordering tuple has drifted from the required set;
4. any value is not the `True` singleton (`is True`, so `1`, `"yes"` and truthy objects fail).

`PAPER_ACTIVATION_GATES` is retained solely to give `blocking_gates` a stable order, and
condition 3 stops the two from silently describing different questions.

### Mutation proof (executed)

Guard neutralized in a scratch overlay by reverting the call site to the vacuous form:

```
mutant applied: _authorized() -> vacuous all()
FAILED tests/test_v2f_activation_gate_mapping.py::test_an_empty_ordering_tuple_cannot_authorize
E  assert True is False
E   ... paper_activation_authorized=True, blocking_gates=()
1 failed, 44 passed
```

The regression fails for exactly the intended reason.

**Honest limitation of that proof:** only *one* of the 45 tests broke, because the other 44
call `_authorized()` directly and the mutant reverted only the call site. The unit tests of
the helper and the single integration test of the wiring are both needed; neither alone
proves the other.

### Scope — what this does NOT fix

An attacker who can rebind `PAPER_ACTIVATION_GATES` can rebind `_authorized` itself. This is
not a defence against arbitrary in-process code execution and is not claimed to be. It
removes a failure mode reachable by replacing one innocuous-looking constant — the kind of
change that survives review — and it makes authorization and `blocking_gates` provably
describe the same set.

### Neutrality

No scientific or financial artifact changed. The derived state for the real repository is
byte-identical before and after: `authorized=False`, `trading_active=False`,
`sell_ready=False`, same six blocking gates. Governed inventory and source freeze rebuilt;
`fable5 verify` (13 checks) and `freeze-verify` (4 checks) both `ok: true`.
