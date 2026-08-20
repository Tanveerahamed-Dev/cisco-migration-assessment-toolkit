from __future__ import annotations

import base64
import hashlib
import json
import logging
import sys
import traceback
from dataclasses import replace
from io import BytesIO, StringIO
from pathlib import Path

import pytest


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from cli import atlas_release  # noqa: E402
import release.pdf_review as pdf_review_module  # noqa: E402
from release.model import canonical_json, sha256_bytes  # noqa: E402
from release.pdf_report import inspect_pdf_report_bytes  # noqa: E402
from release.pdf_review import (  # noqa: E402
    PDF_REVIEW_POLICY_SCHEMA_VERSION,
    PDF_REVIEW_RESULT_SCHEMA_VERSION,
    PDF_REVIEW_SCHEMA_VERSION,
    PDF_REVIEW_SIGNATURE_SCHEMA_VERSION,
    PdfReviewError,
    PdfReviewEvidenceBytes,
    PdfReviewSubject,
    pdf_review_evidence_sha256,
    pdf_review_signing_material,
    read_pdf_review_evidence_files,
    verify_pdf_review as verify_pdf_review_public,
)
from release.schema_validation import SCHEMAS  # noqa: E402


verify_pdf_review_subject = pdf_review_module._verify_pdf_review_subject


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _subject() -> PdfReviewSubject:
    return PdfReviewSubject(
        manifest_path=Path("frozen-family/release-manifest.json"),
        source_commit="1" * 40,
        head_tree_oid="2" * 40,
        index_digest="3" * 64,
        source_tree_digest="4" * 64,
        release_manifest_sha256="5" * 64,
        family_attestation_sha256="6" * 64,
        pdf_gate_sha256="7" * 64,
        pdf_path="master-reference.pdf",
        pdf_sha256="8" * 64,
        pdf_bytes=230467,
        pdf_page_count=3,
        pdf_input_digest="9" * 64,
        release_status="unsigned_preview_incomplete",
        publication_status="not_authorized",
        family_independent_verification_verdict="BLOCK",
        pdf_gate_status="generated_visual_review_pending",
        pdf_gate_independent_verification_verdict="BLOCK",
    )


def _binding(subject: PdfReviewSubject) -> dict[str, object]:
    return {
        "source_commit": subject.source_commit,
        "head_tree_oid": subject.head_tree_oid,
        "index_digest": subject.index_digest,
        "source_tree_digest": subject.source_tree_digest,
        "release_manifest_sha256": subject.release_manifest_sha256,
        "family_attestation_sha256": subject.family_attestation_sha256,
        "pdf_gate_sha256": subject.pdf_gate_sha256,
        "pdf_path": subject.pdf_path,
        "pdf_sha256": subject.pdf_sha256,
        "pdf_bytes": subject.pdf_bytes,
        "pdf_page_count": subject.pdf_page_count,
        "pdf_input_digest": subject.pdf_input_digest,
    }


def _rechain(payload: dict[str, object]) -> dict[str, object]:
    rows = payload["page_reviews"]
    assert isinstance(rows, list)
    verdicts = [row["review_verdict"] for row in rows]
    page_numbers = [row["page_number"] for row in rows]
    page_count = payload["pdf_page_count"]
    exact = page_numbers == list(range(1, page_count + 1))
    passed = verdicts.count("pass")
    blocked = verdicts.count("block")
    reviewed = passed + blocked
    checks = payload["checks"]
    assert isinstance(checks, dict)
    checks["all_pages_rendered"] = "pass" if exact else "block"
    checks["all_pages_reviewed"] = "pass" if exact and reviewed == page_count else "block"
    payload["render_profile_digest"] = sha256_bytes(canonical_json(payload["render_profile"]))
    payload["page_reviews_digest"] = sha256_bytes(canonical_json(rows))
    payload["rendered_page_count"] = len(rows)
    payload["reviewed_page_count"] = reviewed
    payload["passed_page_count"] = passed
    payload["blocked_page_count"] = blocked
    payload["checks_digest"] = sha256_bytes(canonical_json(checks))
    complete_pass = exact and passed == page_count and all(value == "pass" for value in checks.values())
    payload["verdict"] = "PASS" if complete_pass else "BLOCK"
    payload["review_evidence_sha256"] = pdf_review_evidence_sha256(payload)
    return payload


