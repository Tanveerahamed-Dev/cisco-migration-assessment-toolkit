"""The published FHRP redundancy-domain receipt serialises identically under every hash seed.

The snapshot (and the pipeline golden) is written with ``sort_keys=False``: key order is code-defined and part
of the written bytes. A member row built by iterating a ``set`` of field names made that order depend on
PYTHONHASHSEED, so two runs over identical evidence wrote different bytes (dict-equal, textually churned) and
any byte-level comparison of a written snapshot could flap. This drives the REAL producer (and its embedded
projection) in fresh interpreters under several fixed hash seeds and requires byte-identical serialisations.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = r"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from test_fhrp_redundancy_domain_engine import _owner
from cisco_toolkit.fhrp_redundancy import (
    compute_fhrp_redundancy_domain_baseline, embedded_fhrp_redundancy_domain_baseline,
)
with tempfile.TemporaryDirectory() as tmp:
    configured, interfaces, _devices = _owner(Path(tmp), second_role="Standby")
    current = compute_fhrp_redundancy_domain_baseline(interfaces, configured)
embedded = embedded_fhrp_redundancy_domain_baseline(current)
assert current["domains"] and current["domains"][0]["members"], current
sys.stdout.write(json.dumps({"current": current, "embedded": embedded}, sort_keys=False))
"""


def _serialised_under_seed(seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(ROOT), str(ROOT / "tests")],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"seed {seed}:\nSTDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}"
    return proc.stdout


def test_domain_receipt_bytes_do_not_depend_on_the_hash_seed():
    outputs = {seed: _serialised_under_seed(seed) for seed in ("0", "1", "2", "3")}
    assert len(set(outputs.values())) == 1, (
        "the published FHRP redundancy-domain receipt serialises differently under different "
        "PYTHONHASHSEED values -- a set is being iterated to build a published dict")


def test_member_rows_follow_the_declared_field_order():
    from cisco_toolkit import fhrp_redundancy

    order = fhrp_redundancy._MEMBER_FIELD_ORDER
    assert isinstance(order, tuple) and len(set(order)) == len(order)
    # the validator's set and the builder's order are ONE owner: neither can drift from the other
    assert set(order) == fhrp_redundancy._MEMBER_KEYS
    published = json.loads(_serialised_under_seed("0"))
    for view in ("current", "embedded"):
        members = [m for d in published[view]["domains"] for m in d["members"]]
        assert members, view
        assert all(tuple(m) == order for m in members), (view, [list(m) for m in members])
