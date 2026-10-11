"""W60b: independent-review examples, required slots and exact archival differentials.

Corpus expectations are authored from credential grammar, never harvested from
the candidate. Expensive archive and persisted-view comparisons run in the
separate hosted W60b lane; ordinary corpus and work-bound tests also run in every
required Python leg. Nothing regenerates a repository artifact.
"""
import ast
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

from cisco_toolkit import html
from webapp.backend import redaction_verify as rv


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/w60b_redaction_corpus.json"
BASE = "0b411c16347a0f1651b88cae52b58555701e4db3"
MAIN = "2c927d0209e4c4928c3f29d8747d648f930ddade"
ROUND3 = "d05ff1aaea85d87ff474f3a9d425eeacfa99a10c"
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
    sources = {ref: _archive(ref, scratch) for ref in (MAIN, ROUND3, BASE)}
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


def test_w60b_persisted_outputs_and_their_redacted_views_do_not_move(archival_replay):
    _cases, _results, sources, scratch = archival_replay
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "HEAD"], cwd=ROOT).decode().splitlines()
    protected_prefixes = ("tests/golden/", "webapp/frontend/dist/", "atlas-scope/dist-hub/")
    protected_files = {"webapp/sample_data/sample_fleet.snapshot.json", "atlas-scope/src/data/fabric.json"}
    moved = [path for path in changed if path.startswith(protected_prefixes) or path in protected_files]
    assert moved == [], ("STOP: persisted engine output would move; do not regenerate", moved)
    inputs = []
    for name in ("tests/golden/snapshot.json", "webapp/sample_data/sample_fleet.snapshot.json"):
        raw = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT)
        assert (ROOT / name).read_bytes().replace(b"\r\n", b"\n") == raw
        path = scratch / Path(name).name
        path.write_bytes(raw)
        inputs.append(str(path))
    outputs = {}
    for ref in (BASE, "candidate"):
        destination = scratch / (ref + "-views")
        destination.mkdir()
        subprocess.run([sys.executable, "-I", "-B", "-c", _SNAPSHOT_SCRIPT, str(sources[ref]),
                        json.dumps(inputs), str(destination)], cwd=scratch, check=True, timeout=180)
        outputs[ref] = destination
    for path in inputs:
        name = Path(path).name + ".redacted.json"
        before = (outputs[BASE] / name).read_bytes()
        after = (outputs["candidate"] / name).read_bytes()
        changed_leaves = _changed_leaf_paths(json.loads(before), json.loads(after)) if before != after else []
        print(json.dumps({"view": name, "before_sha256": hashlib.sha256(before).hexdigest(),
                          "after_sha256": hashlib.sha256(after).hexdigest(), "changed_leaf_paths": changed_leaves}))
        assert before == after, ("STOP: existing redacted engine view would move; do not rebaseline", name,
                                 hashlib.sha256(before).hexdigest(), hashlib.sha256(after).hexdigest(), changed_leaves)
