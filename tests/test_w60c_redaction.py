"""W60c residuals: synthetic grammar probes and exact hosted archival custody.

The earlier W60/W60b suites and fixtures remain unchanged. This suite activates
the retained deferred schematic assertions and adds fresh EXAMPLE cases. Real
Git archives and persisted-view oracles are mandatory in every hosted job that
collects this module. Nothing regenerates a repository artifact.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from cisco_toolkit import html
import test_w60b_redaction as w60b


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/w60c_redaction_corpus.json"
CORPUS = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CURRENT_MAIN = "0dc2f5d6f4d122ef74f8098e173e2be0bc2c902f"
LATEST_MAIN = "dbcc2c81a6fdf29ec958b610c8f8f3c060c171b3"
ROUND3 = "d05ff1aaea85d87ff474f3a9d425eeacfa99a10c"
PRE_P26 = "8b9cf50566649fac97c954beb26411a450dbb93d"
ROWS = CORPUS["rows"]
FINDINGS = frozenset({"P1-3", "P1-4", "P2-5", "P2-6"})
ACTIVE_FINDINGS = FINDINGS - {"P2-6"}
VIEW_FIXES = FINDINGS | {"P2-5-carrier", "P2-5-operand-boundary", "P2-6-defer-revert",
                        "P1-4-continuation-closure", "P2-5-decoded-carrier"}
_HISTORICAL_FINDINGS = frozenset({"R4-P1-directive", "R4-P1-prefix", "R4-P2-executable", "R4-P2-field"})
HISTORICAL_ROWS = [row for row in w60b.ROWS if row["id"].startswith("r4:")
                   and row["finding"] in _HISTORICAL_FINDINGS]
VERIFIER_CONTROLS = CORPUS["verifier_only_controls"]
HISTORICAL_VERIFIER_CONTROLS = [row for row in w60b.CORPUS["verifier_only_controls"]
                               if row.get("finding") in _HISTORICAL_FINDINGS]
ACTIVE_ROWS = [row for row in ROWS if row["finding"] in ACTIVE_FINDINGS]
ACTIVE_HISTORICAL_ROWS = [row for row in HISTORICAL_ROWS if row["finding"] != "R4-P2-field"]
DEFERRED_ROWS = [row for row in ROWS if row["finding"] == "P2-6"]
DEFERRED_HISTORICAL_ROWS = [row for row in HISTORICAL_ROWS if row["finding"] == "R4-P2-field"]
ACTIVE_VERIFIER_CONTROLS = [row for row in VERIFIER_CONTROLS if row["finding"] in ACTIVE_FINDINGS]
ACTIVE_HISTORICAL_VERIFIER_CONTROLS = [row for row in HISTORICAL_VERIFIER_CONTROLS if row["finding"] != "R4-P2-field"]
DEFERRED_VERIFIER_CONTROLS = [row for row in VERIFIER_CONTROLS if row["finding"] == "P2-6"]
DEFERRED_HISTORICAL_VERIFIER_CONTROLS = [row for row in HISTORICAL_VERIFIER_CONTROLS if row["finding"] == "R4-P2-field"]


_COMMENT_AUTH_HEADER_RE = re.compile(
    r"""^[ \t]*(?P<marker>//|!)[ \t]*(?P<quote>["']?)(?:proxy-)?authorization(?P=quote)[ \t]*:[ \t]*"""
    r"""(?:<redacted>|[A-Za-z][A-Za-z0-9!#$%&*+.^_`|~-]*)?[ \t]*$""", re.IGNORECASE)
_LEXICAL_BLOCK_RE = re.compile(r"[\w./-]")


def _slot_count(secret, text):
    """Keep legacy exact-token boundaries; a proven comment prefix delimits its value.

    A direct dangling Authorization/Proxy-Authorization comment header establishes
    provenance for the next nonblank line. Only the same physical leading marker,
    immediately followed by the complete declared secret, supplies the additional
    left boundary. Word, path and IP suffix boundaries remain unchanged.
    """
    assert secret, "a declared private slot must have nonempty exact bytes"
    count = w60b._slot_count(secret, text)
    previous_header = None
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if previous_header is not None and previous_header.group("marker") == "//":
            prefix = re.match(r"[ \t]*//", content)
            if prefix is not None:
                start = offset + prefix.end()
                end = start + len(secret)
                if (text.startswith(secret, start)
                        and (end == len(text) or not _LEXICAL_BLOCK_RE.match(text[end]))):
                    count += 1
        if content.strip():
            previous_header = _COMMENT_AUTH_HEADER_RE.fullmatch(content)
        offset += len(line)
    return count