def _payload(
    subject: PdfReviewSubject,
    verdicts: tuple[str, ...] = ("pass", "pass", "pass"),
) -> dict[str, object]:
    render_profile = {
        "renderer": "pdftoppm",
        "renderer_version": "25.06.0",
        "dpi": 144,
        "output_format": "png",
        "page_scope": "all_pages",
        "color_mode": "default",
    }
    rows = [
        {
            "page_number": page_number,
            "render_sha256": _digest(f"page:{page_number}"),
            "render_bytes": 1000 + page_number,
            "review_verdict": verdict,
        }
        for page_number, verdict in enumerate(verdicts, start=1)
    ]
    checks = {
        "all_pages_rendered": "pass",
        "all_pages_reviewed": "pass",
        "no_clipped_or_overflowing_content": "pass",
        "no_overlapping_content": "pass",
        "text_and_glyphs_legible": "pass",
        "tables_and_figures_legible": "pass",
        "headers_footers_and_page_numbers_consistent": "pass",
        "section_transitions_and_visible_content_reconciled": "pass",
    }
    value: dict[str, object] = {
        "schema_version": "pdf-review/1",
        "review_kind": "independent_rendered_pdf_visual_review",
        "purpose": "pdf_visual_review",
        **_binding(subject),
        "render_profile": render_profile,
        "render_profile_digest": "0" * 64,
        "page_reviews": rows,
        "page_reviews_digest": "0" * 64,
        "rendered_page_count": 0,
        "reviewed_page_count": 0,
        "passed_page_count": 0,
        "blocked_page_count": 0,
        "checks": checks,
        "checks_digest": "0" * 64,
        "verdict": "BLOCK",
        "review_evidence_sha256": "0" * 64,
        "accessibility_disposition": "abstain_not_established",
        "binary_privacy_disposition": "abstain_not_established",
    }
    return _rechain(value)


def _policy(fingerprint: str, *, revision: int = 1) -> dict[str, object]:
    return {
        "schema_version": "pdf-reviewer-key-policy/1",
        "policy_kind": "external_ed25519_pdf_review_key_allowlist",
        "policy_revision": revision,
        "keys": [
            {
                "public_key_fingerprint": fingerprint,
                "reviewer_kind": "independent_agent",
                "independent_from_proposer": True,
                "independent_from_pdf_producer": True,
                "independent_from_release_builder": True,
                "authorizations": [
                    {
                        "purpose": "pdf_visual_review",
                        "target_schema_version": "pdf-review/1",
                        "reviewer_role": "pdf_visual_verifier",
                    }
                ],
            }
        ],
    }


def _evidence(payload: dict[str, object]) -> PdfReviewEvidenceBytes:
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    asymmetric = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = asymmetric.Ed25519PrivateKey.generate()
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = f"sha256:{sha256_bytes(public_raw)}"
    payload_raw = canonical_json(payload)
    policy_raw = canonical_json(_policy(fingerprint))
    material = pdf_review_signing_material(MASTER_REFERENCE.parent, payload_raw, policy_raw)
    signature = {
        "schema_version": "pdf-review-signature/1",
        "signature_kind": "detached_ed25519_exact_bytes",
        "purpose": "pdf_visual_review",
        "algorithm": "Ed25519",
        "target_schema_version": "pdf-review/1",
        "target_sha256": sha256_bytes(payload_raw),
        "trust_policy_sha256": sha256_bytes(policy_raw),
        "signer_key_fingerprint": fingerprint,
        "signature_base64": base64.b64encode(key.sign(material)).decode("ascii"),
    }
    return PdfReviewEvidenceBytes(
        payload=payload_raw,
        signature=canonical_json(signature),
        trust_policy=policy_raw,
        trusted_public_key=public_pem,
    )


def _formatted(failure: pytest.ExceptionInfo[BaseException]) -> str:
    return "".join(traceback.format_exception(failure.type, failure.value, failure.tb))


