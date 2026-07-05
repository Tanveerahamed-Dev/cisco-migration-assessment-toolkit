"""[K2] Replay the PARSER_EXAMPLES registry (tests/parser_examples.py) against
cisco_toolkit.parse forever.

Guards the #1 recurring bug class: an unseen platform variant parses to []/{} and
silently reads as feature-absent. Every example is a verbatim (anonymized) real-output
block; the replay asserts the parser still yields at least the pinned entity count and
that pinned spot facts still hold. The integrity tests keep the registry itself honest
(real parse_* callables, no empty example lists, non-trivial inputs)."""
import pytest

from cisco_toolkit import parse
from parser_examples import PARSER_EXAMPLES


def _cases():
    return [(name, i, ex)
            for name, examples in sorted(PARSER_EXAMPLES.items())
            for i, ex in enumerate(examples)]


def _resolve(result, path):
    """Walk a spot-fact path (tuple of dict-keys / list-indices) into the result."""
    node = result
    for seg in path:
        node = node[seg]
    return node


@pytest.mark.parametrize(
    "name,idx,ex", _cases(), ids=[f"{n}-{i}" for n, i, _ in _cases()]
)
def test_replay_example(name, idx, ex):
    fn = getattr(parse, name, None)
    assert callable(fn), f"{name} is not a callable in cisco_toolkit.parse"
    args = tuple(ex.get("prefix_args", ())) + (ex["input"],)
    result = fn(*args)
    # the anti-[]/{} guard: the real block must never again read as feature-absent
    assert result, f"{name} example #{idx} parsed to empty ({result!r})"
    n = len(result)
    assert n >= ex["expect_min_entities"], (
        f"{name} example #{idx}: {n} entities < pinned minimum "
        f"{ex['expect_min_entities']} -- a platform variant regressed"
    )
    for path, want in ex["spot_facts"]:
        try:
            got = _resolve(result, path)
        except (KeyError, IndexError, TypeError) as e:
            pytest.fail(f"{name} example #{idx}: spot-fact path {path!r} unresolvable: {e!r}")
        assert got == want, (
            f"{name} example #{idx}: spot fact {path!r} = {got!r}, pinned {want!r}"
        )


# --------------------------------------------------------------------- registry integrity

def test_registry_keys_resolve_to_real_parsers():
    for name in PARSER_EXAMPLES:
        assert name.startswith("parse_"), f"registry key {name!r} is not a parse_* name"
        fn = getattr(parse, name, None)
        assert callable(fn), f"registry key {name!r} has no callable in cisco_toolkit.parse"


def test_registry_has_no_empty_example_lists():
    for name, examples in PARSER_EXAMPLES.items():
        assert isinstance(examples, list) and examples, f"{name}: empty/invalid example list"


def test_registry_examples_are_well_formed():
    for name, examples in PARSER_EXAMPLES.items():
        for i, ex in enumerate(examples):
            where = f"{name}[{i}]"
            assert isinstance(ex.get("input"), str), f"{where}: input must be a str"
            # >3 lines: a one-liner is a self-authored toy, not a real capture slice
            assert len(ex["input"].splitlines()) > 3, f"{where}: input must be > 3 lines"
            assert isinstance(ex.get("expect_min_entities"), int) and ex["expect_min_entities"] >= 1, \
                f"{where}: expect_min_entities must be an int >= 1"
            assert isinstance(ex.get("spot_facts"), list), f"{where}: spot_facts must be a list"
            for sf in ex["spot_facts"]:
                assert isinstance(sf, tuple) and len(sf) == 2 and isinstance(sf[0], tuple), \
                    f"{where}: spot fact {sf!r} must be ((seg, ...), value)"


def test_registry_fixtures_hold_no_live_credentials():
    """Anonymization gate: no cleartext enable/user secrets, no SNMP communities.
    (Type-5 salted-MD5 fixture hashes from the audit5 precedent are allowed.)"""
    import re
    for name, examples in PARSER_EXAMPLES.items():
        for i, ex in enumerate(examples):
            text = ex["input"]
            assert not re.search(r"snmp-server\s+community\s+\S+", text, re.I), \
                f"{name}[{i}]: SNMP community string leaked"
            assert not re.search(r"enable\s+(?:secret|password)\s+(?:0\s+)?\S+", text, re.I), \
                f"{name}[{i}]: enable secret/password leaked"
            assert not re.search(r"tacacs|radius[- ]server\s+key", text, re.I), \
                f"{name}[{i}]: AAA server key leaked"
