"""W60b: independent-review examples, required slots and exact archival differentials.

Corpus expectations are authored from credential grammar, never harvested from
the candidate. Expensive archive and persisted-view comparisons run in the
separate hosted W60b lane; ordinary corpus and work-bound tests also run in every
required Python leg. Nothing regenerates a repository artifact.
"""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tarfile
import time

import pytest

from cisco_toolkit import analyze, design_kb, html, parse
from webapp.backend import redaction_verify as rv


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/w60b_redaction_corpus.json"
BASE = "0b411c16347a0f1651b88cae52b58555701e4db3"
MAIN = "2c927d0209e4c4928c3f29d8747d648f930ddade"
ROUND3 = "d05ff1aaea85d87ff474f3a9d425eeacfa99a10c"
CURRENT_MAIN = "00647ebddfc68064f6845a8b14a5984b6e92695c"
_SURROGATE = re.compile(r"\{\{U\+(DC[89A-F][0-9A-F])\}\}")


def _restore(value):
    if isinstance(value, str):
        return _SURROGATE.sub(lambda match: chr(int(match.group(1), 16)), value)
    if isinstance(value, list):
        return [_restore(item) for item in value]
    if isinstance(value, dict):
        return {key: _restore(item) for key, item in value.items()}
    return value


CORPUS = _restore(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
ROWS = CORPUS["rows"]


def _slot_count(secret, text):
    """An exact lexical occurrence; never count a digit inside an IP/OID/token.

Shared structural spellings are measured by the decrease in their occurrence
count. Thus the structural 'secret' keyword may remain while its value is removed.
"""
    return len(re.findall(r"(?<![\w./-])" + re.escape(secret) + r"(?![\w./-])", text))


def _verify(root):
    try:
        proof = rv.verify_collection_secret_scrub(root)
    except rv.RedactionVerificationError as error:
        return {"accepted": False, "error": str(error)}
    return {"accepted": True, "proof": proof}


def _capture(root, text):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "capture.cfg"
    path.write_bytes(text.encode("utf-8", "surrogateescape"))
    return path


def _base_password_stops():
    """Read both old stop registries as AST data; execute no baseline module."""
    source = subprocess.check_output(["git", "show", BASE + ":cisco_toolkit/html.py"], cwd=ROOT)
    tree = ast.parse(source.decode("utf-8"))
    words = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                and target.id == "_REDACT_SWEEP_VOID_NEXT" for target in node.targets)):
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "password":
                    words.update(ast.literal_eval(value.args[0]))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_redact_family" and len(node.args) >= 3):
            try:
                anchor = ast.literal_eval(node.args[0])
            except ValueError:
                continue
            if anchor.startswith(r"\b(?:password|passwd|secret|passphrase|pass-phrase|enablesecret)"):
                words.update(ast.literal_eval(node.args[2]))
    return words


def test_w60b_corpus_retains_review_and_every_required_stop_word():
    assert CORPUS["review_merge"] == BASE
    assert CORPUS["main_ref"] == MAIN and CORPUS["round3_ref"] == ROUND3
    review = CORPUS["review_differential"]
    assert len(review) == 599 and len({row["id"] for row in review}) == 599
    assert len({row["id"] for row in ROWS}) == len(ROWS)
    findings = {row["finding"] for row in ROWS}
    assert {"R1", "L1", "L2", "L3", "L4", "L5", "L6", "O1", "O2", "O3", "O4",
            "OR1", "A1", "A2", "T2"} <= findings
    assert {row["id"] for row in CORPUS["performance_families"]} == {"T1", "T2-digest", "T2-entropy"}
    words = _base_password_stops()
    assert words and set(CORPUS["exempt_password_words"]) == words
    required = {(row.get("structural_word"), row.get("value_form"), row.get("value_variant"))
                for row in ROWS if row["id"].startswith("required:")}
    for word in words:
        for form in ("username-password", "username-secret", "neighbor-password", "enable-password", "enable-secret"):
            variants = (("bare", "typed", "quoted", "level", "leveltyped") if form.startswith("enable-")
                        else ("bare", "typed", "quoted"))
            for variant in variants:
                assert (word, form, variant) in required
        assert any(row["mode"] == "must_keep" and row.get("structural_word") == word for row in ROWS)
    for row in ROWS:
        assert row["mode"] in {"must_redact", "must_keep"}
        if row["mode"] == "must_redact":
            assert row["secrets"] and all(_slot_count(secret, row["text"]) for secret in row["secrets"]), row
        for secret, count in row.get("value_occurrences_removed", {}).items():
            assert secret in row["secrets"] and count == 1 and _slot_count(secret, row["text"]) >= count, row