@pytest.mark.parametrize("secret,text,count", [
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n//EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n//<redacted>\n", 0),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n<redacted> EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n<redacted>EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "//Authorization: <redacted>\n//EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "// 'Proxy-Authorization': Basic\n//EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "!Authorization: Bearer\n!EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "//Authorization:\n\n//EXAMPLE-COUNT-901\n", 1),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n//EXAMPLE-COUNT-901/path\n", 0),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer\n//EXAMPLE-COUNT-901-longer\n", 0),
    ("EXAMPLE-COUNT-901", "//EXAMPLE-COUNT-901\n", 0),
    ("EXAMPLE-COUNT-901", "// EXAMPLE-note Authorization: Bearer\n//EXAMPLE-COUNT-901\n", 0),
    ("EXAMPLE-COUNT-901", "//Content-Length: 5\n//EXAMPLE-COUNT-901\n", 0),
    ("EXAMPLE-COUNT-901", "//Authorization: Bearer EXAMPLE-OTHER\n//EXAMPLE-COUNT-901\n", 0),
    ("EXAMPLE-COUNT-901", "!Authorization: Bearer\n//EXAMPLE-COUNT-901\n", 0),
    ("3", "//Authorization: Bearer\n//192.0.2.3\n", 0),
    ("3", "192.0.2.3/path/3\n", 0),
    ("3", "12345\n", 0),
], ids=[
    "adjacent-private", "private-masked", "only-prefix-masked", "only-prefix-masked-joined",
    "canonical-header-private", "quoted-proxy-header", "adjacent-bang", "empty-header-blank-carry",
    "no-path-substring", "no-longer-token-substring", "no-unc-path-promotion",
    "no-prose-provenance", "no-response-header-provenance", "no-complete-header-continuation",
    "no-mismatching-marker-provenance", "no-ip-component", "no-path-component", "no-digit-substring",
])
def test_w60c_exact_private_counter_preserves_boundaries_and_detects_prefix_only_masks(secret, text, count):
    assert _slot_count(secret, text) == count


def test_w60c_round2_retains_exact_reviewer_schematics_and_independent_variants():
    rows = [row for row in ROWS if row["id"].startswith("r2:")]
    assert len(rows) == 34 and sum(row["mode"] == "must_redact" for row in rows) == 24
    exact = {row["id"]: row for row in rows if row["id"].startswith("r2:review-")}
    assert exact["r2:review-shell-executable"]["text"] == (
        "s'h' -c \"snmp''get -c EXAMPLE-PRIVATE EXAMPLE-HOST\"\n")
    assert exact["r2:review-shell-executable"]["expect"] == "s'h' -c \"<redacted>\"\n"
    assert exact["r2:review-shell-option"]["text"] == (
        "sh -'c' \"snmp''get -'c' EXAMPLE-PRIVATE EXAMPLE-HOST\"\n")
    assert exact["r2:review-shell-option"]["expect"] == "sh -'c' \"<redacted>\"\n"
    assert sum(row["id"].startswith("r2:carrier-") for row in rows) == 22
    assert sum(row["id"].startswith("r2:control-") for row in rows) == 10
    assert all(row["review"] == "PR660-comment6119252180" for row in rows)
    assert CORPUS["round2_review"]["comment_id"] == 6119252180
    assert CORPUS["round2_review"]["independently_authored_private_variants"] == 22