def test_pdf_review_contract_versions_are_additive_and_registered() -> None:
    schema_root = MASTER_REFERENCE / "release" / "schemas"
    expectations = {
        "pdf-review.schema.json": PDF_REVIEW_SCHEMA_VERSION,
        "pdf-review-signature.schema.json": PDF_REVIEW_SIGNATURE_SCHEMA_VERSION,
        "pdf-reviewer-key-policy.schema.json": PDF_REVIEW_POLICY_SCHEMA_VERSION,
        "pdf-review-result.schema.json": PDF_REVIEW_RESULT_SCHEMA_VERSION,
    }
    for name, version in expectations.items():
        schema = json.loads((schema_root / name).read_text(encoding="utf-8"))
        assert schema["properties"]["schema_version"]["const"] == version
        if name == "pdf-review.schema.json":
            assert "uniqueItems" not in schema["properties"]["page_reviews"]
            assert schema["$defs"]["renderProfile"]["properties"]["renderer_version"][
                "pattern"
            ] == r"\S"
    for name in ("pdf-review", "pdf-review-signature", "pdf-reviewer-key-policy", "pdf-review-result"):
        assert name in SCHEMAS


def test_pdf_signing_material_is_domain_policy_and_payload_bound() -> None:
    payload_raw = canonical_json(_payload(_subject()))
    fingerprint = "sha256:" + "a" * 64
    policy_one = canonical_json(_policy(fingerprint, revision=1))
    policy_two = canonical_json(_policy(fingerprint, revision=2))
    material_one = pdf_review_signing_material(MASTER_REFERENCE.parent, payload_raw, policy_one)
    material_two = pdf_review_signing_material(MASTER_REFERENCE.parent, payload_raw, policy_two)
    assert material_one.startswith(b"ATLAS-PDF-REVIEW\x00v1\x00pdf_visual_review\x00pdf-review/1\x00")
    assert material_one != material_two
    changed_payload = canonical_json(_payload(replace(_subject(), pdf_bytes=230468)))
    assert material_one != pdf_review_signing_material(MASTER_REFERENCE.parent, changed_payload, policy_one)


def test_all_page_visual_pass_is_authenticated_but_never_promotes() -> None:
    subject = _subject()
    result = verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(_payload(subject)))
    assert result.status == "verified_visual_pass_not_promoted"
    assert result.signature_verified is True
    assert result.family_integrity_verified is True
    assert result.pdf_subject_verified is True
    assert result.visual_review_complete is True
    assert result.visual_review_passed is True
    assert result.rendered_page_count == result.reviewed_page_count == result.passed_page_count == 3
    assert result.blocked_page_count == 0
    assert result.current_gate_promoted is False
    assert result.global_gate_closed is False
    assert result.release_family_mutated is False
    assert result.owner_manifest_signature_verified is False
    assert result.accessibility_review_established is False
    assert result.binary_privacy_review_established is False
    assert result.publication_authority_granted is False


def test_public_verifier_loads_live_family_and_rejects_fabricated_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    evidence = _evidence(_payload(subject))
    loaded = iter((subject, subject))
    monkeypatch.setattr(pdf_review_module, "load_pdf_review_subject", lambda *_args: next(loaded))
    result = verify_pdf_review_public(MASTER_REFERENCE.parent, subject.manifest_path, evidence)
    assert result.family_integrity_verified is True
    assert result.pdf_subject_verified is True

    with pytest.raises(PdfReviewError) as fabricated:
        verify_pdf_review_public(MASTER_REFERENCE.parent, subject, evidence)  # type: ignore[arg-type]
    assert fabricated.value.code == "pdf_review_input_invalid"

    changed = iter((subject, replace(subject, pdf_sha256="a" * 64)))
    monkeypatch.setattr(pdf_review_module, "load_pdf_review_subject", lambda *_args: next(changed))
    with pytest.raises(PdfReviewError) as family_changed:
        verify_pdf_review_public(MASTER_REFERENCE.parent, subject.manifest_path, evidence)
    assert family_changed.value.code == "pdf_review_family_changed"


