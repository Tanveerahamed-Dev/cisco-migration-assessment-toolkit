"""Adversarial tests for the bounded QDP-001 operator-study kit."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest

from tools import atlas_r3_operator_study_scoring as scoring
from tools import build_atlas_r3_break_this_plan_operator_study as builder
from tools import run_atlas_r3_break_this_plan_campaign as campaign_runner


ROOT = Path(__file__).resolve().parents[1]


def _test_source() -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit_headers = (
        subprocess.run(
            ["git", "cat-file", "-p", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.split("\n\n", 1)[0]
        .splitlines()
    )
    parents = [line.removeprefix("parent ") for line in commit_headers if line.startswith("parent ")]
    return {
        "base_campaign_merge": builder.BASE_CAMPAIGN_MERGE,
        "commit": commit,
        "parents": parents,
        "source_state": "DIRTY_TEST_PREVIEW",
        "tree": tree,
    }


def _campaign() -> dict:
    return builder._build_source_campaign(_test_source())


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _build(tmp_path: Path, name: str = "kit") -> Path:
    output = tmp_path / name
    manifest = builder.build(output, source_identity=_test_source())
    assert manifest["status"] == "DIRTY_TEST_PREVIEW_NOT_DELIVERABLE"
    assert manifest["deliverable"] is False
    assert manifest["human_participant_count"] == 0
    return output


def _score(
    kit: Path,
    phase_a: dict,
    phase_b: dict,
    answer: dict | None = None,
    *,
    run_class: str = scoring.RUN_CLASS_SYNTHETIC,
) -> dict:
    answer_value = answer or _json(kit / "researcher-capsule" / "answer-key.json")
    answer_raw = scoring.canonical_json_bytes(answer_value)
    manifest = _json(kit / "study-manifest.json")
    expected = manifest["files"]["researcher-capsule/answer-key.json"]["digest"]
    return scoring.score_responses(
        phase_a,
        phase_b,
        answer_value,
        answer_key_digest=_sha(answer_raw),
        expected_answer_key_digest=expected,
        phase_a_lock_verified=True,
        phase_b_lock_verified=True,
        run_class=run_class,
    )


def _run_config(tmp_path: Path, participant: str = "SYNTHETIC-DRY-RUN") -> Path:
    value = {
        "schema": builder.RUN_CONFIG_SCHEMA,
        "run_class": scoring.RUN_CLASS_SYNTHETIC,
        "run_id": "run.0123456789abcdef",
        "participant_code": participant,
        "participant_contact_ref": "contact.000000000001",
        "withdrawal_contact_ref": "contact.000000000002",
        "accessibility_contact_ref": "contact.000000000003",
        "purpose_profile": scoring.PURPOSE_PROFILE,
        "session_cap_minutes": 60,
        "data_use_profile": scoring.DATA_USE_PROFILE,
        "storage_profile": scoring.STORAGE_PROFILE,
        "access_profile": scoring.ACCESS_PROFILE,
        "retention_days": 30,
        "deletion_profile": scoring.DELETION_PROFILE,
        "data_policy_ref": "policy.000000000001",
        "recording_planned": False,
    }
    path = tmp_path / "run-config.json"
    path.write_bytes(builder._canonical_json(value))
    return path


def _stage_chain(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    master = _build(tmp_path)
    phase_a = tmp_path / "phase-a"
    builder.release_phase_a(
        master,
        _run_config(tmp_path),
        phase_a,
        allow_dirty_test_preview=True,
    )
    fixture = master / "researcher-capsule" / "fixtures"
    phase_a_response = tmp_path / "phase-a-response.json"
    phase_a_response.write_bytes((fixture / "response-n.phase-a.json").read_bytes())
    phase_a_lock = tmp_path / "phase-a-lock.json"
    builder.lock_response(
        master,
        phase_a,
        phase_a_response,
        phase_a_lock,
        expected_stage="PHASE_A",
        recorded_at="2026-08-31T20:00:00+00:00",
        allow_dirty_test_preview=True,
    )
    phase_b = tmp_path / "phase-b"
    builder.release_phase_b(
        master,
        phase_a,
        phase_a_response,
        phase_a_lock,
        phase_b,
        allow_dirty_test_preview=True,
    )
    phase_b_response = tmp_path / "phase-b-response.json"
    phase_b_response.write_bytes((fixture / "response-n.phase-b.json").read_bytes())
    phase_b_lock = tmp_path / "phase-b-lock.json"
    builder.lock_response(
        master,
        phase_b,
        phase_b_response,
        phase_b_lock,
        expected_stage="PHASE_B",
        recorded_at="2026-08-31T20:30:00+00:00",
        allow_dirty_test_preview=True,
    )
    return {
        "master": master,
        "phase_a": phase_a,
        "phase_a_response": phase_a_response,
        "phase_a_lock": phase_a_lock,
        "phase_b": phase_b,
        "phase_b_response": phase_b_response,
        "phase_b_lock": phase_b_lock,
    }


def _reseal_directory(root: Path, manifest_name: str) -> None:
    manifest_path = root / manifest_name
    manifest = _json(manifest_path)
    for name in manifest["files"]:
        raw = root.joinpath(*Path(name).parts).read_bytes()
        manifest["files"][name] = {"bytes": len(raw), "digest": _sha(raw)}
    manifest_raw = builder._canonical_json(manifest) + b"\n"
    manifest_path.write_bytes(manifest_raw)
    rows = []
    for name in sorted(set(manifest["files"]) | {manifest_name}):
        raw = root.joinpath(*Path(name).parts).read_bytes()
        rows.append(f"{hashlib.sha256(raw).hexdigest()}  {name}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="ascii", newline="\n")


def test_exact_package_builds_deterministically_and_verifies(tmp_path: Path) -> None:
    first = _build(tmp_path, "first")
    second = _build(tmp_path, "second")
    first_files = {item.relative_to(first).as_posix(): item.read_bytes() for item in first.rglob("*") if item.is_file()}
    second_files = {
        item.relative_to(second).as_posix(): item.read_bytes() for item in second.rglob("*") if item.is_file()
    }
    assert first_files == second_files
    run = subprocess.run(
        [sys.executable, "-B", str(first / "verify-study.py")],
        cwd=first,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    assert run.stdout.startswith("PASS:")


def test_campaign_is_recomputed_with_runtime_bound_result_digest() -> None:
    first = _campaign()
    second = _campaign()
    assert first["input_raw"] == second["input_raw"]
    assert first["result_raw"] == second["result_raw"]
    assert first["report_raw"] == second["report_raw"]
    assert _sha(first["input_raw"]) == scoring.EXPECTED_CAMPAIGN_INPUT_DIGEST
    result_digest = _sha(first["result_raw"])
    assert result_digest == first["manifest"]["files"]["campaign-result.json"]["digest"]
    assert result_digest == builder.EXPECTED_FILE_DIGESTS["campaign-result.json"]
    expected_discovery_semantics = campaign_runner._expected_discovery_semantics_digest()
    assert first["result"]["discovery_semantics_digests"] == [expected_discovery_semantics]
    assert first["result"]["campaign_semantics_digest"] == campaign_runner._campaign_semantics_digest(
        [expected_discovery_semantics]
    )
    assert _sha(first["report_raw"]) == ("sha256:257fa730cc30f0ea7a8904c0bc4f0bbda708e01b4b707eadddf769ef4e92b947")


def test_researcher_campaign_bytes_are_exact_replay_inputs(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    campaign = _campaign()
    input_path = kit / "researcher-capsule" / "campaign-input.json"
    result_path = kit / "researcher-capsule" / "campaign-result.json"
    assert input_path.read_bytes() == campaign["input_raw"]
    assert result_path.read_bytes() == campaign["result_raw"]
    assert campaign_runner.analyze_campaign_bytes(input_path.read_bytes()) == (result_path.read_bytes())


def test_phase_a_is_contextually_blinded_and_aliases_do_not_collapse(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    manifest = _json(kit / "study-manifest.json")
    phase_a = "\n".join(
        item.read_text(encoding="utf-8") for item in (kit / "participant-phase-a").rglob("*") if item.is_file()
    )
    for token in manifest["phase_a_forbidden_tokens"]:
        assert token not in phase_a
    assert "Model observation" not in phase_a
    for priming_token in (
        "REPRODUCED_SYNTHETIC_OBSERVED_DISCARD_ONLY",
        "NO_SUPPORT_OR_SAFETY_INFERENCE",
        "TRUST_CUSTODY_PROOF",
        "replay_nonclaims",
        "forbidden_claims",
    ):
        assert priming_token not in phase_a
    assert not builder._phase_a_semantic_cue(phase_a.encode("utf-8"))
    assert manifest["phase_a_forbidden_cue_patterns"] == list(builder.PHASE_A_FORBIDDEN_CUE_PATTERNS)
    assert manifest["known_residuals"] == list(builder.EXPECTED_KNOWN_RESIDUALS)
    residual_text = "\n".join(manifest["known_residuals"])
    for current_world_claim in ("NOT_PUSHED", "NOT_MERGED", "HAS_BEEN_RUN"):
        assert current_world_claim not in residual_text
    assert "Node A reaches the required destination network" in phase_a
    assert not any(
        item.suffix.lower() in {".json", ".csv"}
        for root in (
            kit / "participant-phase-a",
            kit / "participant-phase-b",
            kit / "participant-debrief",
        )
        for item in root.rglob("*")
    )


def test_standalone_phase_a_includes_no_later_answer_or_boundary_manifest(
    tmp_path: Path,
) -> None:
    master = _build(tmp_path)
    phase_a = tmp_path / "phase-a"
    builder.release_phase_a(
        master,
        _run_config(tmp_path),
        phase_a,
        allow_dirty_test_preview=True,
    )
    manifest = _json(phase_a / "stage-manifest.json")
    assert set(manifest) == set(builder.STAGE_MANIFEST_KEYS)
    for key in (
        "authoritative",
        "decision_effect",
        "authentication",
        "custody_proved",
        "trusted_time",
    ):
        assert key not in manifest
    complete_phase_a = {
        path.relative_to(phase_a).as_posix(): path.read_bytes() for path in phase_a.rglob("*") if path.is_file()
    }
    assert not any(builder._phase_a_semantic_cue(raw) for raw in complete_phase_a.values())
    assert "Download Phase A response" in (phase_a / "03-response.html").read_text(encoding="utf-8")
    assert "Download locked Phase A response" not in (phase_a / "03-response.html").read_text(encoding="utf-8")
    participant_information = (phase_a / "PARTICIPANT-INFORMATION.md").read_text(encoding="utf-8")
    for expected in (
        "Understand how people reason about one synthetic migration plan.",
        "contact.000000000001",
        "contact.000000000002",
        "contact.000000000003",
        "Use responses only to evaluate this formative plan-reasoning study.",
        "Store responses in an encrypted internal study workspace.",
        "Limit response access to the moderator and two assigned narrative reviewers.",
        "Retention: 30 days.",
        "policy.000000000001",
    ):
        assert expected in participant_information

    campaign = _campaign()
    aliases = builder._aliases(campaign["input"], campaign["result"])
    step_total = sum(len(candidate["steps"]) for case in campaign["input"]["cases"] for candidate in case["candidates"])
    requirement_total = sum(len(case["requirements"]) for case in campaign["input"]["cases"])
    assert len(aliases["contextual_aliases"]["steps"]) == step_total
    assert len(aliases["contextual_aliases"]["requirements"]) == requirement_total

    reversed_input = deepcopy(campaign["input"])
    reversed_result = deepcopy(campaign["result"])
    reversed_input["cases"].reverse()
    reversed_result["case_reports"].reverse()
    reversed_aliases = builder._aliases(reversed_input, reversed_result)
    truth = builder._ground_truth(reversed_aliases, reversed_result)
    witness = truth["witness"]
    contextual = reversed_aliases["contextual_aliases"]
    assert (
        truth["phase_a"]["unsafe_step_alias"]
        == contextual["steps"][f"{witness['case_id']}|{witness['candidate_id']}|{witness['step_id']}"]
    )


def test_browser_equivalent_n_passes_but_n_minus_one_and_n_plus_one_fail(
    tmp_path: Path,
) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    phase_a = _json(fixture / "response-n.phase-a.json")
    phase_b = _json(fixture / "response-n.phase-b.json")
    assert phase_b["global_limitations"] == sorted(phase_b["global_limitations"])
    assert all(value == sorted(value) for value in phase_b["candidate_limitations"].values())
    exact = _score(kit, phase_a, phase_b)
    assert exact["automated_critical_checks_pass"] is True
    assert exact["participant_pass"] is None
    assert exact["operator_acceptance"] is False
    assert exact["primary_cohort_structural_conditions_met"] is True
    assert exact["declared_primary_cohort_conditions_met"] is False
    assert exact["primary_cohort_eligible"] is None
    assert exact["human_participant_established"] is None
    assert exact["disposition"] == "SYNTHETIC_DRY_RUN_TOOLING_ONLY"

    declared_human_a = deepcopy(phase_a)
    declared_human_b = deepcopy(phase_b)
    declared_human_a["participant_code"] = "p.0123456789ab"
    declared_human_b["participant_code"] = "p.0123456789ab"
    declared_human = _score(
        kit,
        declared_human_a,
        declared_human_b,
        run_class=scoring.RUN_CLASS_HUMAN,
    )
    assert declared_human["automated_critical_checks_pass"] is True
    assert declared_human["declared_primary_cohort_conditions_met"] is True
    assert declared_human["primary_cohort_eligible"] is None
    assert declared_human["human_participant_established"] is None
    assert declared_human["disposition"] == ("AUTOMATED_CHECKS_PASS_HUMAN_ORIGIN_AND_MANUAL_REVIEW_UNVERIFIED")

    missing = _score(kit, phase_a, _json(fixture / "response-n-minus-1.phase-b.json"))
    extra = _score(kit, phase_a, _json(fixture / "response-n-plus-1.phase-b.json"))
    assert missing["automated_critical_checks_pass"] is False
    assert extra["automated_critical_checks_pass"] is False
    assert any(
        row["check_id"] == "phase_b_global_limitations" and not row["passed"] for row in missing["automated_checks"]
    )


def test_hostile_identity_is_not_echoed_and_assistance_is_separate_from_comprehension(
    tmp_path: Path,
) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    hostile = _json(fixture / "response-hostile.phase-a.json")
    phase_b = _json(fixture / "response-n.phase-b.json")
    score = _score(kit, hostile, phase_b)
    assert score["participant_code"] is None
    assert score["automated_critical_checks_pass"] is False
    assert score["primary_cohort_eligible"] is None

    phase_a = _json(fixture / "response-n.phase-a.json")
    assisted_a = deepcopy(phase_a)
    assisted_b = deepcopy(phase_b)
    assisted_a["prompt_code"] = assisted_b["prompt_code"] = "P1"
    assisted = _score(kit, assisted_a, assisted_b)
    assert assisted["automated_critical_checks_pass"] is True
    assert assisted["primary_cohort_eligible"] is None
    assert assisted["primary_cohort_structural_conditions_met"] is False
    assert assisted["disposition"] == "SYNTHETIC_DRY_RUN_TOOLING_ONLY"

    malformed_a = deepcopy(phase_a)
    malformed_b = deepcopy(phase_b)
    malformed_a["prompt_code"] = {"not": "a closed code"}
    malformed_b["prompt_code"] = ["P0"]
    malformed_a["prior_exposure"] = {"not": "a closed value"}
    malformed = _score(kit, malformed_a, malformed_b)
    assert malformed["automated_technical_checks_pass"] is False
    assert malformed["primary_cohort_eligible"] is None
    assert {row["check_id"] for row in malformed["automated_checks"] if not row["passed"]} >= {
        "phase_a_prompt_code_domain",
        "phase_b_prompt_code_domain",
        "phase_a_prior_exposure_domain",
    }

    declined = deepcopy(phase_a)
    declined["voluntary_consent"] = False
    declined_score = _score(kit, declined, phase_b)
    assert declined_score["automated_critical_checks_pass"] is False
    assert declined_score["primary_cohort_eligible"] is None


def test_answer_key_is_digest_bound_and_empty_subset_exploit_is_refused(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    phase_a = _json(fixture / "response-n.phase-a.json")
    phase_b = _json(fixture / "response-n.phase-b.json")
    answer = _json(kit / "researcher-capsule" / "answer-key.json")
    empty = deepcopy(answer)
    empty["phase_a"] = {}
    empty["phase_b"] = {}
    empty["replay_nonclaims"] = []
    empty["forbidden_claim_keys"] = []
    empty_digest = _sha(scoring.canonical_json_bytes(empty))
    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.score_responses(
            phase_a,
            phase_b,
            empty,
            answer_key_digest=empty_digest,
            expected_answer_key_digest=empty_digest,
        )
    assert exc.value.code == "ANSWER_KEY_INVALID"

    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.score_responses(
            phase_a,
            phase_b,
            answer,
            answer_key_digest=_sha(scoring.canonical_json_bytes(answer)),
            expected_answer_key_digest="sha256:" + "0" * 64,
        )
    assert exc.value.code == "ANSWER_KEY_INVALID"


def test_deep_duplicate_and_oversized_json_fail_with_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(
            scoring.json,
            "loads",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RecursionError()),
        )
        with pytest.raises(scoring.StudyScoringError) as exc:
            scoring.parse_json_bytes(b"{}")
        assert exc.value.code == "JSON_NESTING_OR_NODE_LIMIT"

    deep = ("[" * 2_000 + "0" + "]" * 2_000).encode("ascii")
    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.parse_json_bytes(deep)
    assert exc.value.code == "JSON_NESTING_OR_NODE_LIMIT"
    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.parse_json_bytes(b'{"a":1,"a":2}')
    assert exc.value.code == "DUPLICATE_JSON_KEY"
    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.parse_json_bytes(b"x" * (scoring.MAX_RESPONSE_BYTES + 1))
    assert exc.value.code == "JSON_BYTE_LIMIT_OR_EMPTY"

    def worksheet(payload: bytes) -> bytes:
        return b"# hostile worksheet\n\n" + builder.WORKSHEET_FENCE.encode("utf-8") + b"\n" + payload + b"\n```\n"

    for payload in (deep, b'{"a":1,"a":2}'):
        with pytest.raises(builder.StudyBuildError) as exc:
            builder.parse_worksheet_response_bytes(worksheet(payload), expected_phase="A")
        assert exc.value.code == "WORKSHEET_RESPONSE_INVALID"
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.parse_worksheet_response_bytes(
            worksheet(b"x" * scoring.MAX_RESPONSE_BYTES),
            expected_phase="A",
        )
    assert exc.value.code == "WORKSHEET_BYTE_LIMIT_OR_EMPTY"


def test_response_schemas_validate_n_and_reject_malformed_shape(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    for phase in ("a", "b"):
        schema = _json(kit / "schemas" / f"phase-{phase}-response.schema.json")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        response = _json(fixture / f"response-n.phase-{phase}.json")
        validator.validate(response)
        malformed = deepcopy(response)
        malformed["participant_code"] = "../escape"
        assert list(validator.iter_errors(malformed))
        malformed = deepcopy(response)
        malformed["unexpected"] = True
        assert list(validator.iter_errors(malformed))


def test_html_source_accessibility_and_offline_contract(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    html_files = list((kit / "participant-phase-a").glob("*.html"))
    html_files += list((kit / "participant-phase-b").glob("*.html"))
    html_files += list((kit / "participant-debrief").glob("*.html"))
    assert html_files
    for path in html_files:
        text = path.read_text(encoding="utf-8")
        assert '<html lang="en">' in text
        assert 'name="viewport"' in text
        assert "<h1>" in text and "<title>" in text
        assert ":focus-visible" in text
        assert "box-sizing:border-box" in text
        assert "fieldset{margin:1rem 0;padding:1rem;min-width:0}" in text
        assert "@media(max-width:40rem)" in text
        assert 'href="http' not in text and 'src="http' not in text
    for name in ("03-response.html", "05-response.html"):
        path = next(item for item in html_files if item.name == name)
        text = path.read_text(encoding="utf-8")
        assert text.count("<label") >= text.count("<select") + text.count("<textarea")
        assert 'maxlength="8192"' in text and 'minlength="20"' in text
        assert 'role="status"' in text
        assert "Array.from(field.value.trim()).length" in text
    report = (kit / "participant-phase-b" / "index.html").read_text(encoding="utf-8")
    assert 'scope="col"' in report and 'scope="row"' in report
    assert "Accessible case and candidate results" in report
    assert "Meaning unavailable" not in report
    semantic_report = report.split("<details>", 1)[0]
    for value in (
        builder.EXPECTED_BOUNDARY["release_2"],
        builder.EXPECTED_BOUNDARY["runtime"],
        builder.EXPECTED_BOUNDARY["release_3"],
        "EXPERIMENTAL / CONTRACT_ONLY",
        "R2-AUTH-001",
        "R2-AUTH-002",
        "R2-AUTH-004",
        "selection receipt <code>null</code>",
        "workload collection started <code>false</code>",
    ):
        assert str(value) in semantic_report
    phase_b_response = (kit / "participant-phase-b" / "05-response.html").read_text(encoding="utf-8")
    focus_stops = len(re.findall(r"<(?:input|select|textarea|button)\b", phase_b_response))
    assert focus_stops <= 64
    assert "Reuse the exact participant code from Phase A" in phase_b_response
    for root in (kit / "participant-phase-a", kit / "participant-phase-b"):
        assert (root / "index.html").is_file()
        assert (root / "RESPONSE-WORKSHEET.md").is_file()
        assert "%~dp0index.html" in (root / "START.cmd").read_text(encoding="utf-8")
        response = next(root.glob("*response.html"))
        assert "RESPONSE-WORKSHEET.md" in response.read_text(encoding="utf-8")
    worksheet_b = (kit / "participant-phase-b" / "RESPONSE-WORKSHEET.md").read_text(encoding="utf-8")
    for value in scoring.EXPECTED_REPLAY_NONCLAIMS + scoring.EXPECTED_FORBIDDEN_CLAIM_KEYS:
        assert value in worksheet_b
    assert builder.WORKSHEET_FENCE in worksheet_b
    assert builder.WORKSHEET_PLACEHOLDER in worksheet_b
    debrief = (kit / "participant-debrief" / "index.html").read_text(encoding="utf-8")
    for text in (
        "Plan D3",
        "Step D3.2",
        "Requirement D-R1",
        "__NONE_EMITTED__",
        "Campaign-global limitations",
    ):
        assert text in debrief


def test_generated_browser_serializers_are_valid_javascript(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    for name in (
        "participant-phase-a/03-response.html",
        "participant-phase-b/05-response.html",
    ):
        text = (kit / name).read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", text, flags=re.DOTALL)
        assert len(scripts) == 1
        script_path = tmp_path / (Path(name).stem + ".js")
        script_path.write_text(scripts[0], encoding="utf-8", newline="\n")
        run = subprocess.run(
            ["node", "--check", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr


def test_verifier_rejects_tampered_payload_and_extra_member(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    target = kit / "participant-phase-a" / "02-neutral-plan.html"
    target.write_text(target.read_text(encoding="utf-8") + "tamper", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-B", str(kit / "verify-study.py")],
        cwd=kit,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "FILE_BINDING" in run.stdout

    clean = _build(tmp_path, "clean")
    (clean / "unexpected.txt").write_text("extra", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-B", str(clean / "verify-study.py")],
        cwd=clean,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "PACKAGE_MEMBER_SET" in run.stdout


def test_fixed_nonpromotion_and_technical_evidence_are_retained(tmp_path: Path) -> None:
    kit = _build(tmp_path)
    manifest = _json(kit / "study-manifest.json")
    assert manifest["product_boundary"] == builder.EXPECTED_BOUNDARY
    assert manifest["authority_placeholders"] == {
        "R2-AUTH-001": None,
        "R2-AUTH-002": None,
        "R2-AUTH-004": None,
    }
    assert manifest["collection_started"] is False
    evidence = (kit / "researcher-capsule" / "technical-evidence.md").read_text(encoding="utf-8")
    for text in (
        "Exact local source",
        builder.BASE_CAMPAIGN_MERGE,
        "Same-process full-mapping agreement",
        "1,024-replay",
        "NVDA",
        "unkeyed self-consistency bindings",
    ):
        assert text in evidence


def test_source_files_are_lint_clean_and_builder_refuses_existing_output(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.build(existing, source_identity=_test_source())
    assert exc.value.code == "OUTPUT_ALREADY_EXISTS"
    assert builder.STUDY_ID == scoring.EXPECTED_STUDY_ID
    assert builder.EXPECTED_FILE_DIGESTS["campaign-input.json"] == (scoring.EXPECTED_CAMPAIGN_INPUT_DIGEST)
    assert scoring.EXPECTED_ANSWER_KEY_DIGEST != "sha256:" + "0" * 64


def test_no_javascript_round_trip_matches_browser_model_and_scorer(
    tmp_path: Path,
) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    parsed: dict[str, dict] = {}
    for phase, name in (("A", "response-n.phase-a.json"), ("B", "response-n.phase-b.json")):
        response = _json(fixture / name)
        worksheet = builder.response_to_worksheet_bytes(phase, response)
        canonical, value = builder.parse_worksheet_response_bytes(worksheet, expected_phase=phase)
        assert value == response
        assert canonical == scoring.canonical_json_bytes(response)
        path = tmp_path / f"response-{phase}.md"
        path.write_bytes(worksheet)
        _raw, scorer_value = scoring.load_response_file(path)
        assert scorer_value == response
        parsed[phase] = value

    ordered_b = _json(fixture / "response-n.phase-b.json")
    report_order_b = deepcopy(ordered_b)
    report_order_b["global_limitations"].reverse()
    report_order_b["replay_nonclaims"].reverse()
    for mapping_name in ("candidate_limitations", "next_evidence_by_case"):
        for values in report_order_b[mapping_name].values():
            values.reverse()
    report_order_worksheet = builder.response_to_worksheet_bytes("B", report_order_b)
    crlf_worksheet = report_order_worksheet.replace(b"\n", b"\r\n")
    canonical_b, normalized_b = builder.parse_worksheet_response_bytes(crlf_worksheet, expected_phase="B")
    assert normalized_b == ordered_b
    assert canonical_b == scoring.canonical_json_bytes(ordered_b)
    crlf_path = tmp_path / "response-B-crlf-report-order.md"
    crlf_path.write_bytes(crlf_worksheet)
    preserved_raw, scorer_normalized_b = scoring.load_response_file(crlf_path)
    assert preserved_raw == crlf_worksheet
    assert scorer_normalized_b == ordered_b
    browser_score = _score(
        kit,
        _json(fixture / "response-n.phase-a.json"),
        _json(fixture / "response-n.phase-b.json"),
    )
    worksheet_score = _score(kit, parsed["A"], parsed["B"])
    assert worksheet_score == browser_score
    assert _score(kit, parsed["A"], scorer_normalized_b) == browser_score

    duplicate_b = deepcopy(ordered_b)
    duplicate_b["global_limitations"].append(duplicate_b["global_limitations"][0])
    duplicate_worksheet = builder.response_to_worksheet_bytes("B", duplicate_b)
    _duplicate_raw, normalized_duplicate_b = builder.parse_worksheet_response_bytes(
        duplicate_worksheet, expected_phase="B"
    )
    assert _score(kit, parsed["A"], normalized_duplicate_b)["automated_critical_checks_pass"] is False

    n_a = _json(fixture / "response-n.phase-a.json")
    for name in (
        "response-n-minus-1.phase-b.json",
        "response-n-plus-1.phase-b.json",
    ):
        browser_b = _json(fixture / name)
        worksheet = builder.response_to_worksheet_bytes("B", browser_b)
        _canonical, worksheet_b = builder.parse_worksheet_response_bytes(worksheet, expected_phase="B")
        assert _score(kit, n_a, worksheet_b) == _score(kit, n_a, browser_b)
        assert _score(kit, n_a, worksheet_b)["automated_critical_checks_pass"] is False

    hostile_a = _json(fixture / "response-hostile.phase-a.json")
    hostile_worksheet = builder.response_to_worksheet_bytes("A", hostile_a)
    _canonical, parsed_hostile = builder.parse_worksheet_response_bytes(hostile_worksheet, expected_phase="A")
    assert _score(kit, parsed_hostile, parsed["B"]) == _score(kit, hostile_a, parsed["B"])
    assert _score(kit, parsed_hostile, parsed["B"])["automated_critical_checks_pass"] is False

    blank = builder._phase_a_worksheet(_campaign()).encode("utf-8")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.parse_worksheet_response_bytes(blank, expected_phase="A")
    assert exc.value.code == "WORKSHEET_RESPONSE_INVALID"


def test_reordered_browser_json_preserves_raw_bytes_and_normalizes_lock(
    tmp_path: Path,
) -> None:
    chain = _stage_chain(tmp_path)
    ordered = _json(chain["phase_b_response"])
    reordered = deepcopy(ordered)
    reordered["global_limitations"].reverse()
    reordered["replay_nonclaims"].reverse()
    for mapping_name in ("candidate_limitations", "next_evidence_by_case"):
        for values in reordered[mapping_name].values():
            values.reverse()
    reordered_raw = scoring.canonical_json_bytes(reordered)
    ordered_raw = scoring.canonical_json_bytes(ordered)
    assert reordered_raw != ordered_raw
    response_path = tmp_path / "phase-b-response-report-order.json"
    response_path.write_bytes(reordered_raw)
    lock_path = tmp_path / "phase-b-report-order-lock.json"
    builder.lock_response(
        chain["master"],
        chain["phase_b"],
        response_path,
        lock_path,
        expected_stage="PHASE_B",
        recorded_at="2026-08-31T20:31:00+00:00",
        allow_dirty_test_preview=True,
    )
    receipt = _json(lock_path)
    assert receipt["response_raw_digest"] == _sha(reordered_raw)
    assert receipt["response_canonical_digest"] == _sha(ordered_raw)
    manifest_raw = (chain["master"] / "study-manifest.json").read_bytes()
    source = _json(chain["master"] / "study-manifest.json")["source_campaign"]["recomputed_at_source"]
    _receipt_raw, normalized = scoring.verify_response_lock(
        chain["phase_b"],
        response_path,
        lock_path,
        expected_stage="PHASE_B",
        expected_master_manifest_digest=_sha(manifest_raw),
        expected_source_commit=source["commit"],
        expected_source_tree=source["tree"],
    )
    assert normalized == ordered


def test_stage_chain_is_physically_separate_and_debrief_is_gated(
    tmp_path: Path,
) -> None:
    chain = _stage_chain(tmp_path)
    _raw_a, stage_a = builder.verify_stage(chain["phase_a"], expected_stage="PHASE_A")
    _raw_b, stage_b = builder.verify_stage(chain["phase_b"], expected_stage="PHASE_B")
    assert set(stage_a["files"]) == set(builder.PHASE_A_STAGE_MEMBERS)
    assert set(stage_b["files"]) == set(builder.PHASE_B_STAGE_MEMBERS)
    assert stage_a["predecessor_lock_digest"] is None
    assert not {"source_commit", "source_tree", "source_state"} & set(stage_a)
    assert stage_b["predecessor_lock_digest"] == _sha(chain["phase_a_lock"].read_bytes())
    assert not any(
        token in path.name.lower()
        for path in chain["phase_a"].rglob("*")
        for token in ("phase-b", "debrief", "answer-key", "researcher")
    )
    debrief = tmp_path / "debrief"
    builder.release_debrief(
        chain["master"],
        chain["phase_b"],
        chain["phase_b_response"],
        chain["phase_b_lock"],
        debrief,
        allow_dirty_test_preview=True,
    )
    _raw_d, stage_d = builder.verify_stage(debrief, expected_stage="DEBRIEF")
    assert set(stage_d["files"]) == set(builder.DEBRIEF_STAGE_MEMBERS)
    assert stage_d["predecessor_lock_digest"] == _sha(chain["phase_b_lock"].read_bytes())

    second = tmp_path / "phase-a-second"
    builder.release_phase_a(
        chain["master"],
        _run_config(tmp_path),
        second,
        allow_dirty_test_preview=True,
    )
    first_bytes = {
        path.relative_to(chain["phase_a"]).as_posix(): path.read_bytes()
        for path in chain["phase_a"].rglob("*")
        if path.is_file()
    }
    second_bytes = {
        path.relative_to(second).as_posix(): path.read_bytes() for path in second.rglob("*") if path.is_file()
    }
    assert first_bytes == second_bytes


def test_phase_a_mutation_cross_participant_and_extra_member_refuse_release(
    tmp_path: Path,
) -> None:
    chain = _stage_chain(tmp_path)
    original = chain["phase_a_response"].read_bytes()
    changed = json.loads(original)
    changed["explanation"] += " changed after Phase B exposure"
    chain["phase_a_response"].write_bytes(scoring.canonical_json_bytes(changed))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_b(
            chain["master"],
            chain["phase_a"],
            chain["phase_a_response"],
            chain["phase_a_lock"],
            tmp_path / "refused-mutated",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "LOCK_RECEIPT_BINDING_INVALID"

    chain["phase_a_response"].write_bytes(original)
    other = json.loads(original)
    other["participant_code"] = "OTHER-PARTICIPANT"
    chain["phase_a_response"].write_bytes(scoring.canonical_json_bytes(other))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.lock_response(
            chain["master"],
            chain["phase_a"],
            chain["phase_a_response"],
            tmp_path / "other-lock.json",
            expected_stage="PHASE_A",
            recorded_at="2026-08-31T20:00:00+00:00",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code in {
        "RESPONSE_SCHEMA_REFUSED",
        "RESPONSE_STAGE_BINDING_INVALID",
    }

    chain["phase_a_response"].write_bytes(original)
    (chain["phase_a"] / "participant-phase-b-leak.txt").write_text("later stage", encoding="utf-8")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_stage(chain["phase_a"], expected_stage="PHASE_A")
    assert exc.value.code == "STAGE_MEMBER_SET_INVALID"


def test_run_config_placeholders_and_resealed_lock_are_refused(tmp_path: Path) -> None:
    master = _build(tmp_path)
    bad = tmp_path / "bad-config.json"
    bad.write_bytes(builder._canonical_json(builder._run_config_template()))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            bad,
            tmp_path / "bad-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"

    config = _json(_run_config(tmp_path))
    config["purpose_profile"] = "FOR_THIS_SESSION_CHOOSE_PLAN_D3"
    cue = tmp_path / "answer-cue.json"
    cue.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            cue,
            tmp_path / "answer-cue-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"

    config = _json(_run_config(tmp_path))
    config["recording_planned"] = False
    config["purpose_profile"] = "![remote](https://example.invalid/participant-data)"
    hostile = tmp_path / "hostile.json"
    hostile.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            hostile,
            tmp_path / "hostile-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"

    chain = _stage_chain(tmp_path / "chain")
    forged = _json(chain["phase_a_lock"])
    forged["response_raw_digest"] = "sha256:" + "0" * 64
    chain["phase_a_lock"].write_bytes(builder._canonical_json(forged) + b"\n")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_b(
            chain["master"],
            chain["phase_a"],
            chain["phase_a_response"],
            chain["phase_a_lock"],
            tmp_path / "forged-phase-b",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "LOCK_RECEIPT_BINDING_INVALID"


@pytest.mark.parametrize(
    "cue",
    [
        "This study chooses no proposal.",
        "No observation work may begin.",
        "This does not make QCP-001 ready.",
        "This does not advance a release.",
        "This is not for public availability.",
        "This does not establish chain of handling.",
        "This is non-authoritative.",
        "Replay is not trust or custody.",
        "No candidate support follows.",
    ],
)
def test_run_config_later_answer_paraphrases_are_refused(
    tmp_path: Path,
    cue: str,
) -> None:
    master = _build(tmp_path)
    config = _json(_run_config(tmp_path))
    config["purpose_profile"] = cue
    path = tmp_path / "semantic-answer-cue.json"
    path.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            path,
            tmp_path / "semantic-answer-cue-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"


@pytest.mark.parametrize(
    ("run_class", "participant_code"),
    [
        (scoring.RUN_CLASS_HUMAN, scoring.SYNTHETIC_PARTICIPANT_CODE),
        (scoring.RUN_CLASS_SYNTHETIC, "p.0123456789ab"),
    ],
)
def test_run_class_and_participant_identity_must_reconcile(
    tmp_path: Path,
    run_class: str,
    participant_code: str,
) -> None:
    master = _build(tmp_path)
    config = _json(_run_config(tmp_path))
    config["run_class"] = run_class
    config["participant_code"] = participant_code
    path = tmp_path / "run-class-mismatch.json"
    path.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            path,
            tmp_path / "run-class-mismatch-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"


def test_declared_human_run_uses_opaque_identity_and_neutral_closed_profiles(
    tmp_path: Path,
) -> None:
    master = _build(tmp_path)
    config = _json(_run_config(tmp_path))
    config["run_class"] = scoring.RUN_CLASS_HUMAN
    config["participant_code"] = "p.0123456789ab"
    path = tmp_path / "human-run-config.json"
    path.write_bytes(builder._canonical_json(config))
    output = tmp_path / "human-phase-a"
    manifest = builder.release_phase_a(
        master,
        path,
        output,
        allow_dirty_test_preview=True,
    )
    assert manifest["run_config"]["run_class"] == scoring.RUN_CLASS_HUMAN
    assert manifest["participant_code"] == "p.0123456789ab"
    assert not any(builder._phase_a_semantic_cue(item.read_bytes()) for item in output.rglob("*") if item.is_file())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "run.semantic-answer"),
        ("participant_contact_ref", "contact.no-authority"),
        ("data_policy_ref", "policy.no-collection"),
        ("purpose_profile", "ARBITRARY_PARTICIPANT_VISIBLE_PROSE"),
        ("retention_days", 0),
        ("retention_days", 3_651),
    ],
)
def test_run_config_accepts_only_closed_profiles_and_opaque_references(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    master = _build(tmp_path)
    config = _json(_run_config(tmp_path))
    config[field] = value
    path = tmp_path / "run-config-closed-profile-refusal.json"
    path.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            path,
            tmp_path / "run-config-closed-profile-refusal-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"


def test_scorer_cli_requires_closed_master_and_both_lock_receipts(
    tmp_path: Path,
) -> None:
    chain = _stage_chain(tmp_path)
    scorer = chain["master"] / "researcher-capsule" / "score_response.py"
    args = [
        sys.executable,
        "-B",
        str(scorer),
        "--master",
        str(chain["master"]),
        "--phase-a",
        str(chain["phase_a_response"]),
        "--phase-a-stage",
        str(chain["phase_a"]),
        "--phase-a-lock",
        str(chain["phase_a_lock"]),
        "--phase-b",
        str(chain["phase_b_response"]),
        "--phase-b-stage",
        str(chain["phase_b"]),
        "--phase-b-lock",
        str(chain["phase_b_lock"]),
        "--allow-dirty-test-preview",
    ]
    run = subprocess.run(args, check=False, capture_output=True)
    assert run.returncode == 0, run.stderr.decode("utf-8", errors="replace")
    result = json.loads(run.stdout)
    assert result["automated_critical_checks_pass"] is False
    assert result["participant_pass"] is None
    assert result["source_state"] == "DIRTY_TEST_PREVIEW"
    assert result["primary_cohort_eligible"] is None
    assert result["human_participant_established"] is None
    assert result["disposition"] == "SYNTHETIC_DRY_RUN_TOOLING_ONLY"
    bindings = result["evidence_bindings"]
    assert bindings["authentication"] == "none"
    assert bindings["custody_proved"] is False
    assert bindings["run_id"] == "run.0123456789abcdef"
    assert bindings["run_class"] == scoring.RUN_CLASS_SYNTHETIC
    assert bindings["source_state"] == "DIRTY_TEST_PREVIEW"
    for key in (
        "master_manifest_digest",
        "phase_a_stage_manifest_digest",
        "phase_a_lock_receipt_digest",
        "phase_b_stage_manifest_digest",
        "phase_b_lock_receipt_digest",
        "run_config_digest",
    ):
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", bindings[key])
    assert {row["check_id"] for row in result["automated_checks"] if row["passed"]} >= {
        "structural_phase_a_lock_chain_verified",
        "structural_phase_b_lock_chain_verified",
    }

    changed = _json(chain["phase_a_response"])
    changed["explanation"] += " changed after lock"
    chain["phase_a_response"].write_bytes(scoring.canonical_json_bytes(changed))
    refused = subprocess.run(args, check=False, capture_output=True)
    assert refused.returncode == 2
    assert b"LOCK_RECEIPT_BINDING_INVALID" in refused.stderr


def test_source_answer_anchor_refuses_joint_answer_and_manifest_rewrite(
    tmp_path: Path,
) -> None:
    kit = _build(tmp_path)
    fixture = kit / "researcher-capsule" / "fixtures"
    phase_a = _json(fixture / "response-n.phase-a.json")
    phase_b = _json(fixture / "response-n.phase-b.json")
    answer = _json(kit / "researcher-capsule" / "answer-key.json")
    answer["phase_a"]["unsafe_step_alias"] = "Step D1.1"
    phase_a["unsafe_step_alias"] = "Step D1.1"
    forged_digest = _sha(scoring.canonical_json_bytes(answer))
    with pytest.raises(scoring.StudyScoringError) as exc:
        scoring.score_responses(
            phase_a,
            phase_b,
            answer,
            answer_key_digest=forged_digest,
            expected_answer_key_digest=forged_digest,
            phase_a_lock_verified=True,
            phase_b_lock_verified=True,
        )
    assert exc.value.code == "ANSWER_KEY_INVALID"


def test_master_joint_reseal_and_stage_link_reseal_are_refused(
    tmp_path: Path,
) -> None:
    master = _build(tmp_path)
    phase_a_html = master / "participant-phase-a" / "02-neutral-plan.html"
    phase_a_html.write_text(
        phase_a_html.read_text(encoding="utf-8") + "<p>COUNTEREXAMPLE Step D3.2</p>",
        encoding="utf-8",
    )
    manifest = _json(master / "study-manifest.json")
    manifest["phase_a_forbidden_tokens"] = []
    (master / "study-manifest.json").write_bytes(builder._canonical_json(manifest) + b"\n")
    _reseal_directory(master, "study-manifest.json")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_master_kit(master, allow_dirty_test_preview=True)
    assert exc.value.code == "MASTER_SOURCE_REGENERATION_MISMATCH"

    chain = _stage_chain(tmp_path / "stage")
    response_html = chain["phase_a"] / "03-response.html"
    response_html.write_text(
        response_html.read_text(encoding="utf-8") + '<a href="../phase-b/index.html">later stage</a>',
        encoding="utf-8",
    )
    _reseal_directory(chain["phase_a"], "stage-manifest.json")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_stage(chain["phase_a"], expected_stage="PHASE_A")
    assert exc.value.code == "STAGE_LINK_BOUNDARY_INVALID"

    semantic_chain = _stage_chain(tmp_path / "semantic-stage")
    participant_info = semantic_chain["phase_a"] / "PARTICIPANT-INFORMATION.md"
    participant_info.write_text(
        participant_info.read_text(encoding="utf-8") + "\nThis study chooses no proposal.\n",
        encoding="utf-8",
    )
    _reseal_directory(semantic_chain["phase_a"], "stage-manifest.json")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_stage(semantic_chain["phase_a"], expected_stage="PHASE_A")
    assert exc.value.code == "PHASE_A_SEMANTIC_ANSWER_CUE"


def test_recording_is_refused(
    tmp_path: Path,
) -> None:
    master = _build(tmp_path)
    config = _json(_run_config(tmp_path))
    config["recording_planned"] = True
    recording = tmp_path / "recording.json"
    recording.write_bytes(builder._canonical_json(config))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            recording,
            tmp_path / "recording-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RUN_CONFIG_INVALID"


def test_cross_stage_substitution_and_invalid_receipt_time_are_refused(
    tmp_path: Path,
) -> None:
    chain = _stage_chain(tmp_path)
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.lock_response(
            chain["master"],
            chain["phase_a"],
            chain["phase_a_response"],
            tmp_path / "naive-time-lock.json",
            expected_stage="PHASE_A",
            recorded_at="2026-08-31T20:00:00",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "RECEIPT_TIME_INVALID"

    phase_b_manifest = _json(chain["phase_b"] / "stage-manifest.json")
    phase_b_manifest["run_config"]["run_id"] = "run.cross-stage"
    (chain["phase_b"] / "stage-manifest.json").write_bytes(builder._canonical_json(phase_b_manifest) + b"\n")
    _reseal_directory(chain["phase_b"], "stage-manifest.json")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_stage_against_master(
            chain["master"],
            chain["phase_b"],
            expected_stage="PHASE_B",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code in {
        "RUN_CONFIG_INVALID",
        "STAGE_MANIFEST_INVALID",
        "STAGE_SOURCE_REGENERATION_MISMATCH",
    }

    with pytest.raises(builder.StudyBuildError):
        builder.release_phase_b(
            chain["master"],
            chain["phase_a"],
            chain["phase_a_response"],
            tmp_path / "missing-lock.json",
            tmp_path / "missing-lock-phase-b",
            allow_dirty_test_preview=True,
        )


def test_atomic_master_build_does_not_publish_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "never-visible"
    original = builder._write_member
    calls = 0

    def interrupted(root: Path, name: str, raw: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise builder.StudyBuildError("SYNTHETIC_INTERRUPTION")
        original(root, name, raw)

    monkeypatch.setattr(builder, "_write_member", interrupted)
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.build(output, source_identity=_test_source())
    assert exc.value.code == "SYNTHETIC_INTERRUPTION"
    assert not output.exists()
    assert not list(tmp_path.glob(".never-visible.partial-*"))


def test_outputs_and_receipts_cannot_overlap_protected_inputs(
    tmp_path: Path,
) -> None:
    master = _build(tmp_path)
    before = {path.relative_to(master).as_posix(): path.read_bytes() for path in master.rglob("*") if path.is_file()}
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            _run_config(tmp_path),
            master / "nested-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "OUTPUT_PATH_OVERLAPS_PROTECTED_INPUT"
    after = {path.relative_to(master).as_posix(): path.read_bytes() for path in master.rglob("*") if path.is_file()}
    assert after == before

    git_before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            _run_config(tmp_path),
            ROOT / "forbidden-stage-output",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "OUTPUT_PATH_OVERLAPS_PROTECTED_INPUT"
    git_after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert git_after == git_before

    phase_a = tmp_path / "phase-a"
    builder.release_phase_a(
        master,
        _run_config(tmp_path),
        phase_a,
        allow_dirty_test_preview=True,
    )
    response = tmp_path / "response.json"
    response.write_bytes((master / "researcher-capsule" / "fixtures" / "response-n.phase-a.json").read_bytes())
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.lock_response(
            master,
            phase_a,
            response,
            phase_a / "nested-lock.json",
            expected_stage="PHASE_A",
            recorded_at="2026-08-31T20:00:00+00:00",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "OUTPUT_PATH_OVERLAPS_PROTECTED_INPUT"
    builder.verify_stage(phase_a, expected_stage="PHASE_A")


@pytest.mark.parametrize(
    "html",
    [
        "<a href='https://example.invalid/x'>x</a>",
        '<a HREF="https://example.invalid/x">x</a>',
        '<form action="https://example.invalid/x"></form>',
        '<meta http-equiv="refresh" content="0;url=https://example.invalid/x">',
        '<div style="background:url(https://example.invalid/x)"></div>',
        "<script>fetch('https://example.invalid/x')</script>",
    ],
)
def test_stage_html_egress_variants_are_refused(html: str) -> None:
    with pytest.raises(builder.StudyBuildError) as exc:
        builder._validate_payload_links(
            {"index.html": ('<!doctype html><html lang="en"><body>' + html + "</body></html>").encode("utf-8")}
        )
    assert exc.value.code == "STAGE_LINK_BOUNDARY_INVALID"


def test_deep_oversized_and_hardlinked_workflow_inputs_refuse(
    tmp_path: Path,
) -> None:
    deep = ("[" * 2_000 + "0" + "]" * 2_000).encode("ascii")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder._parse_json(deep, require_canonical=False)
    assert exc.value.code in {
        "SOURCE_JSON_INVALID",
        "SOURCE_JSON_NESTING_OR_NODE_LIMIT",
    }

    master = _build(tmp_path)
    deep_config = tmp_path / "deep-config.json"
    deep_config.write_bytes(deep)
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            deep_config,
            tmp_path / "deep-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code in {
        "SOURCE_JSON_INVALID",
        "SOURCE_JSON_NESTING_OR_NODE_LIMIT",
    }

    oversized = tmp_path / "oversized-config.json"
    oversized.write_bytes(b"x" * (builder.MAX_RUN_CONFIG_BYTES + 1))
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.release_phase_a(
            master,
            oversized,
            tmp_path / "oversized-phase-a",
            allow_dirty_test_preview=True,
        )
    assert exc.value.code == "SOURCE_FILE_NOT_BOUNDED_REGULAR"

    chain = _stage_chain(tmp_path / "hardlink")
    target = chain["phase_a"] / "response.schema.json"
    external = tmp_path / "external-schema.json"
    external.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.link(external, target)
    except OSError:
        pytest.skip("hard links unavailable on this host")
    with pytest.raises(builder.StudyBuildError) as exc:
        builder.verify_stage(chain["phase_a"], expected_stage="PHASE_A")
    assert exc.value.code == "SOURCE_FILE_NOT_BOUNDED_REGULAR"
