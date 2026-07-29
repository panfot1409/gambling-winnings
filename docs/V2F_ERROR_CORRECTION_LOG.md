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
| 6 | The mutual hash pinning in `containment.json` binds a forged containment lift. | It detects **drift**, not **forgery**. Executed 2026-07-29 in a disposable clone: forge `active:false` + `lifted_by` + `lifted_on`, and `fable5 verify` does object (byte drift + `surface_digest drift`) — but `fable5 build --write` then `freeze-build --write`, two committed and legitimate commands, make **both** verifiers report `ok: true` over the forgery, and all 34 `test_v2f_containment_mutations.py` tests pass against the laundered tree. What actually catches it is hard-coded live-state assertions (5 failures across `test_v2f_containment_gate.py` and `test_v2f_research_partition_determination.py`, both CI-enforced). Found by an independent refuter; reproduced before recording. `containment.json` now carries a `mutual_pinning_limitation` field stating this. |

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

---

## V2F-EC-002 — the independent verifier confined only the final path component

| field | value |
| --- | --- |
| **Class** | B — security / provenance integrity (defence-in-depth, not a live authorization bypass) |
| **Reported by** | independent read-only governance captain, recursive audit at pinned `220ff47a` |
| **Refuted by** | its refuter narrowed the claim; I reproduced both parts before acting |
| **File** | `tools/m3f_independent_verify.py` — `_read_bytes` and `_v2d_anchor_active` |
| **Directive link** | §3 item 10: *"Audit `tools/m3f_independent_verify.py` for final-component-only symlink behavior."* Confirmed. |

### Observation

Two reads, two different gaps, one root cause — confinement that did not walk every component.

    # _read_bytes
    path = root / relpath
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_relative_to(root.resolve()):
        raise IndependentVerifyError(...)

`Path.is_symlink()` tests the **final component only**. The companion resolved-inside-root check
did catch symlinks pointing *outside* the repository, so the surviving hole was narrow and easy
to miss: an **intermediate directory symlink whose target is inside the root** passed silently.

`_v2d_anchor_active` was worse — it never called `_read_bytes`, so it had **neither** guard.

### Reproduction (executed, literal output)

```
control (no symlink)      : {"v": "REAL"}
final-component symlink   : REFUSED -> IndependentVerifyError
F1 intermediate (in-root) : *** ACCEPTED ***  read: {"v": "SHADOW"}
```

For the anchor, the diagnostic is the error *category*, not its presence:

```
F2 error: IndependentVerifyError -> v2d anchor kind/schema is unexpected
```

A complaint about the outside file's **contents** is itself the proof that no path guard ran —
the tool had already read bytes from outside the repository root and gotten as far as validating
them.

### Why the anchor read is the more serious of the two

An active V2D anchor is a **relaxation**, not a restriction. It disables the zero-proposal check,
whitelists `m3e-prospective-update.yml`'s write permission, and loosens the freeze-catalog check
from exact-hash to append-only. A read that decides three relaxations must be the most confined
read in the tool; it was the least.

### Intended guard

`eth_research.m3f.validation.safe_repo_path`, which walks every component. Against the same
fixture it refused where the tool accepted — and the tool's own module docstring says *"If the
two verifiers ever disagree, that disagreement is itself the finding."* The independent backstop
was strictly weaker than the thing it backstops.

### Repair

One `_confined_path(root, relpath)` helper, used by both call sites: rejects absolute paths and
`""` / `.` / `..` components, walks **every** component checking `is_symlink()`, then confirms
the resolved path stays inside the root. Reimplemented in stdlib rather than importing
`safe_repo_path` — importing it would make a common-mode defect invisible, which is the entire
reason this tool exists. The cost of reimplementing is drift, and a parity test pays it.

### Mutation proof (executed)

Mutant A — revert `_read_bytes` to final-component-only:

```
FAILED test_a_final_component_symlink_is_refused
FAILED test_an_intermediate_directory_symlink_inside_the_root_is_refused
FAILED test_traversal_shaped_relpaths_are_refused[parent-mid]
FAILED test_traversal_shaped_relpaths_are_refused[dot-mid]
FAILED test_traversal_shaped_relpaths_are_refused[empty]
FAILED test_the_two_verifiers_agree_on_every_attack[intermediate-symlink-in-root]
FAILED test_the_whole_tool_refuses_a_repository_with_a_redirected_governed_directory
```

Mutant B — revert `_v2d_anchor_active` to its own unconfined read:

```
FAILED test_the_anchor_directory_cannot_be_a_symlink_out_of_the_repository
FAILED test_the_anchor_file_itself_cannot_be_a_symlink
E  Expected regex: 'symlink component'
E  Actual message: 'v2d anchor is not a regular file'
```

**Honest reading of Mutant A:** 6 of those 7 are genuine behaviour regressions — the pre-fix code
*accepted* those inputs. `test_a_final_component_symlink_is_refused` is not: the old code did
refuse that one, with different wording, so it fails on the asserted *reason* rather than on
behaviour. Counting it as a caught bypass would overstate the proof.

### Scope — what this does NOT fix

Not a live authorization bypass. Nothing in `paper_readiness` consults this tool, and the Fable 5
inventory's `_iter_files` independently refuses the same construction — so the M3F attestation was
still protected, by the *packaged* verifier, which is exactly the code path the independent tool
exists not to depend on. What was lost was the tool's stated independence guarantee, and that is
what is restored. Per standing correction 5, per-component checks still do not close TOCTOU.

### Neutrality

No scientific or financial artifact changed. `tools/m3f_independent_verify.py --repo-root .` →
`OK: 8 checks, 0 failures` before and after. Error messages were reworded to
`unsafe path: <specific reason>` so the pre-existing contract in
`test_m3f_acceptance_hardening.py` (`match="unsafe path"`) and the new specific-reason assertions
both hold — the alternative was rewriting a pre-existing test's expectations, which is the more
invasive change.

### A defect this work exposed in my own test

Reproducing the forged-lift launder (standing correction 6) ran the new determination suite against
a clone whose containment record *had* `lifted_by`/`lifted_on`. `test_the_gate_refuses_an_unattributed_lift`
failed there — correctly, but for the wrong reason: it built its fixture as
`_load(CONTAINMENT_PATH) | {"active": False}` and inherited whatever the live record contained, so
the moment a lift was recorded it silently stopped being an unattributed-lift test. Now it removes
the attribution keys explicitly and asserts their absence. Deriving an attack fixture from live
state is the same class of mistake as reducing over a rebindable collection: the fixture stops
describing the thing it is named after.