def test_w60c_corpus_has_each_scoped_family_and_fresh_positive_negative_controls():
    assert CORPUS["current_main_ref"] == CURRENT_MAIN and CORPUS["round3_ref"] == ROUND3
    assert CORPUS["latest_main_ref"] == LATEST_MAIN
    assert set(CORPUS["scope"]) == set(CORPUS["scope_requested"]) == FINDINGS
    assert set(CORPUS["active_scope"]) == ACTIVE_FINDINGS and CORPUS["values_policy"]
    deferred = {row["finding"]: row for row in CORPUS["deferred"]}
    assert set(deferred) == {"P3-7", "P2-6"}
    assert deferred["P2-6"]["source_revert_ref"] == CORPUS["fix_commit_refs"]["P2-6-defer-revert"]
    assert deferred["P2-6"]["owner_decision"] and deferred["P2-6"]["reason"]
    residual = [row for row in w60b.ROWS if row["id"] == deferred["P3-7"]["immutable_legacy_row"]]
    assert len(residual) == 1 and "hostname <redacted>" in residual[0]["expect"]
    assert len({row["id"] for row in ROWS}) == len(ROWS)
    assert len(ROWS) == 188 and sum(row["mode"] == "must_redact" for row in ROWS) == 136
    assert len(VERIFIER_CONTROLS) == 7 and len(HISTORICAL_ROWS) == 18 and len(HISTORICAL_VERIFIER_CONTROLS) == 6
    assert len(ACTIVE_ROWS) == 160 and len(ACTIVE_HISTORICAL_ROWS) == 13
    assert len(DEFERRED_ROWS) == 28 and len(DEFERRED_HISTORICAL_ROWS) == 5
    assert len(ACTIVE_VERIFIER_CONTROLS) == 5 and len(ACTIVE_HISTORICAL_VERIFIER_CONTROLS) == 5
    assert len(DEFERRED_VERIFIER_CONTROLS) == 2 and len(DEFERRED_HISTORICAL_VERIFIER_CONTROLS) == 1
    for finding in FINDINGS:
        assert any(row["finding"] == finding and row["mode"] == "must_redact" for row in ROWS)
        assert any(row["finding"] == finding and row["mode"] == "must_keep" for row in ROWS)
    prior = {case["text"].strip() for case in w60b._all_differential_cases()}
    prior.update(row["text"].strip() for row in w60b.CORPUS["verifier_only_controls"])
    prior.update(row["clean_header"].strip() for row in w60b.CORPUS["verifier_only_controls"] if "clean_header" in row)
    assert len({row["text"].strip() for row in ROWS}) == len(ROWS)
    assert not prior.intersection(row["text"].strip() for row in ROWS), "a new source input reuses old evidence"
    assert set(row["finding"] for row in HISTORICAL_ROWS) == _HISTORICAL_FINDINGS
    assert set(row["finding"] for row in HISTORICAL_VERIFIER_CONTROLS) == _HISTORICAL_FINDINGS
    for row in ROWS:
        assert row["mode"] in {"must_redact", "must_keep"} and row["note"]
        if row["mode"] == "must_redact":
            assert row["expect"] and row["secrets"]
            assert all(_slot_count(secret, row["text"]) for secret in row["secrets"]), row["id"]
    for row in VERIFIER_CONTROLS:
        assert row["secrets"] and all(_slot_count(secret, row["text"]) for secret in row["secrets"]), row["id"]
    probes = CORPUS["source_review_probe_inputs"]
    assert len(probes) == 1 and probes[0]["id"] == "source-review:raw-known-creator-marker-alias"
    assert probes[0]["status"] and "expect" not in probes[0]
    assert probes[0]["secrets"] and all(_slot_count(secret, probes[0]["text"]) for secret in probes[0]["secrets"])


@pytest.mark.parametrize("row", ACTIVE_ROWS + ACTIVE_HISTORICAL_ROWS, ids=lambda row: row["id"])
def test_w60c_real_producer_and_independent_verifier(row, tmp_path):
    capture = w60b._capture(tmp_path, row["text"])
    raw_proof = w60b._verify(tmp_path)
    result = html.redact_collection_dir(str(tmp_path))
    output = capture.read_bytes().decode("utf-8", "surrogateescape")
    assert result[0] == 1 and not result.uncovered, (row["id"], result)
    if row["mode"] == "must_keep":
        assert raw_proof["accepted"], (row["id"], raw_proof)
        assert result[1] == 0 and output == row["text"], (row["id"], output)
    else:
        assert not raw_proof["accepted"], ("raw private operand certified", row["id"], raw_proof)
        assert result[1] == 1, (row["id"], result)
        for secret in row["secrets"]:
            assert _slot_count(secret, output) < _slot_count(secret, row["text"]), (
                row["id"], "required private value survives", secret, output)
        assert output == row["expect"], (row["id"], "lost public structure or private coverage", output)
        for structural in row["structural"]:
            assert structural in output, (row["id"], structural, output)
    proof = w60b._verify(tmp_path)
    assert proof["accepted"], (row["id"], proof, output)
    assert proof["proof"]["files"] == 1 and proof["proof"]["uncovered"] == []
    second = html.redact_collection_dir(str(tmp_path))
    assert second == (1, 0) and not second.uncovered
    assert capture.read_bytes().decode("utf-8", "surrogateescape") == output


@pytest.mark.parametrize("row", ACTIVE_VERIFIER_CONTROLS + ACTIVE_HISTORICAL_VERIFIER_CONTROLS,
                         ids=lambda row: row["id"])
