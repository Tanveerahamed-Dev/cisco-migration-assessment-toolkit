"""Tier-3 #14 Phase-1: write the on-disk SNAPSHOT with compact JSON separators (a pure size win).

Provably byte-neutral for the contract: the golden harness and every `--compare`/webapp consumer
`json.load`s the snapshot and compares PARSED objects (tests/test_pipeline_golden.py:65,174), so the
byte formatting is invisible to them. Debug artifacts (run_manifest / phase_timings) stay indented.
"""
import json

from COLLECT_PARSE_V3_23_0 import write_json_file


def test_write_json_file_compact_vs_default(tmp_path):
    data = {"a": 1, "nested": {"x": [1, 2, 3], "y": "z"}, "list": [{"k": "v"}]}
    d = tmp_path / "default.json"
    c = tmp_path / "compact.json"
    write_json_file(str(d), data)                  # default: indented, human-readable (manifest/timings)
    write_json_file(str(c), data, compact=True)    # snapshot path: minified
    draw = d.read_text(encoding="utf-8")
    craw = c.read_text(encoding="utf-8")

    assert "\n  " in draw                          # default is still indented
    assert "\n" not in craw.rstrip("\n")           # compact is a single line
    assert ", " not in craw and ": " not in craw   # compact separators (no spaces)
    assert len(craw) < len(draw)                   # genuinely smaller
    # byte formatting is invisible to the contract: both round-trip to the SAME object
    assert json.loads(craw) == json.loads(draw) == data
