"""docmeta.CLI_ARTIFACT_SUFFIX — what a COMPLETE engine CLI run leaves on disk.

Atlas's `--redact-folder` diffs produced-against-expected to tell the field engineer when the
share-safe set is SHORT (every engine writer is fail-soft: it logs a warning and continues, so a
run that rendered 13 of 15 files still exits 0). That check is only as honest as this map, and the
map is exactly the kind of hand-maintained list that rots as deliverables accrete — the engine's
own `--no-*` flag list had already gone stale that way (V3.23.170).

So the map is reconciled against the ENGINE SOURCE here: a renamed suffix or a newly added writer
fails the suite instead of quietly widening the blind spot it was written to close. No python-docx
dependency — this is a source-level contract and must run everywhere.
"""
import re
from pathlib import Path

from cisco_toolkit.docmeta import CLI_ARTIFACT_SUFFIX, FAMILY, WEB_ONLY_KINDS, cli_artifacts

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"

# Every engine deliverable is named `os.path.splitext(os.path.abspath(out_xlsx))[0] + "<suffix>"`.
# ANY extension: pinning this to (docx|pptx|html) made the ratchet blind to exactly the case it
# exists for — a future writer emitting `_board_brief.pdf` would have been invisible to the regex,
# so it would never be mapped, never expected, and permanently outside the completeness check.
# The leading `_` is what distinguishes a deliverable from the engine's own sidecars, which are
# `.`-joined (`.snapshot.json`, `.run_manifest.json`, `.phase_timings.json`).
_ENGINE_SUFFIX = re.compile(r'out_xlsx\)\)\[0\] \+ "(_[A-Za-z0-9_]+\.[A-Za-z0-9]{2,5})"')


def test_every_family_kind_is_classified():
    """A new FAMILY entry is either produced by the engine CLI (mapped) or rendered by AssessHub's
    web layer (declared web-only). Leaving it unclassified would silently exempt it from the
    completeness check — the failure mode this whole map exists to prevent."""
    keys = {key for key, _name, _role in FAMILY}
    mapped = set(CLI_ARTIFACT_SUFFIX)
    assert mapped | set(WEB_ONLY_KINDS) == keys, (
        f"unclassified family kind(s): {sorted(keys - mapped - set(WEB_ONLY_KINDS))}; add a suffix "
        f"to CLI_ARTIFACT_SUFFIX or declare it in WEB_ONLY_KINDS")
    assert not (mapped & set(WEB_ONLY_KINDS)), "a kind cannot be both engine-produced and web-only"


def test_suffixes_match_what_the_engine_actually_writes():
    """The load-bearing reconciliation. `workbook` is the --output path itself, so it has no
    suffix line in the engine; every OTHER mapped kind must correspond to a real writer, and every
    writer the engine has must be mapped."""
    in_engine = set(_ENGINE_SUFFIX.findall(ENGINE.read_text(encoding="utf-8", errors="replace")))
    assert in_engine, "the engine's artifact-naming shape changed — update this reconciler"
    mapped = {s for k, s in CLI_ARTIFACT_SUFFIX.items() if k != "workbook"}
    assert mapped == in_engine, (
        f"docmeta.CLI_ARTIFACT_SUFFIX has drifted from the engine writers.\n"
        f"  mapped but not written by the engine: {sorted(mapped - in_engine)}\n"
        f"  written by the engine but unmapped:   {sorted(in_engine - mapped)}")
    assert CLI_ARTIFACT_SUFFIX["workbook"] == ".xlsx"


def test_the_two_web_only_kinds_have_no_engine_writer():
    """Cutover and NRFU render in AssessHub from a stored snapshot. If the engine ever grows a
    writer for one, a CLI run stops being complete without it and the map must say so."""
    src = ENGINE.read_text(encoding="utf-8", errors="replace")
    assert WEB_ONLY_KINDS == {"cutover", "nrfu"}
    for key in WEB_ONLY_KINDS:
        assert f'"_{key}.docx"' not in src, f"the engine now writes {key} — map it instead"


def test_cli_artifacts_returns_basenames_in_family_order():
    got = cli_artifacts("/tmp/share/Assessment_redacted")
    assert [k for k, _n, _f in got] == [k for k, _n, _r in FAMILY if k in CLI_ARTIFACT_SUFFIX]
    names = [f for _k, _n, f in got]
    assert "Assessment_redacted.xlsx" in names
    assert "Assessment_redacted_ops_handbook.docx" in names
    assert all("/" not in f and "\\" not in f for f in names), "must be basenames, not paths"
    # Windows separators resolve too — the caller passes a native path stem.
    assert cli_artifacts(r"D:\share\Assessment_redacted") == got