def test_w60c_independent_raw_refusal_and_nonvacuous_clean_control(row, tmp_path):
    assert row["expect_refusal"] is True
    if "clean_header" in row:
        clean = w60b._capture(tmp_path, row["clean_header"])
        clean_proof = w60b._verify(tmp_path)
        assert clean_proof["accepted"], (row["id"], "clean owner control was refused", clean_proof)
        assert clean_proof["proof"]["files"] == 1 and clean_proof["proof"]["uncovered"] == []
        assert clean.read_bytes() == row["clean_header"].encode("utf-8")
    capture = w60b._capture(tmp_path, row["text"])
    proof = w60b._verify(tmp_path)
    assert not proof["accepted"], (row["id"], "private continuation/scalar was certified", proof)
    assert "residue" in proof["error"], (row["id"], proof)
    assert capture.read_bytes() == row["text"].encode("utf-8"), "read-only verifier changed source"


def _all_differential_cases():
    cases = w60b._all_differential_cases()
    for row in w60b.CORPUS["verifier_only_controls"]:
        cases.append({"id": "w60b-refusal:" + row["id"], "text": row["text"], "secrets": row.get("secrets", [])})
        if "clean_header" in row:
            cases.append({"id": "w60b-refusal-clean:" + row["id"], "text": row["clean_header"], "secrets": []})
    cases.extend({"id": "w60c:" + row["id"], "text": row["text"], "secrets": row["secrets"]} for row in ROWS)
    cases.extend({"id": "w60c-refusal:" + row["id"], "text": row["text"], "secrets": row.get("secrets", [])}
                 for row in VERIFIER_CONTROLS)
    cases.extend({"id": "w60c-review-probe:" + row["id"], "text": row["text"], "secrets": row["secrets"]}
                 for row in CORPUS["source_review_probe_inputs"])
    assert len({case["id"] for case in cases}) == len(cases)
    return cases


@pytest.mark.parametrize("row", [row for row in ROWS if row["id"] in {
    "prefix:prose-before-header", "prefix:bang-prose-before-proxy-header"}], ids=lambda row: row["id"])
def test_w60c_comment_prose_cannot_create_direct_header_provenance(row):
    for state in (html._redact_dangle(row["text"].rstrip("\n")),
                  w60b.rv._sweep_dangle(row["text"].rstrip("\n"))):
        assert state is None or not any(item.startswith("comment:") for item in state[1]), (row["id"], state)


