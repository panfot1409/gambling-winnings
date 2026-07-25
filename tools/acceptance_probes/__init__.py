"""Reproduce the acceptance-layer probe truth table.

Run ``python tools/acceptance_probes/run_probes.py`` from a clean checkout, then
``run_guard_deletions.py``, then ``render_truth_table.py``. Each probe executes in
its own disposable clone; the working tree is never mutated, and the run refuses
outright if the tree is dirty.
"""
