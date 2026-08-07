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
import sys
import zipfile
from pathlib import Path

import pytest

from cisco_toolkit.docmeta import CLI_ARTIFACT_SUFFIX, FAMILY, WEB_ONLY_KINDS, cli_artifacts

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "COLLECT_PARSE_V3_23_0.py"

# What a deliverable suffix LOOKS like. Extensions up to 8 chars and hyphens are allowed: pinning
# this to (docx|pptx|html) once made the ratchet blind to exactly the case it exists for — a future
# writer emitting `_board_brief.pdf` would never be mapped, never expected, and permanently outside
# the completeness check. `-` and the 8-char bound cost NOTHING (measured: all three shapes match
# the same 9 literals in the engine today) and cover `_board-brief.docx` (Cisco house naming) and
# `.drawio`/`.graphml`. The leading `_` is what excludes the engine's own sidecars, which are
# `.`-joined (`.snapshot.json`, `.run_manifest.json`, `.phase_timings.json`) — the length bound
# does no exclusion work, so widening it is free.
# NOT widened further: a shape tolerating a leading `{}`/`%s` was measured at 23 matches, sweeping
# in the sidecars, `command_index.json` and 7 `show_*.txt` collection filenames.
_SUFFIX_SHAPE = re.compile(r"^_[A-Za-z0-9_-]+\.[A-Za-z0-9]{2,8}$")


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

    KNOWN GAPS — the exact rule is: **only a suffix that appears verbatim in the engine file as ONE
    string Constant beginning with ``_`` is seen.** An earlier version of this docstring claimed a
    missed suffix "has no literal to find and is invisible to ANY source-level check". That was
    FALSE in both halves, and measured so; a ratchet narrower than its docstring is worse than none,
    because the docstring is what stops the next reader looking. What is actually missed:

    * ``"{}_board_brief.pdf".format(stem)`` and ``"%s_board_brief.pdf" % stem`` — the literal IS
      present, it just does not START with ``_``. NB the engine already builds filenames this way
      (``:1275`` ``tmp = "%s.%d.tmp" % (path, os.getpid())``), so this is not a strawman.
    * ``stem + ("_board_brief" + ".pdf")`` — split across two Constants; ``ast.parse`` does not
      constant-fold. (The *implicit* adjacent form ``"_board" "_brief.pdf"`` IS caught — the two
      spellings behave oppositely, which is worth knowing before you trust a near-miss.)
    * a suffix assembled fully at runtime (``stem + "_" + kind + ".docx"``) — no literal at all.
    * **a writer that lives outside this one file.** Only ``COLLECT_PARSE_V3_23_0.py`` is scanned,
      while writers have been migrating into ``cisco_toolkit/`` for several releases; a module that
      owns its own suffix constant (the ``capture_integrity.CAPTURE_META_FILENAME`` pattern) is
      invisible here. This is the likeliest way this ratchet goes stale.

    The durable fix is to invert the direction — give ``docmeta`` an ``artifact_path(stem, kind)``
    that every writer calls, so the map PRODUCES the filename instead of mirroring it, and every gap
    above disappears at once. Tracked as a follow-up; this file patches a mirror."""
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
    # The left-hand message deliberately does NOT say "not written by the engine". It cannot know
    # that: a writer whose filename this reconciler cannot see (see _suffixes_in KNOWN GAPS) lands
    # here even though the engine really does write it. Asserting the falsehood pointed the one
    # contributor who had done everything right — added the writer AND mapped it — at deleting the
    # map entry as the only way to green the suite, which manufactures exactly the unmapped,
    # unchecked deliverable this map exists to prevent.
    assert mapped == in_engine, (
        f"docmeta.CLI_ARTIFACT_SUFFIX and the engine source disagree.\n"
        f"  mapped, but NOT FOUND as a literal in the engine: {sorted(mapped - in_engine)}\n"
        f"    -> either the writer was removed (drop the map entry), OR it names its output in a\n"
        f"       way this reconciler cannot see. Check _suffixes_in's KNOWN GAPS first; if the\n"
        f"       engine really does write it, DO NOT delete the map entry to go green — widen the\n"
        f"       detector or add the file to the scanned set.\n"
        f"  found in the engine but unmapped: {sorted(in_engine - mapped)}\n"
        f"    -> a new deliverable: add it to CLI_ARTIFACT_SUFFIX (and FAMILY).")
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


def test_the_documented_gaps_are_the_REAL_gaps():
    """Pin the KNOWN GAPS list to actual behaviour.

    The first version of that docstring claimed a missed suffix "has no literal to find and is
    invisible to ANY source-level check" — false in both halves. Documentation of a limitation is
    itself a claim, and an unpinned one rots the same way a stale map does. If a future change
    makes one of these visible, this test fails and the docstring gets corrected WITH it."""
    missed = {
        "format":     'p = "{}_board_brief.pdf".format(stem)',
        "percent":    'p = "%s_board_brief.pdf" % stem',
        "split concat": 'p = stem + ("_board_brief" + ".pdf")',
        "runtime":    'p = stem + "_" + kind + ".docx"',
    }
    for label, code in missed.items():
        assert not _suffixes_in(code), (
            f"KNOWN GAPS says the {label} idiom is missed, but the detector now sees it — "
            f"good news: widen the docstring's gap list to match")
    # ...and the one that IS caught, whose opposite behaviour the docstring calls out
    assert _suffixes_in('p = stem + "_board" "_brief.pdf"'), \
        "implicit adjacent concatenation used to be caught; the docstring says so"


def test_the_widened_shape_costs_nothing_and_buys_something():
    """`-` and the 8-char extension bound were adopted only because they were measured free."""
    assert _suffixes_in('p = stem + "_board-brief.docx"'), "hyphenated house naming must be seen"
    assert _suffixes_in('p = stem + "_topology.drawio"'), "a 6-char extension must be seen"
    # the bound still has to exclude prose-y strings that are not filenames
    assert not _suffixes_in('x = "_x.toolongextension"')
    # and the leading `_` still does the sidecar exclusion, which is what keeps this tight
    for sidecar in (".snapshot.json", ".run_manifest.json", ".phase_timings.json"):
        assert not _suffixes_in(f'p = stem + "{sidecar}"'), f"{sidecar} is a sidecar, not a deliverable"


def test_the_failure_message_never_claims_the_engine_does_not_write_it(monkeypatch):
    """The highest-severity finding from review: the old message asserted 'not written by the
    engine' about a file the engine may well write, and the only way to green it was to delete the
    map entry — manufacturing the exact blind spot the map prevents.

    Checked by TRIGGERING the real failure and reading the real message, not by grepping this file.
    The first version grepped, and matched its own assertion string — a source-text check on the
    file that contains the banned phrase can never be anything but self-satisfying."""
    # A non-empty but INCOMPLETE result — the shape a real unseeable writer produces. (Returning
    # an empty set instead trips the earlier "naming shape changed" guard and never reaches the
    # message under test.)
    incomplete = {s for k, s in CLI_ARTIFACT_SUFFIX.items()
                  if k not in ("workbook", "design")}
    monkeypatch.setattr(sys.modules[__name__], "_engine_suffixes", lambda: incomplete)
    with pytest.raises(AssertionError) as excinfo:
        test_suffixes_match_what_the_engine_actually_writes()
    msg = str(excinfo.value)
    assert "not written by the engine" not in msg, \
        f"the reconciler asserts something it cannot know:\n{msg}"
    assert "NOT FOUND as a literal" in msg, "say what was actually observed"
    assert "DO NOT delete the map entry" in msg, \
        "the message must steer away from the destructive fix"


def test_structural_validator_rejects_partial_deliverables(tmp_path):
    from cisco_toolkit.docmeta import validate_artifact

    partial = tmp_path / "report.docx"
    partial.write_bytes(b"PK\x03\x04interrupted")
    ok, reason = validate_artifact(str(partial), "docx")
    assert ok is False and "invalid Office package" in reason

    torn = tmp_path / "assessment.snapshot.json"
    torn.write_text('{"interfaces":', encoding="utf-8")
    ok, reason = validate_artifact(str(torn), "snapshot")
    assert ok is False and "invalid JSON" in reason


def test_structural_validator_rejects_office_zip_with_malformed_required_xml(tmp_path):
    from cisco_toolkit.docmeta import validate_artifact

    broken = tmp_path / "looks-complete.xlsx"
    with zipfile.ZipFile(broken, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types>")
        zf.writestr("xl/workbook.xml", "<workbook/>")

    ok, reason = validate_artifact(str(broken), "xlsx")
    assert ok is False
    assert "invalid Office package" in reason


def test_structural_validator_accepts_real_workbook_and_exact_candidates(tmp_path):
    from openpyxl import Workbook
    from cisco_toolkit.docmeta import artifact_candidate_paths, validate_artifact

    path = tmp_path / "Assessment.xlsx"
    Workbook().save(path)
    assert validate_artifact(str(path), "xlsx")[0] is True

    names = {Path(p).name for p in artifact_candidate_paths(tmp_path / "Assessment")}
    assert "Assessment.xlsx" in names
    assert "Assessment.snapshot.json" in names
    assert "Assessment.phase_timings.json" in names
    assert "Assessment.run_manifest.json" in names
    assert {"topology.mmd", "topology.dot"} <= names


def _lc_snap(**summary):
    return {"devices": {f"sw{i}": {} for i in range(4)},
            "lifecycle_risk": {"summary": summary, "per_device": []}}


def test_at_a_glance_does_not_report_zero_past_ldos_when_the_answer_is_UNDETERMINED():
    """"0 device(s) past last-day-of-support" on the front page of EVERY deliverable.

    `ssot.CANONICAL_FACTS` carried slots for n_past_ldos / n_past_eos / n_near / n_active and NONE
    for n_unknown, so no consumer had a path to say "not determined" — `v()` maps only `None` to
    `[NOT OBSERVED]`, and a real `0` passes straight through. A fleet whose every platform is
    unmatched by the offline EoX KB therefore led with a clean zero on the first page a customer
    reads.

    Same class as the LC-1 verdict (handoff §7.22) and the reason that one was not enough: fixing the
    instance is not fixing the class.
    """
    from cisco_toolkit import docmeta
    rows = dict(docmeta._glance_rows(_lc_snap(n_past_ldos=0, n_past_eos=0, n_near=0, n_unknown=4)))
    lifecycle = rows["Biggest lifecycle exposure?"]
    # Assert the PROPERTY (the undetermined population is disclosed, with its size), not one
    # phrasing — a wording check would go red on an editorial pass that changed nothing that matters.
    low = lifecycle.lower()
    assert "4" in lifecycle and any(w in low for w in
                                    ("not assessed", "undetermined", "unknown", "not determined")), (
        f"the front page reports a bare zero while 4 device(s) were never assessed: {lifecycle!r}"
    )


def test_at_a_glance_still_reads_clean_when_every_device_WAS_assessed():
    """Non-vacuity: a genuinely clean, fully-assessed fleet must not gain a scary caveat."""
    from cisco_toolkit import docmeta
    rows = dict(docmeta._glance_rows(_lc_snap(n_past_ldos=0, n_past_eos=0, n_near=0, n_unknown=0)))
    lifecycle = rows["Biggest lifecycle exposure?"]
    assert "unknown" not in lifecycle.lower(), f"clean fleet gained an unknown caveat: {lifecycle!r}"
    assert "0 device(s) past last-day-of-support" in lifecycle


def test_at_a_glance_partial_lifecycle_summary_discloses_missing_coverage_count():
    """Published zero adverse counts are not a clean result when n_unknown itself was omitted."""
    from cisco_toolkit import docmeta
    rows = dict(docmeta._glance_rows(_lc_snap(n_past_ldos=0, n_past_eos=0, n_near=0)))
    lifecycle = rows["Biggest lifecycle exposure?"]
    assert "lifecycle coverage count [NOT OBSERVED]" in lifecycle
    assert "did not publish n_unknown" in lifecycle