@pytest.fixture(scope="module")
def archival_replay(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("w60c-archives")
    assert not scratch.resolve().is_relative_to(ROOT.resolve()), "archives must be outside the repository"
    cases = _all_differential_cases()
    case_path = scratch / "cases.json"
    case_path.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8")
    fix_refs = CORPUS["fix_commit_refs"]
    assert set(fix_refs) == VIEW_FIXES and len(set(fix_refs.values())) == len(VIEW_FIXES), (
        "every separately authored finding fix must have an immutable full-view oracle", fix_refs)
    assert all(len(ref) == 40 and all(char in "0123456789abcdef" for char in ref) for ref in fix_refs.values())
    for ref in fix_refs.values():
        subprocess.run(["git", "merge-base", "--is-ancestor", ref, "HEAD"], cwd=ROOT, check=True, timeout=30)
    archive_refs = list(dict.fromkeys([CURRENT_MAIN, LATEST_MAIN, ROUND3, *fix_refs.values()]))
    sources = {ref: w60b._archive(ref, scratch) for ref in archive_refs}
    sources["candidate"] = ROOT
    results = {}
    for ref in (CURRENT_MAIN, LATEST_MAIN, ROUND3, "candidate"):
        output_path = scratch / (ref + ".json")
        subprocess.run([sys.executable, "-I", "-B", "-c", w60b._BATCH_SCRIPT, str(sources[ref]), str(case_path),
                        str(scratch / (ref + "-captures")), str(output_path)],
                       cwd=scratch, check=True, timeout=300)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(result) == len(cases) and {row["id"] for row in result} == {case["id"] for case in cases}
        results[ref] = {row["id"]: row for row in result}
    return cases, results, sources, scratch


@pytest.mark.parametrize("ref", [CURRENT_MAIN, LATEST_MAIN, ROUND3],
                         ids=["original-main-0dc2f5d6", "latest-main-dbcc2c81", "round3"])
def test_w60c_all_legacy_and_fresh_cases_have_zero_archive_regressions(ref, archival_replay):
    cases, results, _sources, _scratch = archival_replay
    removed_slots = 0
    certified_baselines = 0
    regressions = []
    for case in cases:
        baseline = results[ref][case["id"]]
        candidate = results["candidate"][case["id"]]
        for secret in case["secrets"]:
            raw_count = _slot_count(secret, case["text"])
            baseline_count = _slot_count(secret, baseline["output"])
            if baseline_count < raw_count:
                removed_slots += 1
                if _slot_count(secret, candidate["output"]) > baseline_count:
                    regressions.append({"id": case["id"], "kind": "secret survives", "secret": secret,
                                        "baseline": baseline["output"], "candidate": candidate["output"]})
        if baseline["verifier"]["accepted"]:
            certified_baselines += 1
            if not candidate["verifier"]["accepted"]:
                regressions.append({"id": case["id"], "kind": "scrub certification lost",
                                    "candidate": candidate["output"], "verifier": candidate["verifier"]})
    assert removed_slots >= 800 and certified_baselines >= 800, ("vacuous archival replay", ref, removed_slots)
    print(json.dumps({"w60c_ref": ref, "cases": len(cases), "removed_secret_slots_checked": removed_slots,
                      "baseline_certifications_checked": certified_baselines, "regressions": len(regressions)}))
    assert regressions == [], json.dumps(regressions, ensure_ascii=True, indent=2)


def test_w60c_archived_candidate_strict_case_postconditions(archival_replay):
    _cases, results, _sources, _scratch = archival_replay
    for row in ACTIVE_ROWS:
        receipt = results["candidate"]["w60c:" + row["id"]]
        assert receipt["verifier"]["accepted"] and receipt["idempotent"], (row["id"], receipt)
        assert receipt["uncovered"] == [] and receipt["second_counts"] == [1, 0], (row["id"], receipt)
        if row["mode"] == "must_redact":
            assert not receipt["raw_verifier"]["accepted"] and receipt["output"] == row["expect"], (row["id"], receipt)
        else:
            assert receipt["raw_verifier"]["accepted"] and receipt["output"] == row["text"], (row["id"], receipt)


def test_w60c_inherited_source_review_probe_emits_runtime_evidence(archival_replay):
    """Expose an inherited boundary without inventing a P2-5 closure oracle.

    The unchanged main/round3 differential above owns every removal and
    certification floor; this receipt makes both survival and certification
    visible even when the same behavior exists on an immutable baseline.
    """
    _cases, results, _sources, _scratch = archival_replay
    for probe in CORPUS["source_review_probe_inputs"]:
        for ref in (CURRENT_MAIN, LATEST_MAIN, ROUND3, "candidate"):
            result = results[ref]["w60c-review-probe:" + probe["id"]]
            raw_count = sum(_slot_count(secret, probe["text"]) for secret in probe["secrets"])
            remaining = sum(_slot_count(secret, result["output"]) for secret in probe["secrets"])
            assert raw_count > 0 and 0 <= remaining <= raw_count
            print(json.dumps({"source_review_probe": probe["id"], "ref": ref,
                              "input_private_occurrences": raw_count, "private_occurrences_remaining": remaining,
                              "declared_private_survives": remaining > 0,
                              "raw_certified": result["raw_verifier"]["accepted"],
                              "post_scrub_certified": result["verifier"]["accepted"],
                              "producer_uncovered_count": len(result["uncovered"]),
                              "verifier_uncovered_count": len(result["verifier"]["proof"]["uncovered"])
                              if result["verifier"]["accepted"] else None,
                              "idempotent": result["idempotent"]}))


def test_w60c_each_finding_fix_and_final_head_keep_exact_main_views(archival_replay):
    _cases, _results, sources, scratch = archival_replay
    protected_prefixes = ("tests/golden/", "webapp/frontend/dist/", "atlas-scope/dist-hub/")
    protected_files = {"webapp/sample_data/sample_fleet.snapshot.json", "atlas-scope/src/data/fabric.json"}
    changes = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", CURRENT_MAIN, "HEAD"],
                                      cwd=ROOT).decode().splitlines()
    moved = [path for path in changes if path.startswith(protected_prefixes) or path in protected_files]
    assert moved == [], ("STOP: W60c would move a persisted output; no import or regeneration", moved)
    expected_entries = subprocess.check_output(["git", "ls-tree", "-r", "-z", CURRENT_MAIN, "--",
        "tests/golden/", "webapp/frontend/dist/", "atlas-scope/dist-hub/", *sorted(protected_files)], cwd=ROOT)
    candidate_entries = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD", "--",
        "tests/golden/", "webapp/frontend/dist/", "atlas-scope/dist-hub/", *sorted(protected_files)], cwd=ROOT)
    assert candidate_entries == expected_entries, "protected candidate modes/types/blobs differ from main"
    inputs = []
    for name in ("tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json"):
        raw = subprocess.check_output(["git", "show", CURRENT_MAIN + ":" + name], cwd=ROOT)
        assert (ROOT / name).read_bytes().replace(b"\r\n", b"\n") == raw
        path = scratch / Path(name).name
        path.write_bytes(raw)
        inputs.append(str(path))
    view_refs = {"current-main": CURRENT_MAIN, "latest-main": LATEST_MAIN,
                 **CORPUS["fix_commit_refs"], "final-head": "candidate"}
    outputs = {}
    for label, ref in view_refs.items():
        destination = scratch / (label + "-views")
        destination.mkdir()
        subprocess.run([sys.executable, "-I", "-B", "-c", w60b._SNAPSHOT_SCRIPT, str(sources[ref]),
                        json.dumps(inputs), str(destination)], cwd=scratch, check=True, timeout=180)
        outputs[label] = destination
    failures = []
    for path in inputs:
        name = Path(path).name + ".redacted.json"
        before = (outputs["current-main"] / name).read_bytes()
        expected_hash = CORPUS["view_sha256"][Path(path).name]
        assert hashlib.sha256(before).hexdigest() == expected_hash, ("main view hash differs from owner receipt", name)
        for label, ref in view_refs.items():
            after = (outputs[label] / name).read_bytes()
            receipt = {"w60c_fix": label, "ref": ref, "view": name, "byte_identical": before == after,
                       "before_sha256": hashlib.sha256(before).hexdigest(),
                       "after_sha256": hashlib.sha256(after).hexdigest(),
                       "changed_leaf_paths": w60b._changed_leaf_paths(json.loads(before), json.loads(after))
                       if before != after else []}
            print(json.dumps(receipt))
            if before != after:
                failures.append(receipt)
    assert failures == [], ("STOP: single-fix or final redacted view drift; ask owner, do not rebaseline", failures)