def test_large_page_ledger_is_linear_and_exact_range_owned() -> None:
    subject = replace(_subject(), pdf_page_count=1_000)
    payload = _payload(subject, ("pass",) * subject.pdf_page_count)
    result = verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(payload))
    assert result.rendered_page_count == 1_000
    assert result.passed_page_count == 1_000


def test_renderer_version_rejects_whitespace_only_identity() -> None:
    payload = _payload(_subject())
    profile = payload["render_profile"]
    assert isinstance(profile, dict)
    profile["renderer_version"] = "   "
    _rechain(payload)
    with pytest.raises(PdfReviewError) as failure:
        pdf_review_signing_material(
            MASTER_REFERENCE.parent,
            canonical_json(payload),
            canonical_json(_policy("sha256:" + "a" * 64)),
        )
    assert failure.value.code == "pdf_review_payload_malformed"


def test_pypdf_parser_diagnostic_is_suppressed_and_fails_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata(
        {
            "/Title": "Atlas Master Reference - Whole-Repository Accounting",
            "/Author": "Atlas repository",
            "/Subject": f"source {'1' * 40} tree {'2' * 64}",
        }
    )
    buffer = BytesIO()
    writer.write(buffer)
    hostile = buffer.getvalue().replace(b"startxref\n", b"startxref ", 1)
    assert hostile != buffer.getvalue()
    logger = logging.getLogger("pypdf._reader")
    external_output = StringIO()
    external_handler = logging.StreamHandler(external_output)

    class RejectAll(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return False

    rejecting_filter = RejectAll()
    previous_disabled = logger.disabled
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.addHandler(external_handler)
    logger.addFilter(rejecting_filter)
    logger.disabled = True
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False
    try:
        with pytest.raises(ValueError):
            inspect_pdf_report_bytes(
                hostile,
                path=Path("warning.pdf"),
                expected_commit="1" * 40,
                expected_tree_digest="2" * 64,
            )
        assert logger.disabled is True
        assert logger.level == logging.CRITICAL
        assert logger.propagate is False
        assert rejecting_filter in logger.filters
    finally:
        logger.removeHandler(external_handler)
        logger.removeFilter(rejecting_filter)
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert external_output.getvalue() == ""

    previous_global_disable = logger.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with pytest.raises(ValueError):
            inspect_pdf_report_bytes(
                hostile,
                path=Path("warning.pdf"),
                expected_commit="1" * 40,
                expected_tree_digest="2" * 64,
            )
        assert logger.manager.disable == logging.CRITICAL
    finally:
        logging.disable(previous_global_disable)
    globally_disabled = capsys.readouterr()
    assert globally_disabled.out == ""
    assert globally_disabled.err == ""


@pytest.mark.parametrize("mode", ("page_block", "not_reviewed", "check_block"))
def test_authenticated_visual_block_is_reported_without_promotion(mode: str) -> None:
    subject = _subject()
    if mode == "page_block":
        payload = _payload(subject, ("pass", "block", "pass"))
    elif mode == "not_reviewed":
        payload = _payload(subject, ("pass", "not_reviewed", "pass"))
    else:
        payload = _payload(subject)
        checks = payload["checks"]
        assert isinstance(checks, dict)
        checks["no_overlapping_content"] = "block"
        _rechain(payload)
    result = verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(payload))
    assert result.status == "verified_visual_blocked_not_promoted"
    assert result.visual_review_passed is False
    assert result.visual_review_complete is (mode != "not_reviewed")
    assert result.current_gate_promoted is False
    assert result.publication_authority_granted is False


@pytest.mark.parametrize("mode", ("duplicate", "missing", "reordered", "out_of_range"))
def test_page_ledger_requires_exact_ordered_page_denominator_even_when_rechained(mode: str) -> None:
    subject = _subject()
    payload = _payload(subject)
    rows = payload["page_reviews"]
    assert isinstance(rows, list)
    if mode == "duplicate":
        rows[1]["page_number"] = 1
    elif mode == "missing":
        rows.pop()
    elif mode == "reordered":
        rows.reverse()
    else:
        rows[-1]["page_number"] = 4
    _rechain(payload)
    with pytest.raises(PdfReviewError) as failure:
        verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(payload))
    assert failure.value.code == "pdf_review_subject_mismatch"


