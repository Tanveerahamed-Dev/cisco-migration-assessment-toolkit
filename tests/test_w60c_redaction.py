"""W60c residuals: synthetic grammar probes and exact hosted archival custody.

The earlier W60/W60b suites and fixtures remain unchanged. This suite activates
the retained deferred schematic assertions and adds fresh EXAMPLE cases. Real
Git archives and persisted-view oracles are mandatory in every hosted job that
collects this module. Nothing regenerates a repository artifact.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cisco_toolkit import html
import test_w60b_redaction as w60b


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/w60c_redaction_corpus.json"
CORPUS = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CURRENT_MAIN = "0dc2f5d6f4d122ef74f8098e173e2be0bc2c902f"
ROUND3 = "d05ff1aaea85d87ff474f3a9d425eeacfa99a10c"
ROWS = CORPUS["rows"]
FINDINGS = frozenset({"P1-3", "P1-4", "P2-5", "P2-6"})
VIEW_FIXES = FINDINGS | {"P2-5-carrier", "P2-5-operand-boundary"}
_HISTORICAL_FINDINGS = frozenset({"R4-P1-directive", "R4-P1-prefix", "R4-P2-executable", "R4-P2-field"})
HISTORICAL_ROWS = [row for row in w60b.ROWS if row["id"].startswith("r4:")
                   and row["finding"] in _HISTORICAL_FINDINGS]
VERIFIER_CONTROLS = CORPUS["verifier_only_controls"]
HISTORICAL_VERIFIER_CONTROLS = [row for row in w60b.CORPUS["verifier_only_controls"]
                               if row["finding"] in _HISTORICAL_FINDINGS]


def test_w60c_corpus_has_each_scoped_family_and_fresh_positive_negative_controls():
    assert CORPUS["current_main_ref"] == CURRENT_MAIN and CORPUS["round3_ref"] == ROUND3
    assert set(CORPUS["scope"]) == FINDINGS
    assert CORPUS["values_policy"] and CORPUS["deferred"] == [
        {"finding": "P3-7", "reason": "Fail-safe ISAKMP hostname over-redaction; no claimed repair unless "
         "an independent narrow proven-operand rule exists.",
         "immutable_legacy_row": "isakmp-peer:complete-inline-enc-hostname"}]
    residual = [row for row in w60b.ROWS if row["id"] == CORPUS["deferred"][0]["immutable_legacy_row"]]
    assert len(residual) == 1 and "hostname <redacted>" in residual[0]["expect"]
    assert len({row["id"] for row in ROWS}) == len(ROWS)
    assert len(ROWS) == 154 and sum(row["mode"] == "must_redact" for row in ROWS) == 112
    assert len(VERIFIER_CONTROLS) == 7 and len(HISTORICAL_ROWS) == 18 and len(HISTORICAL_VERIFIER_CONTROLS) == 6
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
            assert all(w60b._slot_count(secret, row["text"]) for secret in row["secrets"]), row["id"]
    for row in VERIFIER_CONTROLS:
        assert row["secrets"] and all(w60b._slot_count(secret, row["text"]) for secret in row["secrets"]), row["id"]
    probes = CORPUS["source_review_probe_inputs"]
    assert len(probes) == 1 and probes[0]["id"] == "source-review:raw-known-creator-marker-alias"
    assert probes[0]["status"] and "expect" not in probes[0]
    assert probes[0]["secrets"] and all(w60b._slot_count(secret, probes[0]["text"]) for secret in probes[0]["secrets"])


@pytest.mark.parametrize("row", ROWS + HISTORICAL_ROWS, ids=lambda row: row["id"])
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
            assert w60b._slot_count(secret, output) < w60b._slot_count(secret, row["text"]), (
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


@pytest.mark.parametrize("row", VERIFIER_CONTROLS + HISTORICAL_VERIFIER_CONTROLS, ids=lambda row: row["id"])
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
    archive_refs = list(dict.fromkeys([CURRENT_MAIN, ROUND3, *fix_refs.values()]))
    sources = {ref: w60b._archive(ref, scratch) for ref in archive_refs}
    sources["candidate"] = ROOT
    results = {}
    for ref in (CURRENT_MAIN, ROUND3, "candidate"):
        output_path = scratch / (ref + ".json")
        subprocess.run([sys.executable, "-I", "-B", "-c", w60b._BATCH_SCRIPT, str(sources[ref]), str(case_path),
                        str(scratch / (ref + "-captures")), str(output_path)],
                       cwd=scratch, check=True, timeout=300)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(result) == len(cases) and {row["id"] for row in result} == {case["id"] for case in cases}
        results[ref] = {row["id"]: row for row in result}
    return cases, results, sources, scratch


@pytest.mark.parametrize("ref", [CURRENT_MAIN, ROUND3], ids=["current-main-0dc2f5d6", "round3"])
def test_w60c_all_legacy_and_fresh_cases_have_zero_archive_regressions(ref, archival_replay):
    cases, results, _sources, _scratch = archival_replay
    removed_slots = 0
    certified_baselines = 0
    regressions = []
    for case in cases:
        baseline = results[ref][case["id"]]
        candidate = results["candidate"][case["id"]]
        for secret in case["secrets"]:
            raw_count = w60b._slot_count(secret, case["text"])
            baseline_count = w60b._slot_count(secret, baseline["output"])
            if baseline_count < raw_count:
                removed_slots += 1
                if w60b._slot_count(secret, candidate["output"]) > baseline_count:
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
    for row in ROWS:
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
        for ref in (CURRENT_MAIN, ROUND3, "candidate"):
            result = results[ref]["w60c-review-probe:" + probe["id"]]
            raw_count = sum(w60b._slot_count(secret, probe["text"]) for secret in probe["secrets"])
            remaining = sum(w60b._slot_count(secret, result["output"]) for secret in probe["secrets"])
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
    view_refs = {"current-main": CURRENT_MAIN, **CORPUS["fix_commit_refs"], "final-head": "candidate"}
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
