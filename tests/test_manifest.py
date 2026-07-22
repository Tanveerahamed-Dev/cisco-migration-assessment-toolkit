"""Tests for the sealed/navigable run-manifest chain-of-custody (roadmap D2 + J4).

The offline, deterministic answer to NetClaw's GAIT: an append-only, hash-chained ledger of the pipeline
steps (collect/parse/detector/deliverable) where each row commits to the previous one, so any later edit
to an earlier row is detectable without a Git dependency. Pure stdlib hashlib; determinism is the point.
"""
import json
import os
import sys
from pathlib import Path

from cisco_toolkit import manifest as m

ROOT = Path(__file__).resolve().parents[1]


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


# --- the shipped auditor surface -------------------------------------------------------------------
# Before this, verify_manifest/verify_chain had NO production caller and the module had no `main`,
# so `python -m cisco_toolkit.manifest` did nothing: a client could be handed a sealed manifest with
# no shipped command able to check it. These pin the verb, its exit codes, and its honesty.

def _write(tmp_path, name, man):
    p = tmp_path / name
    p.write_text(json.dumps(man, indent=2), encoding="utf-8")
    return str(p)


def _man(artifacts=None):
    return m.build_manifest({"schema_version": "3.23.0"}, artifacts or {},
                            [{"stage": "collect", "n": 253}, {"stage": "analyze"}, {"stage": "deliver"}])