def test_w60b_ordered_type_matrix_covers_each_private_value_without_reusing_a_fixture_line():
    typed = {row["id"]: row for row in ROWS if row["id"].startswith("ordered-type:")}
    forms = ("username-password", "username-secret", "neighbor-password", "enable-password", "enable-secret")
    values = [str(number) for number in range(10)] + ["10", "14", "enc", "md5", "hash"]
    for form in forms:
        for value in values:
            for variant in ("next-statement", "note-tail"):
                assert f"ordered-type:{form}:{variant}:{value}" in typed
        for variant in ("quoted-value7", "first-type7-wrap"):
            assert f"ordered-type:{form}:{variant}" in typed
    for form in ("enable-password", "enable-secret"):
        assert f"ordered-type:{form}:level7-type0-value7" in typed
    assert len(typed) == 162
    old = _restore(json.loads((ROOT / "tests/fixtures/redaction_grammar_corpus.json").read_text(encoding="utf-8")))
    prior_texts = [row["line"] for group in ("must_redact", "must_keep", "over_redacted", "qualifier_shaped")
                   for row in old[group]]
    prior_texts.extend(row["text"] for row in CORPUS["review_differential"])
    prior_texts.extend(row["text"] for row in ROWS if row["id"] not in typed)
    prior_lines = {line.strip() for text in prior_texts for line in text.splitlines() if line.strip()}
    fresh_lines = [line.strip() for row in typed.values() for line in row["text"].splitlines() if line.strip()]
    assert len(fresh_lines) == len(set(fresh_lines)), "an ordered-type source line is repeated"
    assert not prior_lines.intersection(fresh_lines), "an ordered-type source line reuses an older corpus fixture"


@pytest.mark.parametrize("row", ROWS, ids=[row["id"] for row in ROWS])
def test_w60b_real_producer_and_independent_verifier(row, tmp_path):
    capture = _capture(tmp_path, row["text"])
    raw_proof = _verify(tmp_path)
    result = html.redact_collection_dir(str(tmp_path))
    output = capture.read_bytes().decode("utf-8", "surrogateescape")
    assert result[0] == 1 and not result.uncovered
    if row["mode"] == "must_keep":
        assert result[1] == 0 and output == row["text"], row["id"]
        assert raw_proof["accepted"], raw_proof
    else:
        assert not raw_proof["accepted"], ("raw credential certified", row["id"], raw_proof)
        assert result[1] == 1, row["id"]
        for secret in row["secrets"]:
            assert _slot_count(secret, output) < _slot_count(secret, row["text"]), (row["id"], secret, output)
            if secret in row.get("value_occurrences_removed", {}):
                removed = _slot_count(secret, row["text"]) - _slot_count(secret, output)
                assert removed == row["value_occurrences_removed"][secret], (
                    row["id"], "removed a public type/level/privilege occurrence or retained the private value", secret, output)
        if "expect" in row:
            assert output == row["expect"], row["id"]
        for structural in row["structural"]:
            assert structural in output, (row["id"], "lost structure", structural, output)
        for prefix in row.get("statement_prefixes", ()):
            assert output.splitlines()[prefix["line"]].startswith(prefix["prefix"]), (row["id"], prefix, output)
    proof = _verify(tmp_path)
    assert proof["accepted"], (row["id"], proof, output)
    assert proof["proof"]["files"] == 1 and proof["proof"]["uncovered"] == []
    assert html.redact_collection_dir(str(tmp_path)) == (1, 0)
    assert capture.read_bytes().decode("utf-8", "surrogateescape") == output


@pytest.mark.parametrize("row", CORPUS["verifier_only_controls"], ids=lambda row: row["id"])
def test_w60b_curl_header_quote_exception_refuses_unsafe_or_unproven_tails(row, tmp_path):
    """Verifier-only counterexamples; no producer rewrite or approval is promised."""
    assert row["expect_refusal"] is True
    capture = _capture(tmp_path, row["text"])
    proof = _verify(tmp_path)
    assert not proof["accepted"], (row["id"], "unsafe authorization tail was certified", proof)
    assert "residue" in proof["error"], (row["id"], "refusal was not a credential postcondition", proof)
    assert capture.read_bytes() == row["text"].encode("utf-8"), "read-only verifier changed the capture"


class _CountedText(str):
    """Instrument materialised source slices, the two reported quadratic causes."""
    def __new__(cls, value):
        result = super().__new__(cls, value)
        result.copied = 0
        result.visited = 0
        return result

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(key, slice):
            self.copied += len(result)
        else:
            self.visited += 1
        return result


def _performance_text(family, count):
    if family["generator"] == "smuxpeer_suffix":
        return family["separator"].join(family["unit"].format(index=index) for index in range(count)) + "\n"
    return family["unit"] * count + "\n"