@pytest.mark.parametrize(
    "field,replacement",
    (
        ("source_commit", "a" * 40),
        ("head_tree_oid", "b" * 40),
        ("index_digest", "c" * 64),
        ("source_tree_digest", "d" * 64),
        ("release_manifest_sha256", "e" * 64),
        ("family_attestation_sha256", "f" * 64),
        ("pdf_gate_sha256", "a" * 64),
        ("pdf_sha256", "b" * 64),
        ("pdf_bytes", 230468),
        ("pdf_page_count", 4),
        ("pdf_input_digest", "c" * 64),
    ),
)
def test_every_family_binding_is_exact_even_after_attacker_rechains(
    field: str,
    replacement: object,
) -> None:
    subject = _subject()
    payload = _payload(subject)
    payload[field] = replacement
    _rechain(payload)
    with pytest.raises(PdfReviewError) as failure:
        verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(payload))
    assert failure.value.code == "pdf_review_binding_mismatch"


def test_counts_subdigests_summary_digest_and_verdict_cannot_contradict_signed_rows() -> None:
    subject = _subject()
    mutations = []
    count_tamper = _payload(subject)
    count_tamper["passed_page_count"] = 2
    count_tamper["review_evidence_sha256"] = pdf_review_evidence_sha256(count_tamper)
    mutations.append((count_tamper, "pdf_review_verdict_inconsistent"))
    row_digest_tamper = _payload(subject)
    row_digest_tamper["page_reviews_digest"] = "a" * 64
    row_digest_tamper["review_evidence_sha256"] = pdf_review_evidence_sha256(row_digest_tamper)
    mutations.append((row_digest_tamper, "pdf_review_subject_mismatch"))
    summary_tamper = _payload(subject)
    summary_tamper["review_evidence_sha256"] = "b" * 64
    mutations.append((summary_tamper, "pdf_review_subject_mismatch"))
    verdict_tamper = _payload(subject)
    verdict_tamper["verdict"] = "BLOCK"
    verdict_tamper["review_evidence_sha256"] = pdf_review_evidence_sha256(verdict_tamper)
    mutations.append((verdict_tamper, "pdf_review_verdict_inconsistent"))
    for payload, expected in mutations:
        with pytest.raises(PdfReviewError) as failure:
            verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, _evidence(payload))
        assert failure.value.code == expected


def test_signature_bit_flip_and_untrusted_key_fail_closed() -> None:
    subject = _subject()
    evidence = _evidence(_payload(subject))
    signature = json.loads(evidence.signature.decode("utf-8"))
    decoded = bytearray(base64.b64decode(signature["signature_base64"], validate=True))
    decoded[0] ^= 1
    signature["signature_base64"] = base64.b64encode(bytes(decoded)).decode("ascii")
    hostile = replace(evidence, signature=canonical_json(signature))
    with pytest.raises(PdfReviewError) as invalid:
        verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, hostile)
    assert invalid.value.code == "pdf_review_signature_invalid"

    other = _evidence(_payload(subject))
    with pytest.raises(PdfReviewError) as untrusted:
        verify_pdf_review_subject(
            MASTER_REFERENCE.parent,
            subject,
            replace(evidence, trusted_public_key=other.trusted_public_key),
        )
    assert untrusted.value.code == "pdf_review_key_not_trusted"


def test_partial_or_hostile_inputs_never_echo_values() -> None:
    subject = _subject()
    evidence = _evidence(_payload(subject))
    with pytest.raises(PdfReviewError) as partial:
        verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, replace(evidence, signature=None))
    assert partial.value.code == "pdf_review_input_incomplete"

    canary = "PRIVATE-PDF-REVIEW-CANARY-MUST-NOT-ECHO"
    original = pdf_review_module._verify_detached_signature
    class PdfReviewSubclass(PdfReviewError):
        pass

    try:
        for hostile_exception in (
            RuntimeError(canary),
            PdfReviewError(canary),
            PdfReviewSubclass("pdf_review_binding_mismatch"),
        ):
            pdf_review_module._verify_detached_signature = (
                lambda *_args, failure=hostile_exception: (_ for _ in ()).throw(failure)
            )
            with pytest.raises(PdfReviewError) as hostile:
                verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, evidence)
            assert hostile.value.code == "pdf_review_unexpected"
            assert canary not in _formatted(hostile)
    finally:
        pdf_review_module._verify_detached_signature = original