def test_verify_verb_exits_zero_on_a_clean_manifest(tmp_path, capsys):
    assert m.main(["verify", _write(tmp_path, "a.run_manifest.json", _man())]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK: ")
    # A bare pass must never read as "provably untampered" — the chain is unkeyed.
    assert "not a forger who re-seals" in out and "--expect-root" in out


def test_verify_verb_exits_nonzero_on_a_broken_chain(tmp_path, capsys):
    man = _man()
    man["chain"][1]["stage"] = "analyze-but-actually-skipped"        # silent edit to a sealed row
    rc = m.main(["verify", _write(tmp_path, "b.run_manifest.json", man)])
    assert rc == 4, "a broken chain must exit non-zero — this is the whole point of the verb"
    assert "INTEGRITY" in capsys.readouterr().out


def test_verify_verb_names_truncation_as_truncation(tmp_path, capsys):
    """A dropped tail leaves every REMAINING row self-consistent, so the row indices verify_chain
    reports point at intact rows. Saying 'broken at row 0' sends the auditor to the wrong place."""
    man = _man()
    man["chain"] = man["chain"][:1]                                  # lop off analyze + deliver
    assert m.main(["verify", _write(tmp_path, "c.run_manifest.json", man)]) == 4
    out = capsys.readouterr().out
    assert "TRUNCATED" in out and "dropped from the end" in out


def test_verify_verb_exits_nonzero_when_the_file_is_unreadable(tmp_path, capsys):
    assert m.main(["verify", str(tmp_path / "does-not-exist.json")]) == 4
    assert "cannot read manifest" in capsys.readouterr().out
    torn = tmp_path / "torn.json"
    torn.write_text('{"chain": [{"seq": 0,', encoding="utf-8")        # truncated mid-write
    assert m.main(["verify", str(torn)]) == 4
    assert "cannot read manifest" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text('["not", "a manifest"]', encoding="utf-8")         # valid JSON, wrong shape
    assert m.main(["verify", str(bad)]) == 4
    assert "not a manifest object" in capsys.readouterr().out


def test_expect_root_is_the_check_a_re_seal_cannot_pass(tmp_path, capsys):
    """The recorded weakness, mechanized: build_manifest is public and the chain is unkeyed, so an
    edited ledger RE-SEALS to a clean chain_root and plain `verify` passes it. Only a root held out
    of band catches that — so the verb must offer it, and it must actually fail on mismatch."""
    real = _man()
    forged = m.build_manifest({"schema_version": "3.23.0"}, {},
                              [{"stage": "collect", "n": 3}, {"stage": "analyze"}, {"stage": "deliver"}])
    forged_path = _write(tmp_path, "forged.run_manifest.json", forged)
    assert forged["chain_root"] != real["chain_root"]
    assert m.main(["verify", forged_path]) == 0, "a re-sealed forgery passes plain verify — by design"
    capsys.readouterr()
    assert m.main(["verify", forged_path, "--expect-root", real["chain_root"]]) == 4
    assert "chain_root MISMATCH" in capsys.readouterr().out
    # and the genuine file passes against its own recorded root, with no unkeyed-seal caveat
    ok_path = _write(tmp_path, "real.run_manifest.json", real)
    assert m.main(["verify", ok_path, "--expect-root", real["chain_root"]]) == 0
    # tolerant of how a human copies it: surrounding space, upper-case hex
    capsys.readouterr()
    assert m.main(["verify", ok_path, "--expect-root", "  " + real["chain_root"].upper() + " "]) == 0


def test_a_truncated_expect_root_is_not_reported_as_a_mismatch(tmp_path, capsys):
    """The engine's end-of-run console line prints chain_root cut to 12 chars, so a PARTIAL root is
    the likeliest thing an engineer copies into the report. Calling that "not the manifest that run
    produced" would have them reject a genuine deliverable set at a client site — the expensive
    direction of a false positive. It must fail as a bad ARGUMENT, and say where to get the real one."""
    man = _man()
    path = _write(tmp_path, "r.run_manifest.json", man)
    for partial in (man["chain_root"][:12], man["chain_root"][:16], "not-hex-at-all", ""):
        assert m.main(["verify", path, "--expect-root", partial]) == 4
        out = capsys.readouterr().out
        assert "not a full chain_root" in out and "Not checked against the file" in out
        assert "MISMATCH" not in out, f"a short root read as a forged file: {partial!r}"


def test_artifact_check_catches_altered_and_missing_deliverables(tmp_path, capsys):
    (tmp_path / "wb.xlsx").write_bytes(b"workbook-bytes")
    man = _man({"wb.xlsx": m.artifact_sha256(b"workbook-bytes"), "gone.html": "0" * 64})
    path = _write(tmp_path, "d.run_manifest.json", man)
    assert m.main(["verify", path]) == 0                     # chain alone is clean
    capsys.readouterr()
    assert m.main(["verify", path, "--artifacts"]) == 4       # ...but a listed file is absent
    out = capsys.readouterr().out
    assert "[MISSING] gone.html" in out
    assert "[MISMATCH] wb.xlsx" not in out                    # that one really does match

    (tmp_path / "wb.xlsx").write_bytes(b"workbook-bytes-EDITED")
    assert m.main(["verify", path, "--artifacts"]) == 4
    assert "[MISMATCH] wb.xlsx" in capsys.readouterr().out


def test_python_dash_m_entry_actually_runs(tmp_path):
    """Every other test here calls main() in-process, so deleting the `if __name__ == "__main__"`
    block would leave them ALL green while `python -m cisco_toolkit.manifest verify` silently did
    nothing again — the exact defect this verb exists to fix. Pin the documented invocation, in a
    real subprocess, including the exit code a caller scripts against."""
    import subprocess
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    clean = _write(tmp_path, "clean.run_manifest.json", _man())
    r = subprocess.run([sys.executable, "-m", "cisco_toolkit.manifest", "verify", clean],
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout.startswith("OK: ")

    man = _man()
    man["chain"][0]["stage"] = "edited"
    broken = _write(tmp_path, "broken.run_manifest.json", man)
    r = subprocess.run([sys.executable, "-m", "cisco_toolkit.manifest", "verify", broken],
                       capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert r.returncode == 4, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "INTEGRITY" in r.stdout


def test_artifact_names_cannot_escape_the_folder(tmp_path, capsys):
    """The manifest is UNTRUSTED input — it comes back from a share, a client, an email. Artifact
    names are joined to a directory, and os.path.join DISCARDS that directory for an absolute name
    while '../' walks out of it, so a crafted manifest would turn `verify --artifacts` into a
    read-and-hash oracle over the auditor's own disk. Refused unopened, never normalised."""
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"client-credentials")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "wb.xlsx").write_bytes(b"real")

    escapes = ["../secret.txt", "..\\secret.txt", str(secret), "sub/wb.xlsx", "sub\\wb.xlsx",
               "//host/share/wb.xlsx", "C:/Windows/win.ini", "", ".."]
    man = _man({name: m.artifact_sha256(b"client-credentials") for name in escapes})
    path = _write(tmp_path, "evil.run_manifest.json", man)
    res = m.verify_file(path, artifacts_dir=str(outside))
    assert res["ok"] is False
    assert {a["state"] for a in res["artifacts"]} == {"INVALID"}, \
        f"an escaping name was opened: {res['artifacts']}"
    assert m.main(["verify", path, "--artifacts"]) == 4
    assert "INVALID" in capsys.readouterr().out

    # ...and an ordinary basename in that same folder still verifies normally (non-vacuous).
    ok_man = _man({"wb.xlsx": m.artifact_sha256(b"real")})
    assert m.verify_file(_write(tmp_path, "ok.run_manifest.json", ok_man),
                         artifacts_dir=str(outside))["ok"] is True


def test_gutted_manifest_does_not_verify_clean(tmp_path, capsys):
    """`verify_manifest({})` is (True, []) — with no chain and no chain_root there is nothing to
    contradict, so the LIBRARY reports clean. Passed through, that makes the emptiest possible file
    the easiest one to "verify": strip the chain and an auditor reads OK. Absence is not health."""
    for i, man in enumerate(({}, {"tool": "cisco-assess"}, {"chain": [], "chain_root": m.GENESIS})):
        assert m.verify_manifest(man)[0] in (True, False)             # library semantics unchanged
        assert m.main(["verify", _write(tmp_path, f"gutted{i}.json", man)]) == 4
        assert "nothing sealed here" in capsys.readouterr().out


def test_artifact_check_is_opt_in(tmp_path):
    """Deliverables get split across shares; a plain `verify` must answer only 'does the ledger
    reconcile', or every routine check would fail for a reason that is not tampering."""
    man = _man({"never-delivered.docx": "0" * 64})
    assert m.main(["verify", _write(tmp_path, "e.run_manifest.json", man)]) == 0