def test_w60b_reported_hot_paths_have_linear_source_copy_work():
    smux = _CountedText(_performance_text(CORPUS["performance_families"][0], 2048))
    assert html._redact_snmp_positional_spans(smux)
    assert smux.copied + smux.visited <= 40 * len(smux), (len(smux), smux.copied, smux.visited)
    digest = _performance_text(CORPUS["performance_families"][1], 512)
    for function in (lambda text: html._redact_high_entropy_spans(text, False), rv._sweep_entropy):
        measured = _CountedText(digest)
        assert not function(measured)
        assert measured.copied + measured.visited <= 40 * len(measured), (len(measured), measured.copied, measured.visited)


@pytest.mark.parametrize("family", CORPUS["performance_families"], ids=lambda row: row["id"])
def test_w60b_real_pair_scaling_on_reported_pathological_inputs(family, tmp_path):
    """Eight times the input: generous 24x plus noise bound, and absolute 30s.

Work-count assertions above close the known copy mechanisms independently of
wall-clock noise. This test also catches work hidden in regexes or other helpers.
"""
    medians = []
    receipts = []
    for count in family["counts"]:
        text = _performance_text(family, count)
        samples = []
        for _ in range(3):
            capture = _capture(tmp_path, text)
            started = time.perf_counter()
            result = html.redact_collection_dir(str(tmp_path))
            proof = rv.verify_collection_secret_scrub(tmp_path)
            samples.append(time.perf_counter() - started)
            output = capture.read_bytes().decode("utf-8", "surrogateescape")
            assert result[0] == 1 and not result.uncovered
            assert proof["files"] == 1 and proof["uncovered"] == []
            if family["mode"] == "must_keep":
                assert result[1] == 0 and output == text
            else:
                assert result[1] == 1 and "perfvalue" not in output
                if family["generator"] == "repeat":
                    assert family["unit"].strip() not in output
        medians.append(statistics.median(samples))
        receipts.append({"bytes": len(text.encode()), "samples_s": samples})
    print(json.dumps({"family": family["id"], "receipts": receipts}, sort_keys=True))
    assert medians[-1] < 30, (family["id"], receipts)
    assert medians[-1] <= max(0.20, medians[0]) * 24, (family["id"], receipts)


def _canonical_registry_snapshot():
    """Independent test input from every registry check and all real projections."""
    findings = [{"id": check, "title": title, "severity": severity, "cis_ref": reference,
                 "remediation": remediation, "status": "fail", "detail": "Synthetic registry coverage"}
                for check, (title, severity, reference, remediation) in parse._SEC_CHECKS.items()]
    security = {"owner_scope": {"findings": findings}}
    return {"security": security,
            "framework_coverage": analyze.compute_framework_coverage(security),
            "punchlist": analyze.compute_migration_punchlist([], security, {}, [], [], [], {}, [], []),
            "remediation_plan": analyze.compute_remediation_plan(security=security)}


def _owner_structural_password_collision(value):
    words = html._REDACT_SWEEP_VOID_NEXT["password"]
    return any(match.group(1).casefold() in words
               for match in re.finditer(r"\bpassword\s+([A-Za-z0-9_-]+)\b", value, re.IGNORECASE))


def _registry_owned_text_fields(snapshot):
    fields = []
    for host, block in snapshot["security"].items():
        fields.extend((f"security/{host}/{row['id']}/title", row["title"])
                      for row in block["findings"])
    for framework, block in snapshot["framework_coverage"]["frameworks"].items():
        fields.extend((f"framework/{framework}/{row['check']}/{key}", row[key])
                      for row in block["controls"] for key in ("title", "control"))
    fields.extend((f"punchlist/{index}/title", row["title"])
                  for index, row in enumerate(snapshot["punchlist"]))
    fields.extend((f"remediation/items/{index}/title", row["title"])
                  for index, row in enumerate(snapshot["remediation_plan"]["items"]))
    for host, rows in snapshot["remediation_plan"]["by_device"].items():
        fields.extend((f"remediation/by_device/{host}/{index}/title", row["title"])
                      for index, row in enumerate(rows))
    return fields


def test_w60b_owner_collision_exception_preserves_only_existing_structural_password_words():
    snapshot = _canonical_registry_snapshot()
    expected = {path: value for path, value in _registry_owned_text_fields(snapshot)
                if _owner_structural_password_collision(value)}
    assert expected, "no owner field exercises an existing password structural exemption"
    redacted = dict(_registry_owned_text_fields(html.redact_snapshot(snapshot)))
    assert {path: redacted[path] for path in expected} == expected
    print(json.dumps({"owner_policy": "exact-main-views; structural-password-collisions-only",
                      "collision_fields_checked": sorted(expected), "collision_fields": len(expected)}))