def test_noncanonical_duplicate_and_float_json_fail_before_signature_work() -> None:
    subject = _subject()
    valid = _evidence(_payload(subject))
    duplicate = valid.payload.replace(
        b'{"accessibility_disposition":"abstain_not_established",',
        b'{"accessibility_disposition":"abstain_not_established",'
        b'"accessibility_disposition":"abstain_not_established",',
        1,
    )
    floated = valid.payload.replace(b'"blocked_page_count":0', b'"blocked_page_count":0.0', 1)
    assert duplicate != valid.payload
    assert floated != valid.payload
    for payload in (valid.payload.rstrip(b"\n"), duplicate, floated):
        with pytest.raises(PdfReviewError) as failure:
            verify_pdf_review_subject(
                MASTER_REFERENCE.parent,
                subject,
                replace(valid, payload=payload),
            )
        assert failure.value.code == "pdf_review_payload_malformed"


def test_policy_must_assert_reviewer_independence_from_both_producers() -> None:
    subject = _subject()
    valid = _evidence(_payload(subject))
    for field in ("independent_from_pdf_producer", "independent_from_release_builder"):
        policy = json.loads(valid.trust_policy.decode("utf-8"))
        policy["keys"][0][field] = False
        with pytest.raises(PdfReviewError) as failure:
            verify_pdf_review_subject(
                MASTER_REFERENCE.parent,
                subject,
                replace(valid, trust_policy=canonical_json(policy)),
            )
        assert failure.value.code == "pdf_review_trust_policy_malformed"


def test_external_evidence_reader_is_bounded_and_rejects_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = {
        name: tmp_path / f"{name}.bin"
        for name in ("payload", "signature", "policy", "key")
    }
    values = {name: f"{name}\n".encode() for name in paths}
    for name, path in paths.items():
        path.write_bytes(values[name])
    evidence = read_pdf_review_evidence_files(
        paths["payload"], paths["signature"], paths["policy"], paths["key"]
    )
    assert evidence.payload == values["payload"]
    assert evidence.signature == values["signature"]

    with pytest.raises(PdfReviewError) as colocated:
        read_pdf_review_evidence_files(
            paths["payload"],
            paths["signature"],
            paths["policy"],
            paths["key"],
            forbidden_root=tmp_path,
        )
    assert colocated.value.code == "pdf_review_payload_unavailable"

    original_fstat = pdf_review_module.os.fstat
    mutated = False

    def grow_during_read(descriptor: int):
        nonlocal mutated
        metadata = original_fstat(descriptor)
        if not mutated:
            mutated = True
            with paths["payload"].open("ab") as stream:
                stream.write(b"changed")
        return metadata

    monkeypatch.setattr(pdf_review_module.os, "fstat", grow_during_read)
    with pytest.raises(PdfReviewError) as changed:
        read_pdf_review_evidence_files(
            paths["payload"], paths["signature"], paths["policy"], paths["key"]
        )
    assert changed.value.code == "pdf_review_payload_unavailable"
    monkeypatch.setattr(pdf_review_module.os, "fstat", original_fstat)
    paths["payload"].write_bytes(values["payload"])

    monkeypatch.setattr(pdf_review_module, "_MAX_PAYLOAD_BYTES", 4)
    with pytest.raises(PdfReviewError) as oversized:
        read_pdf_review_evidence_files(
            paths["payload"], paths["signature"], paths["policy"], paths["key"]
        )
    assert oversized.value.code == "pdf_review_payload_unavailable"

    link = tmp_path / "payload-link.bin"
    try:
        link.symlink_to(paths["payload"])
    except OSError:
        return
    with pytest.raises(PdfReviewError) as symlinked:
        read_pdf_review_evidence_files(link, paths["signature"], paths["policy"], paths["key"])
    assert symlinked.value.code == "pdf_review_payload_unavailable"


