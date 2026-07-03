"""Tests for the sealed/navigable run-manifest chain-of-custody (roadmap D2 + J4).

The offline, deterministic answer to NetClaw's GAIT: an append-only, hash-chained ledger of the pipeline
steps (collect/parse/detector/deliverable) where each row commits to the previous one, so any later edit
to an earlier row is detectable without a Git dependency. Pure stdlib hashlib; determinism is the point.
"""
from cisco_toolkit import manifest as m


def test_hash_chain_is_deterministic_and_linked():
    steps = [{"stage": "collect", "host": "sw1"}, {"stage": "parse", "host": "sw1"}, {"stage": "deliver", "artifact": "wb.xlsx"}]
    a = m.hash_chain(steps)
    b = m.hash_chain(steps)
    assert [r["sha256"] for r in a] == [r["sha256"] for r in b]      # same input -> same chain
    assert a[0]["prev_sha256"] == m.GENESIS
    assert a[1]["prev_sha256"] == a[0]["sha256"]                      # each row commits to the previous
    assert a[2]["prev_sha256"] == a[1]["sha256"]
    assert [r["seq"] for r in a] == [0, 1, 2]


def test_clean_chain_verifies():
    chain = m.hash_chain([{"stage": "collect"}, {"stage": "parse"}])
    ok, broken = m.verify_chain(chain)
    assert ok is True and broken == []


def test_tampering_with_an_earlier_row_is_detected():
    chain = m.hash_chain([{"stage": "collect", "n": 1}, {"stage": "parse", "n": 2}, {"stage": "deliver", "n": 3}])
    chain[1]["n"] = 999                                              # silently edit a sealed step
    ok, broken = m.verify_chain(chain)
    assert ok is False
    assert 1 in broken


def test_build_manifest_assembles_seal():
    man = m.build_manifest(
        meta={"schema_version": "3.23.0", "generated_at": "2026-06-30T00:00:00", "collected_at": "2026-06-13T06:32:01",
              "devices_file_sha256": "abc123", "abstention_ledger": {"vpc": "not_collected"}},
        artifacts={"workbook.xlsx": "deadbeef", "explorer.html": "cafef00d"},
        steps=[{"stage": "collect", "n_devices": 253}, {"stage": "deliver", "artifact": "workbook.xlsx"}],
    )
    assert man["schema_version"] == "3.23.0"
    assert man["devices_file_sha256"] == "abc123"
    assert man["abstention_ledger"]["vpc"] == "not_collected"
    assert [a["name"] for a in man["artifacts"]] == ["explorer.html", "workbook.xlsx"]   # sorted
    assert man["chain_root"] == man["chain"][-1]["sha256"]
    ok, _ = m.verify_chain(man["chain"])
    assert ok is True


# --- review-wave-1 regression tests --------------------------------------------------------------

def test_reserved_key_in_step_does_not_false_alarm():
    chain = m.hash_chain([{"stage": "parse", "name": "RM-IN", "seq": 10, "sha256": "caller-value"}])
    ok, broken = m.verify_chain(chain)
    assert ok is True and broken == []      # was: (False, [0]) — caller's reserved keys collided with the seal


def test_seq_tampering_is_detected():
    chain = m.hash_chain([{"stage": "a"}, {"stage": "b"}, {"stage": "c"}])
    for r in chain:
        r["seq"] = 99                       # rewrite the ordering/custody position
    ok, _ = m.verify_chain(chain)
    assert ok is False                      # was: (True, []) — seq was outside the hash


def test_tail_truncation_detected_against_root():
    man = m.build_manifest({}, {}, [{"s": "a"}, {"s": "b"}, {"s": "c"}, {"s": "d"}])
    man["chain"] = man["chain"][:2]         # attacker lops off the tail (the critical finding + deliverable)
    ok, _ = m.verify_chain(man["chain"], expected_root=man["chain_root"])
    assert ok is False
    assert m.verify_manifest(man)[0] is False   # the manifest's own root no longer matches its (truncated) chain


def test_nonserializable_step_is_deterministic():
    class Detector:
        pass
    a = m.hash_chain([{"stage": "detect", "obj": Detector()}])
    b = m.hash_chain([{"stage": "detect", "obj": Detector()}])
    assert a[0]["sha256"] == b[0]["sha256"]   # was: process-nondeterministic (memory address in the default repr)