def test_w60b_all_owner_registry_projections_match_the_real_archived_main_view(archival_replay):
    """Latest owner directive: preserve exact main views, including prior scrubbing.

    All registry rows remain covered. Expected values come from the real BASE
    producer on the independently builder-authored snapshot in hosted scratch.
    The former broad raw-title exception is expressly outside this requirement.
    """
    _cases, _results, sources, scratch = archival_replay
    snapshot = _canonical_registry_snapshot()
    pristine = deepcopy(snapshot)
    input_path = scratch / "canonical-owner-registry.snapshot.json"
    input_path.write_text(json.dumps(pristine, ensure_ascii=False), encoding="utf-8")
    destination = scratch / "canonical-owner-main-views"
    destination.mkdir()
    subprocess.run([sys.executable, "-I", "-B", "-c", _SNAPSHOT_SCRIPT, str(sources[BASE]),
                    json.dumps([str(input_path)]), str(destination)], cwd=scratch, check=True, timeout=180)
    baseline = json.loads((destination / (input_path.name + ".redacted.json")).read_text(encoding="utf-8"))
    redacted = html.redact_snapshot(snapshot)
    assert snapshot == pristine, "owner input was mutated"
    source = snapshot["security"]["owner_scope"]["findings"]
    result = redacted["security"]["owner_scope"]["findings"]
    expected = baseline["security"]["owner_scope"]["findings"]
    assert {row["id"] for row in source} == set(parse._SEC_CHECKS)
    assert [(row["id"], row["title"]) for row in result] == [(row["id"], row["title"]) for row in expected]
    covered = set()
    for framework, block in snapshot["framework_coverage"]["frameworks"].items():
        originals = block["controls"]
        transformed = redacted["framework_coverage"]["frameworks"][framework]["controls"]
        expected = baseline["framework_coverage"]["frameworks"][framework]["controls"]
        assert [(row["check"], row["title"], row["control"]) for row in transformed] == [
            (row["check"], row["title"], row["control"]) for row in expected]
        covered.update(row["check"] for row in originals)
    assert covered == set(parse._SEC_CHECKS), "the real framework input does not cover every check"
    assert [(row["category"], row["title"]) for row in redacted["punchlist"]] == [
        (row["category"], row["title"]) for row in baseline["punchlist"]]
    assert {row["title"] for row in snapshot["punchlist"]} == {row["title"] for row in source}
    for field in ("items", "by_device"):
        original = snapshot["remediation_plan"][field]
        transformed = redacted["remediation_plan"][field]
        expected = baseline["remediation_plan"][field]
        if field == "by_device":
            original = [row for rows in original.values() for row in rows]
            transformed = [row for rows in transformed.values() for row in rows]
            expected = [row for rows in expected.values() for row in rows]
        assert [(row["category"], row["title"]) for row in transformed] == [
            (row["category"], row["title"]) for row in expected]
        assert {row["title"] for row in original} == {row["title"] for row in source}
    assert html.redact_snapshot(redacted) == redacted, "owner-vocabulary result is not idempotent"
    print(json.dumps({"owner_policy": "exact-main-views; structural-password-collisions-only",
                      "reference": BASE, "registry_checks": sorted(parse._SEC_CHECKS),
                      "projected_fields_checked": len(_registry_owned_text_fields(pristine))}))


@pytest.mark.parametrize("context", ["security-id", "security-title-tail", "framework-id", "arbitrary-title",
                                    "credential-container", "punch-reference", "remediation-source", "remediation-verify"])
@pytest.mark.parametrize("owner_class", ["prior-main-scrub", "structural-password-collision"])
def test_w60b_owner_vocabulary_cannot_authenticate_an_unowned_context(context, owner_class):
    snapshot = _canonical_registry_snapshot()
    check = ("weak-user-pw" if owner_class == "prior-main-scrub" else
             next(cid for cid, (title, _severity, _reference, _remediation) in parse._SEC_CHECKS.items()
                  if _owner_structural_password_collision(title)))
    title = parse._SEC_CHECKS[check][0]
    findings = snapshot["security"]["owner_scope"]["findings"]
    index = next(index for index, row in enumerate(findings) if row["id"] == check)
    target = ("security", "owner_scope", "findings", index, "title")
    if context == "security-id":
        findings[index]["id"] = "unowned-corpus-check"
    elif context == "security-title-tail":
        findings[index]["title"] = title + " password SyntheticOwner242"
    elif context == "framework-id":
        controls = snapshot["framework_coverage"]["frameworks"]["CIS"]["controls"]
        control_index = next(index for index, row in enumerate(controls) if row["check"] == check)
        controls[control_index]["check"] = "unowned-corpus-check"
        target = ("framework_coverage", "frameworks", "CIS", "controls", control_index, "title")
    elif context == "arbitrary-title":
        snapshot = {"arbitrary": {"title": title}}
        target = ("arbitrary", "title")
    elif context == "credential-container":
        snapshot = {"password": snapshot}
        target = ("password",) + target
    elif context == "punch-reference":
        punch_index = next(index for index, row in enumerate(snapshot["punchlist"]) if row["title"] == title)
        snapshot["punchlist"][punch_index]["evidence_refs"] = [
            {"ref": "/security/owner_scope/findings/99999", "kind": "device_fact", "role": "derived_from"}]
        target = ("punchlist", punch_index, "title")
    else:
        items = snapshot["remediation_plan"]["items"]
        item_index = next(index for index, row in enumerate(items) if row["title"] == title)
        key = "source" if context == "remediation-source" else "verify"
        items[item_index][key] = "unowned-corpus-context"
        target = ("remediation_plan", "items", item_index, "title")
    result = html.redact_snapshot(snapshot)
    changed = result
    for part in target:
        changed = changed[part]
    assert changed != title, (context, "owner text was exempted at an unauthenticated role")
    if context == "credential-container":
        assert changed == "<redacted>", "credential-container priority was lost"
    if context == "security-title-tail":
        assert "SyntheticOwner242" not in json.dumps(result), "a mutated title authenticated its credential tail"