_LEGACY_ATTRIBUTION_SCRIPT = r'''
import json, logging, pathlib, re, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from cisco_toolkit import html
from webapp.backend import redaction_verify as rv
logging.disable(logging.CRITICAL)
source = pathlib.Path(sys.argv[1]).resolve()
assert pathlib.Path(html.__file__).resolve().is_relative_to(source)
assert pathlib.Path(rv.__file__).resolve().is_relative_to(source)
cases = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
root = pathlib.Path(sys.argv[3])
(root / "core1").mkdir(parents=True)
capture = root / "core1" / "show_running-config.txt"
def write(text):
    capture.write_bytes(text.encode("utf-8", "surrogateescape"))
def verify():
    try:
        return {"accepted": True, "proof": rv.verify_collection_secret_scrub(root)}
    except rv.RedactionVerificationError as error:
        return {"accepted": False, "error": str(error)}
def words(secret, text):
    return len(re.findall(r"(?<![\w-])" + re.escape(secret) + r"(?![\w-])", text))
rows = []
for case in cases:
    checks = {}
    text = case["text"]
    if case["kind"] == "verifier-control":
        if "clean_header" in case:
            write(case["clean_header"])
            checks["clean_control_certifies"] = verify()["accepted"]
        write(text)
        checks["raw_control_refuses"] = not verify()["accepted"]
        checks["read_only_verifier"] = capture.read_bytes() == text.encode("utf-8", "surrogateescape")
    else:
        direct = html._redact_config_values(text)
        if case["expect"] is not None:
            checks["direct_exact_expected"] = direct == case["expect"]
        checks["direct_idempotent"] = html._redact_config_values(direct) == direct
        if case["kind"] in {"must_redact", "qualifier_shaped", "combined"}:
            if case["kind"] != "combined":
                checks["raw_direct_refuses"] = bool(rv._raw_capture_credential_findings(text))
            checks["direct_scrub_certifies"] = not rv._raw_capture_credential_findings(direct)
        wrapped = "hostname core1\n" + text + "\n" if case["suite"] == "w60" else text
        expected = (("hostname core1\n" + case["expect"] + "\n") if case["suite"] == "w60" else case["expect"]) \
            if case["expect"] is not None else None
        write(wrapped)
        raw = verify()
        result = html.redact_collection_dir(str(root))
        output = capture.read_bytes().decode("utf-8", "surrogateescape")
        proof = verify()
        if expected is not None:
            checks["real_capture_exact_expected"] = output == expected
        checks["real_capture_certifies"] = proof["accepted"]
        checks["one_file_and_no_uncovered"] = result[0] == 1 and not getattr(result, "uncovered", ())
        if case["kind"] == "must_keep":
            checks["raw_keep_certifies"] = raw["accepted"]
            checks["keep_not_rewritten"] = result[1] == 0
        if case["kind"] == "must_redact":
            checks["raw_private_refuses"] = not raw["accepted"]
            checks["private_rewritten"] = result[1] == 1
        for index, secret in enumerate(case["secrets"]):
            if case["suite"] == "w60" and case["kind"] in {"must_redact", "combined"}:
                checks[f"private_absent:{index}"] = secret not in direct
            elif case["kind"] == "qualifier_shaped":
                checks[f"private_slot_removed:{index}"] = words(secret, direct) < words(secret, text)
            elif case["kind"] == "must_redact":
                before = len(re.findall(r"(?<![\w./-])" + re.escape(secret) + r"(?![\w./-])", text))
                after = len(re.findall(r"(?<![\w./-])" + re.escape(secret) + r"(?![\w./-])", output))
                checks[f"private_slot_removed:{index}"] = after < before
                if secret in case.get("value_occurrences_removed", {}):
                    checks[f"only_private_slot_removed:{index}"] = before - after == case["value_occurrences_removed"][secret]
        for index, structural in enumerate(case.get("structural", ())):
            checks[f"structural_preserved:{index}"] = structural in output
        for index, prefix in enumerate(case.get("statement_prefixes", ())):
            checks[f"statement_prefix_preserved:{index}"] = output.splitlines()[prefix["line"]].startswith(prefix["prefix"])
        second = html.redact_collection_dir(str(root))
        checks["real_capture_fixpoint"] = (second == (1, 0) and not getattr(second, "uncovered", ())
            and capture.read_bytes().decode("utf-8", "surrogateescape") == output)
        if (case["suite"] == "w60" and case["kind"] == "must_redact"
                and "notail" not in case.get("flags", ())):
            position = output.index("<redacted>") + len("<redacted>")
            write(output[:position] + " Leak99tail" + output[position:])
            checks["private_tail_refuses"] = not verify()["accepted"]
    rows.append({"id": case["id"], "checks": checks, "failed_checks": [name for name, ok in checks.items() if not ok]})
pathlib.Path(sys.argv[4]).write_text(json.dumps(rows, ensure_ascii=True), encoding="utf-8")
'''


