"""Tests for the DEC-007 sealed-holdout tooling (cisco_toolkit.holdout) — P1-2.

The load-bearing properties, straight off the contract (docs/quality/holdout-contract.md):

- activation REFUSES below N >= 50 REAL labelled rows — source_class-aware, REAL only: a
  surrogate flood in any quantity never activates (same discriminator as the D11 gate);
- the seal is deterministic and content-addressed (same rows -> same chain_root, any order);
- seal -> tamper -> verify FAILS: chain edits, policy-term edits, tail truncation, and
  store-row deletion/edits are all caught; an optimisation-row edit is documented as OUTSIDE
  the seal (the manifest freezes the holdout, not the whole store);
- every access through the accessor is LOGGED (who/when) — on success AND on integrity
  failure; an unattributed read is refused before anything is read;
- the CLI refuses to seal below the floor and refuses to overwrite an existing manifest
  (re-sealing is a human-gated event).
"""
import json
import pathlib
import random
import re

import pytest

from cisco_toolkit import holdout as H
from cisco_toolkit.manifest import hash_chain

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _real(i, predicted="READY", actual="clean"):
    return {"predicted": predicted, "actual": actual, "source_class": "REAL",
            "date": "2026-07-10", "engagement": f"eng-{i % 7}", "unit": f"unit-{i}",
            "commit": "abc123", "notes": f"row {i}"}


def _reals(n):
    return [_real(i) for i in range(n)]


def _surrogate(i, sc="fault-injected"):
    return {"predicted": "NOT_READY", "actual": "incident", "source_class": sc,
            "unit": f"surrogate-{i}"}


def _sealed_digests(man):
    return [r["row_sha256"] for r in man["chain"][1:] if r.get("kind") == "holdout_row"]