def test_w60b_exact_owner_title_is_not_an_exemption_in_a_raw_capture(tmp_path):
    title = parse._SEC_CHECKS["weak-user-pw"][0]
    capture = _capture(tmp_path, title + "\n")
    assert not _verify(tmp_path)["accepted"], "the snapshot-owner exception escaped into raw capture verification"
    assert html.redact_collection_dir(str(tmp_path)) == (1, 1)
    assert capture.read_bytes() != (title + "\n").encode("utf-8")
    proof = _verify(tmp_path)
    assert proof["accepted"] and proof["proof"]["files"] == 1 and proof["proof"]["uncovered"] == []
    assert html.redact_collection_dir(str(tmp_path)) == (1, 0)


def _canonical_owner_action_snapshot():
    principle = next(row for row in design_kb.all_principles()
                     if row["id"] == "security-device-hardening-baseline")
    row = {"id": principle["id"], "domain": principle["domain"],
           "recommended_action": principle["recommended_action"]}
    decision = {**row, "principle": {"id": principle["id"]}}
    return principle, {"design_blueprint": {"decisions": [decision],
                                           "doctrine": {principle["domain"]: [row]}}}


def test_w60b_exact_structural_owner_action_keeps_both_registered_projections():
    principle, snapshot = _canonical_owner_action_snapshot()
    original = deepcopy(snapshot)
    redacted = html.redact_snapshot(snapshot)["design_blueprint"]
    assert snapshot == original
    action = principle["recommended_action"]
    assert redacted["decisions"][0]["recommended_action"] == action
    assert redacted["doctrine"][principle["domain"]][0]["recommended_action"] == action
    print(json.dumps({"owner_policy": "exact-main-views; bound-structural-owner-actions-only",
                      "principle_id": principle["id"], "domain": principle["domain"],
                      "action_sha256": hashlib.sha256(action.encode("utf-8")).hexdigest(),
                      "projection_roles": ["design_blueprint.decisions", "design_blueprint.doctrine"]}))


@pytest.mark.parametrize("context", ["decision-id", "decision-domain", "decision-principle-id", "doctrine-id",
                                    "doctrine-domain", "action-tail", "arbitrary-path", "credential-container"])
def test_w60b_owner_action_cannot_exempt_an_unbound_or_mutated_statement(context):
    principle, snapshot = _canonical_owner_action_snapshot()
    action = principle["recommended_action"]
    decision = snapshot["design_blueprint"]["decisions"][0]
    doctrine = snapshot["design_blueprint"]["doctrine"][principle["domain"]][0]
    target = ("design_blueprint", "decisions", 0, "recommended_action")
    if context == "decision-id":
        decision["id"] = "unowned-corpus-principle"
    elif context == "decision-domain":
        decision["domain"] = "unowned-corpus-domain"
    elif context == "decision-principle-id":
        decision["principle"]["id"] = "unowned-corpus-principle"
    elif context == "doctrine-id":
        doctrine["id"] = "unowned-corpus-principle"
        target = ("design_blueprint", "doctrine", principle["domain"], 0, "recommended_action")
    elif context == "doctrine-domain":
        snapshot["design_blueprint"]["doctrine"] = {"unowned-corpus-domain": [doctrine]}
        target = ("design_blueprint", "doctrine", "unowned-corpus-domain", 0, "recommended_action")
    elif context == "action-tail":
        decision["recommended_action"] = action + " password SyntheticAction251"
    elif context == "arbitrary-path":
        snapshot = {"arbitrary": {"recommended_action": action}}
        target = ("arbitrary", "recommended_action")
    elif context == "credential-container":
        snapshot = {"password": snapshot}
        target = ("password",) + target
    result = html.redact_snapshot(snapshot)
    changed = result
    for part in target:
        changed = changed[part]
    assert changed != action, (context, "an unbound or mutated owner action bypassed ordinary scrubbing")
    if context == "action-tail":
        assert "SyntheticAction251" not in json.dumps(result), "a mutated owner action authenticated a secret"
    if context == "credential-container":
        assert changed == "<redacted>", "an owner action overrode credential-container priority"


