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
import ast
import re
from pathlib import Path

from cisco_toolkit.docmeta import CLI_ARTIFACT_SUFFIX, FAMILY, WEB_ONLY_KINDS, cli_artifacts

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"

# What a deliverable suffix LOOKS like. ANY extension: pinning this to (docx|pptx|html) once made
# the ratchet blind to exactly the case it exists for — a future writer emitting `_board_brief.pdf`
# would never be mapped, never expected, and permanently outside the completeness check. The
# leading `_` is what distinguishes a deliverable from the engine's own sidecars, which are
# `.`-joined (`.snapshot.json`, `.run_manifest.json`, `.phase_timings.json`).
_SUFFIX_SHAPE = re.compile(r"^_[A-Za-z0-9_]+\.[A-Za-z0-9]{2,5}$")


def _engine_suffixes() -> set:
    """Every deliverable suffix the engine names, found over the AST rather than the source TEXT.

    This replaced a regex pinned to one spelling of the write —
    ``out_xlsx))[0] + "<suffix>"``. That regex reconciled the map correctly for every writer that
    happened to use that exact idiom, and was **structurally unable to see any other**: hoisting the
    stem into a local first (``stem = os.path.splitext(...)[0]`` … ``stem + "_x.pdf"``) is what an
    ordinary cleanup produces, and a writer added that way would have passed this ratchet while
    sitting permanently outside the completeness check — the same silent-degrade class the map
    exists to close. Verified before replacing it: the regex matches the current idiom and does NOT
    match the hoisted form.

    Matching a LITERAL rather than a dataflow path is deliberate. It is idiom-independent (concat,
    hoisted stem, f-string, ``os.path.join``, ``Path.with_name`` all resolve), and it errs toward
    over-detection: a suffix-shaped literal that is NOT a deliverable fails this test loudly and
    gets classified, which is the safe direction for a ratchet whose only real failure mode is
    being too narrow. As of this writing over-detection is zero — every suffix-shaped literal in
    the engine is a deliverable.

    KNOWN GAP, stated rather than papered over: a suffix assembled at runtime
    (``stem + "_" + kind + ".docx"``) has no literal to find and is invisible to ANY source-level
    check, this one included. Nothing in the engine does that today. If a writer ever needs to,
    the map must be updated by hand and this docstring is where the next reader learns why the
    ratchet did not catch it."""
    return _suffixes_in(ENGINE.read_text(encoding="utf-8", errors="replace"))


def _suffixes_in(source: str) -> set:
    """THE detection rule — ONE implementation, shared by the reconciler above and the idiom tests
    below.

    Deliberately not duplicated. The first version of this file defined the rule inline in
    ``_engine_suffixes()`` and a copy of it in the test helper; reverting the real one to the old
    regex then left all seven tests GREEN, because the tests were exercising the copy. A test that
    asserts against its own reimplementation of the thing under test pins nothing — it cannot fail
    when the thing changes. Caught by revert-proof; the fix is this single owner."""
    return {n.value for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and _SUFFIX_SHAPE.match(n.value)}


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
    in_engine = _engine_suffixes()
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
    assert WEB_ONLY_KINDS == {"cutover", "nrfu"}
    # Over the AST for the same reason as above: the old substring test (`f'"_{key}.docx"' not in
    # src`) was pinned to double quotes AND to `.docx`, so a single-quoted literal or a
    # `_cutover.pdf` writer would have slipped past it.
    written = _engine_suffixes()
    for key in WEB_ONLY_KINDS:
        clash = {s for s in written if s.startswith(f"_{key}.")}
        assert not clash, f"the engine now writes {key} ({sorted(clash)}) — map it instead"


def test_cli_artifacts_returns_basenames_in_family_order():
    got = cli_artifacts("/tmp/share/Assessment_redacted")
    assert [k for k, _n, _f in got] == [k for k, _n, _r in FAMILY if k in CLI_ARTIFACT_SUFFIX]
    names = [f for _k, _n, f in got]
    assert "Assessment_redacted.xlsx" in names
    assert "Assessment_redacted_ops_handbook.docx" in names
    assert all("/" not in f and "\\" not in f for f in names), "must be basenames, not paths"
    # Windows separators resolve too — the caller passes a native path stem.
    assert cli_artifacts(r"D:\share\Assessment_redacted") == got


def test_the_detector_sees_writes_a_source_regex_cannot():
    r"""Non-vacuity for the AST rewrite itself: prove it catches what the old regex missed.

    The regex was `out_xlsx\)\)\[0\] \+ "(_...)"`. It matched only the one spelling. Each idiom
    below is a realistic way to add a writer, and each was invisible to it — so a deliverable added
    that way would have been silently exempt from the completeness check. A ratchet narrower than
    its docstring is worse than none, because the docstring is what stops the next reader looking."""
    for label, code in (
            ("current idiom",
             'p = os.path.splitext(os.path.abspath(out_xlsx))[0] + "_design.docx"'),
            ("hoisted stem",
             'stem = os.path.splitext(os.path.abspath(out_xlsx))[0]\np = stem + "_board_brief.pdf"'),
            ("f-string", 'p = f"{stem}_board_brief.pdf"'),
            ("os.path.join", 'p = os.path.join(d, base + "_board_brief.pdf")'),
            ("pathlib with_name", 'p = Path(out_xlsx).with_name(base + "_board_brief.pdf")'),
            ("single quotes", "p = stem + '_board_brief.pdf'"),
    ):
        assert _suffixes_in(code), f"detector missed a {label} write — it would go unmapped"


def test_the_detector_does_not_fire_on_sidecars_or_ordinary_strings():
    """The other edge. A ratchet that flags everything gets suppressed, so the shape has to be
    tight enough to leave the engine's own sidecars and normal strings alone."""
    for code in ('p = stem + ".snapshot.json"', 'p = stem + ".run_manifest.json"',
                 'p = stem + ".phase_timings.json"', 'x = "_internal"', 'x = "collected_at"',
                 'x = "a.b"', 'x = "_x.toolongextension"'):
        assert not _suffixes_in(code), f"detector over-fires on {code!r}"


def test_over_detection_is_currently_zero():
    """Every suffix-shaped literal in the engine is a real deliverable, so the broad rule costs
    nothing today. If this ever fails, a non-deliverable literal has taken that shape: classify it
    (map it, or exclude it here with a reason) rather than narrowing the detector back down."""
    assert _engine_suffixes() == {s for k, s in CLI_ARTIFACT_SUFFIX.items() if k != "workbook"}
