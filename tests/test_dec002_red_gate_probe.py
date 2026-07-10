"""DEC-002 refuting experiment (P0-4, architect-master-plan-2026-07-10 §5 Phase 0).

Deliberately-red probe: this test exists ONLY on the scratch branch
``scratch/dec002-red-gate-probe`` to prove that branch protection on ``main``
blocks merging a PR whose required checks fail. The PR carrying it is NEVER
merged — it is closed and the branch deleted once the BLOCKED state is
captured as evidence. If this file is ever on ``main``, the gate is not real.
"""


def test_dec002_deliberately_red_gate_probe():
    assert False, "DEC-002 refuting experiment: this PR must be unmergeable (never merge)"