_BATCH_SCRIPT = r'''
import json, logging, pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from cisco_toolkit.html import redact_collection_dir
from webapp.backend.redaction_verify import verify_collection_secret_scrub, RedactionVerificationError
logging.disable(logging.CRITICAL)
cases = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
root = pathlib.Path(sys.argv[3])
root.mkdir()
capture = root / "capture.cfg"
def verify():
    try:
        return {"accepted": True, "proof": verify_collection_secret_scrub(root)}
    except RedactionVerificationError as error:
        return {"accepted": False, "error": str(error)}
rows = []
for case in cases:
    capture.write_bytes(case["text"].encode("utf-8", "surrogateescape"))
    raw = verify()
    result = redact_collection_dir(str(root))
    output = capture.read_bytes().decode("utf-8", "surrogateescape")
    proof = verify()
    second = redact_collection_dir(str(root))
    rows.append({"id": case["id"], "output": output, "raw_verifier": raw, "verifier": proof,
                 "counts": list(result), "uncovered": list(getattr(result, "uncovered", ())),
                 "idempotent": capture.read_bytes().decode("utf-8", "surrogateescape") == output,
                 "second_counts": list(second)})
pathlib.Path(sys.argv[4]).write_text(json.dumps(rows, ensure_ascii=True), encoding="utf-8")
'''


def _all_differential_cases():
    old = _restore(json.loads((ROOT / "tests/fixtures/redaction_grammar_corpus.json").read_text(encoding="utf-8")))
    cases = []
    for group in ("must_redact", "must_keep", "over_redacted", "qualifier_shaped"):
        for index, row in enumerate(old[group]):
            cases.append({"id": f"w60:{group}:{index}", "text": row["line"], "secrets": row.get("secrets", [])})
    cases.extend({"id": "fresh:" + row["id"], "text": row["text"], "secrets": row.get("secrets", [])}
                 for row in CORPUS["review_differential"])
    cases.extend({"id": "w60b:" + row["id"], "text": row["text"], "secrets": row["secrets"]} for row in ROWS)
    return cases


def _archive(ref, scratch):
    directory = scratch / ref
    directory.mkdir()
    archive = scratch / (ref + ".tar")
    # Archive the real dependency closure, not a copied/frozen implementation.
    subprocess.run(["git", "archive", "--format=tar", "--output=" + str(archive), ref,
                    "cisco_toolkit", "webapp/backend", "webapp/__init__.py"], cwd=ROOT, check=True)
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            path = Path(member.name)
            assert not path.is_absolute() and ".." not in path.parts and not member.issym() and not member.islnk()
            if member.isdir():
                (directory / path).mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                output = directory / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(handle.extractfile(member).read())
            else:
                pytest.fail("unexpected non-regular Git archive member")
    for path in ("cisco_toolkit/html.py", "cisco_toolkit/parse.py", "webapp/backend/redaction_verify.py"):
        expected = subprocess.check_output(["git", "show", ref + ":" + path], cwd=ROOT)
        assert (directory / path).read_bytes() == expected
    return directory


@pytest.fixture(scope="module")
def archival_replay(tmp_path_factory):
    if os.environ.get("W60B_ARCHIVE_DIFFERENTIAL") != "1":
        pytest.skip("exact archival differentials and persisted-view custody run in hosted W60b workflow")
    scratch = tmp_path_factory.mktemp("w60b-archives")
    cases = _all_differential_cases()
    case_path = scratch / "cases.json"
    case_path.write_text(json.dumps(cases, ensure_ascii=True), encoding="utf-8")
    sources = {ref: _archive(ref, scratch) for ref in (MAIN, ROUND3, BASE, CURRENT_MAIN)}
    sources["candidate"] = ROOT
    results = {}
    for ref in (MAIN, ROUND3, "candidate"):
        output_path = scratch / (ref + ".json")
        subprocess.run([sys.executable, "-I", "-B", "-c", _BATCH_SCRIPT, str(sources[ref]), str(case_path),
                        str(scratch / (ref + "-captures")), str(output_path)], cwd=scratch, check=True, timeout=300)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(result) == len(cases)
        results[ref] = {row["id"]: row for row in result}
    return cases, results, sources, scratch