def _write_store(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _seal_to_files(tmp_path, rows):
    store = tmp_path / "pir.jsonl"
    _write_store(store, rows)
    man = H.seal(rows, store=str(store))
    mpath = tmp_path / "holdout_manifest.json"
    mpath.write_text(json.dumps(man), encoding="utf-8")
    return store, mpath, tmp_path / "access.jsonl"


# --- activation refusal (the DEC-007 floor; REAL-only, source_class-aware) ----------------------

def test_activation_refused_below_floor():
    """49 REAL rows is one short of the floor: seal refuses and says exactly why."""
    with pytest.raises(H.HoldoutActivationError) as e:
        H.seal(_reals(49))
    assert "49 REAL" in str(e.value) and "50" in str(e.value)
    st = H.activation_status(_reals(49))
    assert st["eligible"] is False and st["real_n"] == 49 and st["floor"] == 50


def test_activation_refused_for_surrogate_only_store():
    """80 surrogate rows, zero REAL: the split must stay dormant however large the store is."""
    with pytest.raises(H.HoldoutActivationError) as e:
        H.seal([_surrogate(i) for i in range(80)])
    assert "0 REAL" in str(e.value) and "surrogate" in str(e.value).lower()


def test_surrogate_flood_never_activates():
    # 49 REAL + 200 synthetic = 249 rows, still below the REAL floor.
    rows = _reals(49) + [_surrogate(i, sc="synthetic") for i in range(200)]
    st = H.activation_status(rows)
    assert st["eligible"] is False and st["real_n"] == 49 and st["n"] == 249
    with pytest.raises(H.HoldoutActivationError):
        H.seal(rows)


def test_untagged_and_malformed_rows_never_count_toward_activation():
    # Unknown provenance != REAL (fail-safe), and a malformed REAL row is dropped, not coerced.
    untagged = [{"predicted": "READY", "actual": "clean", "unit": f"u{i}"} for i in range(60)]
    assert H.activation_status(untagged)["real_n"] == 0
    rows = _reals(49) + [{"predicted": "???", "actual": "clean", "source_class": "REAL"}] * 5
    assert H.activation_status(rows)["real_n"] == 49


def test_floor_is_the_knob():
    assert H.activation_status(_reals(10), floor=10)["eligible"] is True
    assert H.seal(_reals(10), floor=10)["chain"][0]["activation_floor"] == 10


# --- the seal (70/30, deterministic, content-addressed) -----------------------------------------

def test_seal_at_floor_is_70_30():
    rows = _reals(50)
    man = H.seal(rows)
    pol = man["chain"][0]
    assert (pol["real_n"], pol["holdout_n"], pol["optimisation_n"]) == (50, 15, 35)
    assert pol["policy"] == "DEC-007" and pol["activation_floor"] == 50
    assert len(man["chain"]) == 16                      # policy step + 15 holdout digests
    assert man["chain_root"] == man["chain"][-1]["sha256"]
    res = H.verify(man)
    assert res["ok"] is True and "store not checked" in res["reason"]
    res_store = H.verify(man, store_rows=rows)
    assert res_store["ok"] is True and res_store["missing"] == []


def test_split_is_integer_floor_of_30_pct():
    parts = H.split_real_rows(_reals(53) + [_surrogate(1)])
    assert parts["real_n"] == 53                        # surrogate rows are not split at all
    assert len(parts["holdout"]) == 53 * 30 // 100 == 15
    assert len(parts["optimisation"]) == 38
    assert parts["holdout_digests"] == sorted(parts["holdout_digests"])   # lowest digests first


def test_seal_is_deterministic_and_order_independent():
    rows = _reals(60)
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    a, b = H.seal(rows), H.seal(shuffled)
    assert a["chain_root"] == b["chain_root"]           # content-addressed: store order irrelevant
    assert _sealed_digests(a) == _sealed_digests(b)


def test_row_digest_is_alias_invariant_and_honest_about_malformed():
    # 'go'/'success'/'pir' normalize to READY/clean/REAL -> same digest (respelling != tampering).
    a = H.row_sha256({"predicted": "go", "actual": "success", "source_class": "pir", "unit": "u1"})
    b = H.row_sha256({"predicted": "READY", "actual": "clean", "source_class": "REAL", "unit": "u1"})
    assert a == b
    assert H.row_sha256({"predicted": "???", "actual": "clean"}) is None


# --- seal -> tamper -> verify fails --------------------------------------------------------------

def test_tampered_holdout_digest_breaks_the_chain():
    man = H.seal(_reals(50))
    man["chain"][5]["row_sha256"] = "0" * 64            # quietly swap a sealed membership entry
    res = H.verify(man)
    assert res["ok"] is False and "chain broken" in res["reason"]


def test_tampered_policy_terms_break_the_chain():
    man = H.seal(_reals(50))
    man["chain"][0]["activation_floor"] = 1             # rewrite the sealed terms of the seal
    assert H.verify(man)["ok"] is False


def test_tail_truncation_is_detected_against_the_root():
    man = H.seal(_reals(50))
    man["chain"] = man["chain"][:-3]                    # lop off sealed holdout rows
    assert H.verify(man)["ok"] is False


def test_missing_policy_step_is_detected():
    man = H.seal(_reals(50))
    man["chain"] = man["chain"][1:]                     # drop the sealed policy header
    res = H.verify(man)
    assert res["ok"] is False and "policy" in res["reason"]


def test_self_consistent_chain_with_wrong_count_is_detected():
    # An attacker re-cuts a valid chain claiming a different holdout size: hashes verify, the
    # policy-vs-chain count reconcile does not.
    steps = [{"kind": "policy", "policy": "DEC-007", "activation_floor": 50, "holdout_pct": 30,
              "real_n": 50, "optimisation_n": 35, "holdout_n": 2},
             {"kind": "holdout_row", "row_sha256": "ab" * 32}]
    chain = hash_chain(steps)
    res = H.verify({"chain": chain, "chain_root": chain[-1]["sha256"]})
    assert res["ok"] is False and "holdout_n" in res["reason"]


def test_store_row_edit_or_deletion_is_detected():
    rows = _reals(50)
    man = H.seal(rows)
    sealed = set(_sealed_digests(man))
    victim = next(r for r in rows if H.row_sha256(r) in sealed)
    # content-edit: flip the sealed row's outcome -> its digest no longer resolves in the store
    edited = [dict(r, actual="incident") if r is victim else r for r in rows]
    res = H.verify(man, store_rows=edited)
    assert res["ok"] is False and len(res["missing"]) == 1
    # deletion: drop the sealed row entirely
    res2 = H.verify(man, store_rows=[r for r in rows if r is not victim])
    assert res2["ok"] is False and res2["missing"] == res["missing"]


def test_optimisation_row_edit_is_outside_the_seal():
    """Documented boundary, asserted so it stays a decision: the manifest freezes the HOLDOUT;
    optimisation rows are covered by the append-only store + git history, not by this seal."""
    rows = _reals(50)
    man = H.seal(rows)
    sealed = set(_sealed_digests(man))
    opt = next(r for r in rows if H.row_sha256(r) not in sealed)
    edited = [dict(r, actual="incident") if r is opt else r for r in rows]
    assert H.verify(man, store_rows=edited)["ok"] is True


# --- the logging accessor -------------------------------------------------------------------------

def test_read_returns_exactly_the_sealed_holdout_and_logs_who_when(tmp_path):
    rows = _reals(50)
    store, mpath, log = _seal_to_files(tmp_path, rows)
    out = H.read_holdout("pytest", "unit-test read", manifest_path=str(mpath),
                         store_path=str(store), log_path=str(log))
    assert len(out) == 15
    assert all(o["source_class"] == "REAL" for o in out)
    man = json.loads(mpath.read_text(encoding="utf-8"))
    assert sorted(H.row_sha256(o) for o in out) == sorted(_sealed_digests(man))
    entries = H.read_access_log(str(log))
    assert len(entries) == 1
    e = entries[0]
    assert e["who"] == "pytest" and e["purpose"] == "unit-test read"
    assert e["ok"] is True and e["n_rows"] == 15
    assert e["chain_root"] == man["chain_root"] and "ts" in e and "os_user" in e
    # a second read appends — the trail is append-only, one line per access
    H.read_holdout("pytest-2", manifest_path=str(mpath), store_path=str(store), log_path=str(log))
    trail = H.read_access_log(str(log))
    assert len(trail) == 2 and trail[1]["who"] == "pytest-2"


def test_failed_integrity_read_still_logs_the_attempt(tmp_path):
    rows = _reals(50)
    store, mpath, log = _seal_to_files(tmp_path, rows)
    sealed = set(_sealed_digests(json.loads(mpath.read_text(encoding="utf-8"))))
    _write_store(store, [r for r in rows if H.row_sha256(r) not in sealed][:40]
                 + [r for r in rows if H.row_sha256(r) in sealed][1:])   # delete one holdout row
    with pytest.raises(H.HoldoutIntegrityError) as e:
        H.read_holdout("pytest", "tamper attempt", manifest_path=str(mpath),
                       store_path=str(store), log_path=str(log))
    assert "logged" in str(e.value)
    entries = H.read_access_log(str(log))
    assert len(entries) == 1
    assert entries[0]["ok"] is False and entries[0]["n_rows"] == 0
    assert entries[0]["who"] == "pytest"


def test_unattributed_read_is_refused_before_anything_is_read(tmp_path):
    rows = _reals(50)
    store, mpath, log = _seal_to_files(tmp_path, rows)
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            H.read_holdout(bad, manifest_path=str(mpath), store_path=str(store), log_path=str(log))
    assert H.read_access_log(str(log)) == []            # nothing was read, nothing to log


def test_read_before_activation_says_no_seal_exists(tmp_path):
    with pytest.raises(H.HoldoutIntegrityError) as e:
        H.read_holdout("pytest", manifest_path=str(tmp_path / "absent.json"),
                       log_path=str(tmp_path / "access.jsonl"))
    assert "not activated" in str(e.value)


def test_access_log_reader_is_tolerant(tmp_path):
    assert H.read_access_log(str(tmp_path / "nope.jsonl")) == []
    p = tmp_path / "log.jsonl"
    p.write_text('{"who": "a"}\nnot json\n\n{"who": "b"}\n', encoding="utf-8")
    assert [e["who"] for e in H.read_access_log(str(p))] == ["a", "b"]


# --- CLI (exit codes: 0 ok / 2 refusal / 4 integrity) ---------------------------------------------

def test_cli_status_reports_dormant_state(tmp_path, capsys):
    store = tmp_path / "pir.jsonl"
    _write_store(store, _reals(3) + [_surrogate(1)])
    assert H.main(["status", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert "refused" in out and "3 REAL" in out and "fault-injected" in out


def test_cli_seal_refuses_below_floor_and_writes_nothing(tmp_path, capsys):
    store, out = tmp_path / "pir.jsonl", tmp_path / "m.json"
    _write_store(store, _reals(10))
    assert H.main(["seal", "--store", str(store), "--out", str(out)]) == 2
    assert "REFUSED" in capsys.readouterr().out
    assert not out.exists()


def test_cli_seal_verify_read_roundtrip_and_no_overwrite(tmp_path, capsys):
    store, out, log = tmp_path / "pir.jsonl", tmp_path / "m.json", tmp_path / "access.jsonl"
    _write_store(store, _reals(50))
    assert H.main(["seal", "--store", str(store), "--out", str(out)]) == 0
    assert out.exists() and "15 holdout / 35 optimisation" in capsys.readouterr().out
    # re-sealing is human-gated: an existing manifest is never overwritten
    assert H.main(["seal", "--store", str(store), "--out", str(out)]) == 2
    assert "human-gated" in capsys.readouterr().out
    assert H.main(["verify", "--manifest", str(out), "--store", str(store)]) == 0
    capsys.readouterr()
    assert H.main(["read", "--who", "pytest-cli", "--purpose", "roundtrip", "--manifest", str(out),
                   "--store", str(store), "--log", str(log)]) == 0
    lines = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln]
    assert len(lines) == 15 and all(json.loads(ln)["source_class"] == "REAL" for ln in lines)
    assert H.read_access_log(str(log))[0]["who"] == "pytest-cli"


def test_contract_document_reconciles_to_its_code_owners():
    """Law 1: the contract's figures are cited caches of holdout.py/calibration.py constants; a
    constant change that leaves the document behind must go red here. Also pins the load-bearing
    coverage-honesty sentence and the ssot.md registration, so neither can be silently dropped."""
    doc = ROOT / "docs" / "quality" / "holdout-contract.md"
    assert doc.exists(), "the DEC-007 policy owner document is missing"
    txt = doc.read_text(encoding="utf-8")
    assert re.search(rf"ACTIVATION_FLOOR[`*]*\s*\(=\s*{H.ACTIVATION_FLOOR}\)", txt), (
        "contract's cached activation floor drifted from holdout.ACTIVATION_FLOOR")
    assert re.search(rf"HOLDOUT_PCT[`*]*\s*=\s*{H.HOLDOUT_PCT}\b", txt), (
        "contract's cached holdout share drifted from holdout.HOLDOUT_PCT")
    from cisco_toolkit.calibration import DEFAULT_N_FLOOR
    assert re.search(rf"DEFAULT_N_FLOOR[`*]*\s*\(=\s*{DEFAULT_N_FLOOR}\)", txt), (
        "contract's cached D11 tuning floor drifted from calibration.DEFAULT_N_FLOOR")
    assert "proof of non-use does not exist" in txt.lower(), (
        "the contract lost its coverage-honesty core: audit trail, never proof")
    registry = (ROOT / "docs" / "ssot.md").read_text(encoding="utf-8")
    assert "holdout-contract.md" in registry, (
        "docs/ssot.md no longer registers the holdout contract as a policy owner (Law 1)")


def test_cli_verify_flags_store_tamper(tmp_path, capsys):
    store, out = tmp_path / "pir.jsonl", tmp_path / "m.json"
    rows = _reals(50)
    _write_store(store, rows)
    assert H.main(["seal", "--store", str(store), "--out", str(out)]) == 0
    sealed = set(_sealed_digests(json.loads(out.read_text(encoding="utf-8"))))
    _write_store(store, [dict(r, actual="incident") if H.row_sha256(r) in sealed else r
                         for r in rows])                # flip every sealed row's outcome
    capsys.readouterr()
    assert H.main(["verify", "--manifest", str(out), "--store", str(store)]) == 4
    assert "INTEGRITY" in capsys.readouterr().out