def test_same_handle_reader_rejects_lstat_to_open_replacement_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    victim = tmp_path / "release-manifest.json"
    alternate = tmp_path / "alternate.json"
    original = tmp_path / "original.json"
    victim.write_bytes(b"original")
    alternate.write_bytes(b"alternate")

    original_open = pdf_review_module.os.open
    swapped = False

    def swap_before_open(path: object, flags: int, *args: object) -> int:
        nonlocal swapped
        if not swapped and Path(path) == victim:
            swapped = True
            victim.replace(original)
            alternate.replace(victim)
        return original_open(path, flags, *args)

    monkeypatch.setattr(pdf_review_module.os, "open", swap_before_open)
    with pytest.raises(PdfReviewError) as failure:
        pdf_review_module._read_external_regular(
            victim,
            maximum_bytes=32,
            failure_code="pdf_review_family_invalid",
        )
    assert swapped is True
    assert failure.value.code == "pdf_review_family_invalid"


def test_cli_emits_only_canonical_nonpromoting_receipt_and_fixed_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    subject = _subject()
    evidence = _evidence(_payload(subject))
    result = verify_pdf_review_subject(MASTER_REFERENCE.parent, subject, evidence)
    monkeypatch.setattr(
        atlas_release,
        "read_pdf_review_evidence_files",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(atlas_release, "verify_pdf_review", lambda *_args: result)
    arguments = [
        "verify-pdf-review",
        "--repo-root",
        str(MASTER_REFERENCE.parent),
        "--manifest",
        str(tmp_path / "release-manifest.json"),
        "--payload",
        str(tmp_path / "review.json"),
        "--signature",
        str(tmp_path / "review.sig.json"),
        "--trust-policy",
        str(tmp_path / "policy.json"),
        "--public-key",
        str(tmp_path / "reviewer.pub"),
    ]
    assert atlas_release.main(arguments) == 0
    success = capsys.readouterr()
    assert success.out.encode("utf-8") == canonical_json(result.as_dict())
    assert success.err == ""

    changed_evidence = replace(evidence, trusted_public_key=evidence.trusted_public_key + b"\n")
    reads = iter((evidence, changed_evidence))
    monkeypatch.setattr(
        atlas_release,
        "read_pdf_review_evidence_files",
        lambda *_args, **_kwargs: next(reads),
    )
    assert atlas_release.main(arguments) == 2
    changed = capsys.readouterr()
    assert changed.out == ""
    assert changed.err.encode("utf-8") == canonical_json(
        {"error": "pdf_review_input_changed", "ok": False}
    )

    monkeypatch.setattr(
        atlas_release,
        "read_pdf_review_evidence_files",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        atlas_release,
        "verify_pdf_review",
        lambda *_args: (_ for _ in ()).throw(PdfReviewError("pdf_review_family_changed")),
    )
    assert atlas_release.main(arguments) == 2
    family_changed = capsys.readouterr()
    assert family_changed.out == ""
    assert family_changed.err.encode("utf-8") == canonical_json(
        {"error": "pdf_review_family_changed", "ok": False}
    )

    missing_root_arguments = list(arguments)
    missing_root_arguments[2] = str(tmp_path / "missing-repository")
    assert atlas_release.main(missing_root_arguments) == 2
    invalid_root = capsys.readouterr()
    assert invalid_root.out == ""
    assert invalid_root.err.encode("utf-8") == canonical_json(
        {"error": "pdf_review_input_invalid", "ok": False}
    )

    canary = "PRIVATE-CLI-PDF-CANARY"
    monkeypatch.setattr(
        atlas_release,
        "verify_pdf_review",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(canary)),
    )
    assert atlas_release.main(arguments) == 2
    unexpected = capsys.readouterr()
    assert unexpected.out == ""
    assert unexpected.err.encode("utf-8") == canonical_json(
        {"error": "pdf_review_unexpected", "ok": False}
    )
    assert canary not in unexpected.err