@pytest.mark.parametrize("ref", [MAIN, ROUND3], ids=["pre-W60-main", "round3"])
def test_w60b_exact_archive_zero_secret_regressions(ref, archival_replay):
    cases, results, _sources, _scratch = archival_replay
    checked = 0
    regressions = []
    for case in cases:
        baseline = results[ref][case["id"]]
        candidate = results["candidate"][case["id"]]
        for secret in case["secrets"]:
            raw_count = _slot_count(secret, case["text"])
            baseline_count = _slot_count(secret, baseline["output"])
            if baseline_count < raw_count:
                checked += 1
                if _slot_count(secret, candidate["output"]) > baseline_count:
                    regressions.append({"id": case["id"], "secret": secret, "baseline": baseline["output"],
                                        "candidate": candidate["output"], "baseline_verifier": baseline["verifier"],
                                        "candidate_verifier": candidate["verifier"]})
    assert checked >= 800, (ref, "vacuous differential", checked)
    print(json.dumps({"ref": ref, "cases": len(cases), "removed_secret_slots_checked": checked, "regressions": len(regressions)}))
    assert regressions == [], json.dumps(regressions, ensure_ascii=True, indent=2)


def test_w60b_archive_candidate_postconditions_for_every_required_case(archival_replay):
    _cases, results, _sources, _scratch = archival_replay
    for row in ROWS:
        result = results["candidate"]["w60b:" + row["id"]]
        assert result["verifier"]["accepted"] and result["idempotent"], (row["id"], result)
        if row["mode"] == "must_redact":
            assert not result["raw_verifier"]["accepted"], (row["id"], result)


def test_w60b_new_wrapped_hostname_oracles_equal_the_real_archived_w60_output(archival_replay):
    """Two new oracle corrections require main's real byte result, never a guess.

    Candidate raw refusal, private-slot removal, public structure, certification
    and idempotence remain required by the existing strict corpus tests.
    """
    _cases, _results, sources, scratch = archival_replay
    wanted = {"isakmp-peer:wrapped-type7-hostname", "isakmp-peer:wrapped-enc-hostname"}
    rows = [row for row in ROWS if row["id"] in wanted]
    assert {row["id"] for row in rows} == wanted
    case_path = scratch / "w60-wrapped-hostname-cases.json"
    case_path.write_text(json.dumps([{"id": row["id"], "text": row["text"]} for row in rows], ensure_ascii=True),
                         encoding="utf-8")
    output_path = scratch / "w60-wrapped-hostname-results.json"
    subprocess.run([sys.executable, "-I", "-B", "-c", _BATCH_SCRIPT, str(sources[BASE]), str(case_path),
                    str(scratch / "w60-wrapped-hostname-captures"), str(output_path)],
                   cwd=scratch, check=True, timeout=180)
    archived = {result["id"]: result for result in json.loads(output_path.read_text(encoding="utf-8"))}
    assert set(archived) == wanted
    disagreements = []
    for row in rows:
        result = archived[row["id"]]
        output = result["output"]
        receipt = {"id": row["id"], "reference": BASE, "byte_identical": output == row["expect"],
                   "input_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                   "archived_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                   "expected_sha256": hashlib.sha256(row["expect"].encode()).hexdigest(),
                   "archived_raw_verifier": result["raw_verifier"], "archived_verifier": result["verifier"]}
        print(json.dumps(receipt))
        assert all(_slot_count(secret, output) < _slot_count(secret, row["text"]) for secret in row["secrets"]), row["id"]
        assert result["counts"] == [1, 1] and result["uncovered"] == [] and result["idempotent"], (row["id"], result)
        if output != row["expect"]:
            disagreements.append({"id": row["id"], "archived_output": output, "authored_expectation": row["expect"]})
    assert disagreements == [], ("STOP: archived W60 disagrees with the new wrapped-hostname public-syntax oracle", disagreements)


_SNAPSHOT_SCRIPT = r'''
import json, pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from cisco_toolkit.html import redact_snapshot
for path in json.loads(sys.argv[2]):
    snapshot = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    output = redact_snapshot(snapshot)
    destination = pathlib.Path(sys.argv[3]) / (pathlib.Path(path).name + ".redacted.json")
    destination.write_bytes(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
'''


def _changed_leaf_paths(before, after, path="$"):
    """Explain a custody refusal without printing any engine leaf value."""
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        changes = []
        for key in sorted(set(before) | set(after)):
            child_path = path + "[" + json.dumps(key, ensure_ascii=True) + "]"
            if key not in before or key not in after:
                changes.append(child_path)
            else:
                changes.extend(_changed_leaf_paths(before[key], after[key], child_path))
        return changes
    if isinstance(before, list):
        if len(before) != len(after):
            return [path]
        return [changed for index, (left, right) in enumerate(zip(before, after))
                for changed in _changed_leaf_paths(left, right, path + f"[{index}]")]
    return [] if before == after else [path]