def _legacy_attribution_cases():
    old = w60b._restore(json.loads((ROOT / "tests/fixtures/redaction_grammar_corpus.json").read_text(encoding="utf-8")))
    cases = []
    for group in ("must_redact", "must_keep", "over_redacted", "qualifier_shaped"):
        for index, row in enumerate(old[group]):
            expected = row["line"] if group == "must_keep" else row.get("w60b_expect", row["expect"])
            cases.append({"id": f"w60:{group}:{index}", "suite": "w60", "kind": group,
                          "text": row["line"], "expect": expected,
                          "secrets": row.get("secrets", []), "flags": row.get("flags", [])})
    for row in w60b.GATED_ROWS:
        case = {"id": "w60b:" + row["id"], "suite": "w60b", "kind": row["mode"],
                "text": row["text"], "secrets": row["secrets"], "structural": row["structural"],
                "value_occurrences_removed": row.get("value_occurrences_removed", {}),
                "statement_prefixes": row.get("statement_prefixes", ())}
        # A legacy row without an exact byte oracle retains its original
        # slot/structure checks; a separately obtained baseline is not invented.
        if "expect" in row:
            case["expect"] = row["expect"]
        elif row["mode"] == "must_keep":
            case["expect"] = row["text"]
        else:
            case["expect"] = None
        cases.append(case)
    for row in w60b.GATED_VERIFIER_CONTROLS:
        cases.append({"id": "w60b-refusal:" + row["id"], "suite": "w60b", "kind": "verifier-control",
                      "text": row["text"], **({"clean_header": row["clean_header"]} if "clean_header" in row else {})})
    every_row = [row for group in ("must_redact", "must_keep", "over_redacted", "qualifier_shaped") for row in old[group]]
    benign = "\n".join(row["line"] for group in ("must_keep", "over_redacted", "qualifier_shaped") for row in old[group])
    strong = re.compile(r"(?=\S*[A-Za-z])(?=\S*\d)\S{5,}")
    private = sorted({secret for row in old["must_redact"] for secret in row["secrets"]
                      if strong.fullmatch(secret) and secret not in benign})
    cases.append({"id": "w60:whole-corpus-fixpoint", "suite": "w60", "kind": "combined",
                  "text": "\n".join(row["line"] for row in every_row) + "\n", "expect": None, "secrets": private})
    return cases


