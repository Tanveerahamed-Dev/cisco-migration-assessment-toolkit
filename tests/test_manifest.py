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


# --- adversarial-refuter regressions ---------------------------------------------------------------
# Every case below returned the WRONG answer before its fix. Found by independent refuters running
# probes, not by reading the code: my own review of this same file missed all of them.

def test_a_swapped_deliverable_cannot_pass_expect_root(tmp_path, capsys):
    """The one that mattered. `artifacts` used to sit OUTSIDE the chain — the pipeline's steps seal
    artifact NAMES, never their digests — so swapping a delivered workbook and rewriting its sha256
    in the top-level list left chain_root untouched. Both --artifacts (it re-hashes to the rewritten
    value) and --expect-root (the chain never changed) reported clean. For a tool whose entire
    question is "is this the workbook that was sealed?", that was a false pass on the only case
    anyone cares about."""
    (tmp_path / "wb.xlsx").write_bytes(b"genuine workbook")
    man = m.build_manifest({}, {"wb.xlsx": m.artifact_sha256(b"genuine workbook")},
                           [{"stage": "collect"}, {"stage": "deliver"}])
    real_root = man["chain_root"]

    (tmp_path / "wb.xlsx").write_bytes(b"FORGED workbook")
    forged = json.loads(json.dumps(man))
    forged["artifacts"][0]["sha256"] = m.artifact_sha256(b"FORGED workbook")
    assert forged["chain"] == man["chain"], "fixture invalid: the chain must be untouched"
    path = _write(tmp_path, "forged.run_manifest.json", forged)

    res = m.verify_file(path, expect_root=real_root, artifacts_dir=str(tmp_path))
    assert res["ok"] is False, "a swapped deliverable passed every check the tool offers"
    assert "ARTIFACT LIST ALTERED" in res["reason"]
    assert m.main(["verify", path, "--expect-root", real_root, "--artifacts"]) == 4
    capsys.readouterr()
    # and the genuine pair still verifies — the guard must not reject honest manifests
    (tmp_path / "wb.xlsx").write_bytes(b"genuine workbook")
    ok_path = _write(tmp_path, "genuine.run_manifest.json", man)
    assert m.verify_file(ok_path, expect_root=real_root, artifacts_dir=str(tmp_path))["ok"] is True


def test_artifact_digests_are_inside_the_chain(tmp_path):
    """The structural property behind the test above: changing an artifact's digest must change
    chain_root. If this fails, the seal has silently stopped covering the deliverables again."""
    a = m.build_manifest({}, {"wb.xlsx": "a" * 64}, [{"stage": "deliver"}])
    b = m.build_manifest({}, {"wb.xlsx": "b" * 64}, [{"stage": "deliver"}])
    assert a["chain_root"] != b["chain_root"], "artifact digests are not covered by chain_root"
    assert m._sealed_artifacts(a["chain"]) == a["artifacts"]


def test_a_manifest_predating_artifact_sealing_says_so(tmp_path, capsys):
    """Coverage honesty: an older manifest has no sealed-artifacts row. It must not be reported as
    though its digests were covered — absence of the check is stated, not assumed to be agreement."""
    man = m.build_manifest({}, {"wb.xlsx": "a" * 64}, [{"stage": "deliver"}])
    old = json.loads(json.dumps(man))
    old["chain"] = [r for r in old["chain"] if r.get("stage") != m.SEAL_ARTIFACTS]
    old["chain_root"] = old["chain"][-1]["sha256"]          # re-rooted, internally consistent
    assert m.main(["verify", _write(tmp_path, "old.json", old)]) == 0
    assert "predates artifact sealing" in capsys.readouterr().out


def test_a_nulled_chain_root_does_not_disable_the_truncation_check(tmp_path, capsys):
    """verify_chain skips its tail check when expected_root is None, so deleting or nulling
    chain_root switched truncation detection OFF: drop rows, null the root, and a gutted ledger
    verified as clean as an intact one. An unsealed ledger is not a weaker seal, it is no seal."""
    man = m.build_manifest({}, {}, [{"s": i} for i in range(5)])
    for label, mutate in (("null", lambda d: d.update(chain_root=None)),
                          ("absent", lambda d: d.pop("chain_root")),
                          ("empty", lambda d: d.update(chain_root="   "))):
        t = json.loads(json.dumps(man))
        t["chain"] = t["chain"][:3]
        mutate(t)
        assert m.main(["verify", _write(tmp_path, f"t_{label}.json", t)]) == 4, label
        assert "no sealed chain_root" in capsys.readouterr().out


def test_wrong_typed_structures_report_instead_of_crashing(tmp_path, capsys):
    """The manifest is untrusted input. A wrong-typed `chain` or a non-dict row raised
    AttributeError/TypeError straight out of the CLI — a traceback and exit 1, where the contract
    is a sentence and exit 4. Same wrong-typed-value class as the stored-DoS wave (#462-#475)."""
    man = m.build_manifest({}, {"a.txt": "0" * 64}, [{"s": "a"}, {"s": "b"}])
    cases = {"chain_int": 5, "chain_str": "not-a-chain", "chain_bool": True,
             "chain_dict": {"row0": {}}, "rows_str": ["a", "b"], "rows_null": [None, None],
             "rows_int": [1, 2], "rows_list": [["a"]]}
    for label, bad in cases.items():
        d = json.loads(json.dumps(man)); d["chain"] = bad
        assert m.main(["verify", _write(tmp_path, f"{label}.json", d)]) == 4, label
        assert "INTEGRITY" in capsys.readouterr().out, label
    for label, bad in (("arts_dict", {"a": 1}), ("arts_str_rows", ["a.txt"]), ("arts_int", 7)):
        d = json.loads(json.dumps(man)); d["artifacts"] = bad
        assert m.main(["verify", _write(tmp_path, f"{label}.json", d), "--artifacts"]) == 4, label
        assert "INTEGRITY" in capsys.readouterr().out, label


def test_windows_device_names_and_nul_bytes_are_refused(tmp_path):
    """`open("NUL")` succeeds on Windows and reads as empty, so an artifact named NUL carrying the
    (publicly known) sha256 of b"" verified "ok" out of an EMPTY folder — a file that was never
    produced, certified as delivered. An embedded NUL byte instead raised ValueError, which the
    `except OSError` did not catch, crashing the CLI."""
    empty = tmp_path / "empty"; empty.mkdir()
    devices = {n: m.artifact_sha256(b"") for n in ("NUL", "CON", "com1", "LPT1", "nul.txt")}
    man = m.build_manifest({}, devices, [{"s": "a"}])
    res = m.verify_file(_write(tmp_path, "dev.json", man), artifacts_dir=str(empty))
    assert res["ok"] is False
    assert {a["state"] for a in res["artifacts"]} == {"INVALID"}, res["artifacts"]

    nb = m.build_manifest({}, {"evil\x00.txt": "0" * 64}, [{"s": "a"}])
    res = m.verify_file(_write(tmp_path, "nb.json", nb), artifacts_dir=str(tmp_path))
    assert res["ok"] is False and res["artifacts"][0]["state"] == "INVALID"


def test_a_bom_prefixed_manifest_is_not_a_false_alarm(tmp_path):
    """A manifest that merely passed through a Windows tool acquires a UTF-8 BOM. Rejecting that
    untampered file as unreadable is a false alarm at a client site - the expensive direction."""
    man = m.build_manifest({}, {}, [{"s": "a"}])
    p = tmp_path / "bom.run_manifest.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(man).encode("utf-8"))
    assert m.verify_file(str(p))["ok"] is True