def _synthetic_changed_leaf_values(before, after, path="$"):
    """Bounded scalar previews for retained synthetic fixtures only, never a dump."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [change for key in sorted(set(before) & set(after))
                for change in _synthetic_changed_leaf_values(before[key], after[key],
                                                            path + "[" + json.dumps(key, ensure_ascii=True) + "]")]
    if isinstance(before, list) and isinstance(after, list):
        return [change for index, (left, right) in enumerate(zip(before, after))
                for change in _synthetic_changed_leaf_values(left, right, path + f"[{index}]")]
    if before == after:
        return []
    def preview(value):
        if isinstance(value, str):
            return {"value": value if len(value) <= 512 else value[:352] + "..." + value[-128:],
                    "truncated": len(value) > 512, "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        if isinstance(value, (dict, list)):
            return {"type": type(value).__name__, "sha256": hashlib.sha256(
                json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()}
        return {"value": value}
    return [{"path": path, "before": preview(before), "after": preview(after)}]


def test_w60b_persisted_outputs_and_their_redacted_views_do_not_move(archival_replay):
    _cases, _results, sources, scratch = archival_replay
    protected_prefixes = ("tests/golden/", "webapp/frontend/dist/", "atlas-scope/dist-hub/")
    protected_files = {"webapp/sample_data/sample_fleet.snapshot.json", "atlas-scope/src/data/fabric.json"}
    # The integration merge inherits current main's already-published frontend
    # bytes. Bind W60b-owned output custody to that exact main commit, while
    # proving each older BASE->main output delta is inherited without a rewrite.
    # This changes attribution only: every protected candidate path must equal
    # current main, and the original BASE golden/sample inputs and BOTH redacted
    # view byte oracles below remain mandatory. No artifact is regenerated.
    changed = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", CURRENT_MAIN, "HEAD"],
                                      cwd=ROOT).decode().splitlines()
    moved = [path for path in changed if path.startswith(protected_prefixes) or path in protected_files]
    assert moved == [], ("STOP: persisted engine output would move; do not regenerate", moved)
    inherited = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", BASE, CURRENT_MAIN],
                                        cwd=ROOT).decode().splitlines()
    inherited = [path for path in inherited if path.startswith(protected_prefixes) or path in protected_files]
    inherited_failures = []
    for path in inherited:
        published_entry = subprocess.check_output(["git", "ls-tree", "-z", CURRENT_MAIN, "--", path], cwd=ROOT)
        candidate_entry = subprocess.check_output(["git", "ls-tree", "-z", "HEAD", "--", path], cwd=ROOT)
        # Git entries bind mode, type and content blob; both empty proves an
        # inherited deletion. Added, changed and removed paths are all checked.
        if candidate_entry != published_entry:
            inherited_failures.append(path)
    print(json.dumps({"output_custody_main": CURRENT_MAIN, "candidate_owned_output_changes": moved,
                      "exact_inherited_output_paths": inherited, "inherited_output_failures": inherited_failures}))
    assert inherited_failures == [], ("STOP: inherited published output bytes differ from current main", inherited_failures)
    inputs = []
    for name in ("tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json"):
        raw = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT)
        current_raw = subprocess.check_output(["git", "show", CURRENT_MAIN + ":" + name], cwd=ROOT)
        assert current_raw == raw, ("STOP: current-main persisted input differs from W60 baseline", name, CURRENT_MAIN)
        assert (ROOT / name).read_bytes().replace(b"\r\n", b"\n") == raw
        path = scratch / Path(name).name
        path.write_bytes(raw)
        inputs.append(str(path))
    outputs = {}
    for ref in (BASE, CURRENT_MAIN, "candidate"):
        destination = scratch / (ref + "-views")
        destination.mkdir()
        subprocess.run([sys.executable, "-I", "-B", "-c", _SNAPSHOT_SCRIPT, str(sources[ref]),
                        json.dumps(inputs), str(destination)], cwd=scratch, check=True, timeout=180)
        outputs[ref] = destination
    verdicts = []
    for ref in (BASE, CURRENT_MAIN):
        for path in inputs:
            name = Path(path).name + ".redacted.json"
            before = (outputs[ref] / name).read_bytes()
            after = (outputs["candidate"] / name).read_bytes()
            changed_leaves = _changed_leaf_paths(json.loads(before), json.loads(after)) if before != after else []
            verdict = {"baseline_ref": ref, "view": name, "byte_identical": before == after,
                       "before_sha256": hashlib.sha256(before).hexdigest(),
                       "after_sha256": hashlib.sha256(after).hexdigest(), "changed_leaf_paths": changed_leaves}
            verdicts.append(verdict)
            print(json.dumps(verdict))
            if before != after:
                print(json.dumps({"synthetic_view": name, "baseline_ref": ref,
                                  "changed_scalar_values": _synthetic_changed_leaf_values(
                                      json.loads(before), json.loads(after))}, ensure_ascii=True))
    # Collect golden AND sample on BOTH immutable oracles before refusing. The
    # all-views byte equality gate is unchanged; failure diagnostics hold paths
    # and digests instead of dumping the complete synthetic engine snapshots.
    failures = [verdict for verdict in verdicts if not verdict["byte_identical"]]
    assert failures == [], ("STOP: existing redacted engine view would move; do not rebaseline", failures)