def test_w60c_pre_p26_and_main_archives_attribute_every_legacy_corpus_assertion(archival_replay):
    """Mandatory source attribution, distinct from the final-head complete suite.

    Original W60 expected bytes, raw/scrub/tail verdicts and fixpoints plus every
    active W60b required-slot/structure/control record are executed in fresh
    interpreters loading only the real archived producer/verifier source.
    """
    _cases, _results, sources, scratch = archival_replay
    assert CORPUS["fix_commit_refs"]["P2-5"] == PRE_P26
    cases = _legacy_attribution_cases()
    assert len(cases) == 2618 and len({case["id"] for case in cases}) == len(cases)
    input_path = scratch / "legacy-attribution-inputs.json"
    input_path.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8")
    failures = []
    for ref in (CURRENT_MAIN, PRE_P26):
        output_path = scratch / (ref + "-legacy-attribution.json")
        subprocess.run([sys.executable, "-I", "-B", "-c", _LEGACY_ATTRIBUTION_SCRIPT,
                        str(sources[ref]), str(input_path), str(scratch / (ref + "-legacy-attribution-captures")),
                        str(output_path)], cwd=scratch, check=True, timeout=300)
        rows = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(rows) == len(cases) and {row["id"] for row in rows} == {case["id"] for case in cases}
        failed = [{"id": row["id"], "failed_checks": row["failed_checks"]} for row in rows if row["failed_checks"]]
        print(json.dumps({"legacy_source_attribution": ref, "rows": len(rows),
                          "checks": sum(len(row["checks"]) for row in rows), "failed_rows": len(failed),
                          "failures": failed}))
        if failed:
            failures.append({"ref": ref, "failures": failed})
    assert failures == [], ("pre-P26 or immutable-main legacy attribution is not green", failures)

_DEFERRED_BASELINE_CASES = (
    [{"id": "w60c:" + row["id"], "record": row} for row in DEFERRED_ROWS]
    + [{"id": "w60b:" + row["id"], "record": row} for row in DEFERRED_HISTORICAL_ROWS]
    + [{"id": "w60c-refusal:" + row["id"], "record": row} for row in DEFERRED_VERIFIER_CONTROLS]
    + [{"id": "w60b-refusal:" + row["id"], "record": row} for row in DEFERRED_HISTORICAL_VERIFIER_CONTROLS]
)


@pytest.mark.parametrize("case", _DEFERRED_BASELINE_CASES, ids=lambda case: case["id"])
def test_w60c_owner_deferred_p26_retains_exact_main_bytes_and_verdicts(case, archival_replay):
    """Every withdrawn feature example remains an active immutable-main guard.

    Its future expected output/refusal record stays untouched in the fixture.
    Owner authorization withdrew implementation and closure assertions for P26;
    byte/verdict compatibility and full secret/certification differentials remain.
    """
    _cases, results, _sources, _scratch = archival_replay
    baseline = results[CURRENT_MAIN][case["id"]]
    candidate = results["candidate"][case["id"]]
    assert candidate["output"] == baseline["output"], (case["id"], "deferred finding changed baseline bytes")
    assert candidate["counts"] == baseline["counts"] and candidate["uncovered"] == baseline["uncovered"], case["id"]
    assert candidate["raw_verifier"]["accepted"] == baseline["raw_verifier"]["accepted"], (
        case["id"], "deferred raw certification behavior changed")
    assert candidate["verifier"]["accepted"] == baseline["verifier"]["accepted"], (
        case["id"], "deferred post-scrub certification behavior changed")
    for phase in ("raw_verifier", "verifier"):
        if baseline[phase]["accepted"]:
            assert candidate[phase]["proof"] == baseline[phase]["proof"], (case["id"], phase)
    assert candidate["idempotent"] == baseline["idempotent"], case["id"]
    assert candidate["second_counts"] == baseline["second_counts"], case["id"]
