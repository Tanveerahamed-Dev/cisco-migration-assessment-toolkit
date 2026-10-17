"""Executed canonical-fact mutation ratchet; no self-declared reconciled-path list."""
from copy import deepcopy

from cisco_toolkit import ssot


def require_canonical_checks(snapshot):
    """Every registered fact must be refutable on this real producer's raw basis.

    An absent value or raw basis is a failing fixture obligation, never an exemption.
    This also covers worst_band, whose executed comparison predates the _ran census.
    """
    assert ssot.reconcile(snapshot) == [], "The positive producer control already drifts"
    for name, (path, _concept) in ssot.CANONICAL_FACTS.items():
        mutant = deepcopy(snapshot)
        parts = path.split(".")
        parent = mutant
        for part in parts[:-1]:
            assert isinstance(parent, dict) and part in parent, f"No real producer basis for {name}: {path}"
            parent = parent[part]
        assert parts[-1] in parent, f"Producer does not publish {name}: {path}"
        value = parent[parts[-1]]
        # Choose a different finite value without importing any producer derivation.
        parent[parts[-1]] = "__canonical_mutation__" if isinstance(value, str) else (
            value + 100003 if type(value) in (int, float) else 100003)
        violations = ssot.reconcile(mutant)
        assert any(v.startswith(path + "=") for v in violations), (
            f"CANONICAL_FACTS[{name!r}] has no executed reconcile check on the producer snapshot: {path}; "
            f"observed violations: {violations}")
