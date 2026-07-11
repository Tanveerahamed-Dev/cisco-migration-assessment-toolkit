"""P3-E2: the schema/script_version gate for --compare / --trend.

Diffing two snapshots produced by DIFFERENT engine schema versions can misreport a schema difference (a
renamed/moved field) as a real network change. The gate REFUSES that cross-schema diff by default;
--allow-schema-mismatch downgrades the refusal to a loud warning; an ABSENT version is 'unverifiable'
(warn, never silently 'ok' -- coverage-honest). Unit-tests the pure classifier + subprocess-tests the CLI
refuse/override/passthrough at the monolith boundary.
"""
import json
import os
import subprocess
import sys

from cisco_toolkit.precert import _schema_signature, schema_compat_status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONOLITH = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")


# --------------------------------------------------------------------- pure classifier
def test_same_script_version_is_ok():
    assert schema_compat_status([{"script_version": "V3.23.0"},
                                 {"script_version": "V3.23.0"}]) == ("ok", "")


def test_different_script_version_is_mismatch_names_both_and_is_ascii():
    status, msg = schema_compat_status(
        [{"script_version": "V3.23.0"}, {"script_version": "V3.30.0"}],
        labels=["old.json", "new.json"])
    assert status == "mismatch"
    assert "V3.23.0" in msg and "V3.30.0" in msg and "old.json" in msg and "new.json" in msg
    # the message is emitted to a Windows console (cp1252) -> it must be pure ASCII (no em-dash)
    assert msg.isascii(), f"schema-gate message must be ASCII for the cp1252 CI fleet: {msg!r}"


def test_absent_version_is_unverifiable_not_mismatch():
    status, msg = schema_compat_status([{"script_version": "V3.23.0"}, {}])
    assert status == "unverifiable"
    assert "script_version" in msg and msg.isascii()


def test_schema_version_dimension_also_gates():
    status, _ = schema_compat_status([{"script_version": "V3.23.0", "schema_version": "a"},
                                      {"script_version": "V3.23.0", "schema_version": "b"}])
    assert status == "mismatch"


def test_trend_series_same_is_ok_one_odd_is_mismatch():
    assert schema_compat_status([{"script_version": "V3.23.0"}] * 4)[0] == "ok"
    assert schema_compat_status([{"script_version": "V3.23.0"},
                                 {"script_version": "V3.23.0"},
                                 {"script_version": "V3.99.9"}])[0] == "mismatch"


def test_total_on_malformed_input():
    assert _schema_signature(None) == ("", "")
    assert _schema_signature(42) == ("", "")
    assert schema_compat_status([]) == ("ok", "")            # nothing to mismatch
    assert schema_compat_status([None, "x", 7])[0] == "unverifiable"


# --------------------------------------------------------------------- CLI gate (monolith boundary)
def _write(path, script_version, when):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"script_version": script_version, "generated_at": when, "devices": {}}, f)


def _compare(tmp_path, v_old, v_new, extra=()):
    old = os.path.join(str(tmp_path), "old.snapshot.json")
    new = os.path.join(str(tmp_path), "new.snapshot.json")
    _write(old, v_old, "2026-01-01T00:00:00")
    _write(new, v_new, "2026-02-01T00:00:00")
    out = os.path.join(str(tmp_path), "diff.xlsx")
    cmd = [sys.executable, MONOLITH, "--compare", old, new, "--output", out, *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return proc, out


def test_cli_compare_refuses_on_schema_mismatch(tmp_path):
    proc, out = _compare(tmp_path, "V3.23.0", "V9.9.9")
    blob = (proc.stdout + proc.stderr).lower()
    assert proc.returncode != 0, blob
    assert "schema" in blob and "allow-schema-mismatch" in blob
    assert not os.path.exists(out), "a refused diff must not write a workbook"


def test_cli_compare_proceeds_with_override(tmp_path):
    proc, out = _compare(tmp_path, "V3.23.0", "V9.9.9", extra=["--allow-schema-mismatch"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert os.path.exists(out), "override must let the diff proceed"


def test_cli_compare_matching_versions_proceeds_silently(tmp_path):
    proc, out = _compare(tmp_path, "V3.23.0", "V3.23.0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert os.path.exists(out)
    assert "[schema]" not in (proc.stdout + proc.stderr), "no schema warning on the matching-version path"


def test_cli_trend_refuses_on_schema_mismatch(tmp_path):
    a = os.path.join(str(tmp_path), "a.json")
    b = os.path.join(str(tmp_path), "b.json")
    _write(a, "V3.23.0", "2026-01-01T00:00:00")
    _write(b, "V9.9.9", "2026-02-01T00:00:00")
    out = os.path.join(str(tmp_path), "trend.xlsx")
    cmd = [sys.executable, MONOLITH, "--trend", a, b, "--output", out]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "schema" in (proc.stdout + proc.stderr).lower()
