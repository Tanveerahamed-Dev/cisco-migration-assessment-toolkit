"""Pure download-plan refusals; no filesystem/SDK/publication proof is inferred."""

from dataclasses import replace

import pytest

from portable.native_download import (
    MAX_NATIVE_DOWNLOAD_BYTES, ROOT_KINDS, DirectorySnapshot, DownloadSlot, ProtectedRoot,
    StagingInventory, admit_download,
)
from portable.native_origin import NativeRefusal


VOLUME = "11111111-2222-3333-4444-555555555555"
OTHER_VOLUME = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
STAGE = DirectorySnapshot(VOLUME, b"s" * 16, ("User", "NativeDownloads"), "NTFS", True, 123)
TARGET = DirectorySnapshot(VOLUME, b"t" * 16, ("User", "Reports"), "NTFS", True, 123)
ROOTS = tuple(ProtectedRoot(kind, VOLUME, ("Protected", kind)) for kind in sorted(ROOT_KINDS))
ATTEMPT = "a" * 32
OWNED = {"staging_inventory": StagingInventory(True, 0), "slot": DownloadSlot(ATTEMPT)}


def arguments(**changes):
    return {"staging_parent": STAGE, "final_parent": TARGET, "final_name": "synthetic-report.json",
            "expected_bytes": 123, "expected_sha256": None, "roots": ROOTS, "target_exists": False,
            "operation_supported": True, "attempt_id": ATTEMPT, "staging_inventory": StagingInventory(True, 0),
            "slot": DownloadSlot(None), **changes}


def test_admitted_plan_retains_both_physical_identities_and_requires_fresh_revalidation():
    plan = admit_download(**arguments(expected_sha256="a" * 64))
    assert plan.staging_parent == STAGE and plan.final_parent == TARGET
    plan.revalidate(staging_parent=STAGE, final_parent=TARGET, roots=ROOTS,
                    target_exists=False, operation_supported=True, **OWNED)
    with pytest.raises(NativeRefusal, match="download_parent_changed"):
        plan.revalidate(staging_parent=STAGE, final_parent=replace(TARGET, file_id=b"x" * 16),
                        roots=ROOTS, target_exists=False, operation_supported=True, **OWNED)
    with pytest.raises(NativeRefusal, match="download_collision_or_unknown"):
        plan.revalidate(staging_parent=STAGE, final_parent=TARGET, roots=ROOTS,
                        target_exists=True, operation_supported=True, **OWNED)


def test_diagnostics_do_not_expose_physical_directories_selected_names_or_volume_ids():
    plan = admit_download(**arguments())
    for item in (plan, STAGE, TARGET, *ROOTS):
        text = repr(item)
        for private in (VOLUME, "NativeDownloads", "Reports", "Protected", "synthetic-report.json"):
            assert private not in text


@pytest.mark.parametrize("kind", sorted(ROOT_KINDS))
@pytest.mark.parametrize("side", ["staging_parent", "final_parent"])
@pytest.mark.parametrize("spelling", ["same", "case-alias", "resolved-short-name-alias"])
def test_each_protected_root_refuses_both_sides_including_resolved_aliases(kind, side, spelling):
    # A short-name/reparse test against real handles belongs to the hosted OS
    # owner. Here its resolved observation is deliberately the protected path.
    components = ("Protected", kind)
    if spelling == "case-alias":
        components = tuple(part.upper() for part in components)
    candidate = replace(STAGE if side == "staging_parent" else TARGET, components=components)
    with pytest.raises(NativeRefusal, match="download_protected_destination"):
        admit_download(**arguments(**{side: candidate}))


def test_c_staging_to_e_volume_is_refused_by_pure_admission_without_any_writer():
    with pytest.raises(NativeRefusal, match="download_volume_or_media"):
        admit_download(**arguments(final_parent=replace(TARGET, volume=OTHER_VOLUME)))


@pytest.mark.parametrize("change", [
    {"target_exists": True}, {"target_exists": None}, {"operation_supported": False},
    {"final_parent": replace(TARGET, filesystem="FAT32")},
    {"staging_parent": replace(STAGE, writable=False)}, {"final_parent": replace(TARGET, writable=False)},
    {"staging_parent": replace(STAGE, volume_serial=None)},
    {"final_parent": replace(TARGET, volume_serial=456)},
    {"expected_bytes": None}, {"expected_bytes": True}, {"expected_bytes": -1},
    {"expected_bytes": MAX_NATIVE_DOWNLOAD_BYTES + 1}, {"expected_sha256": "unknown"},
    {"roots": ROOTS[:-1]}, {"roots": ()},
])
def test_unsupported_unknown_or_unbounded_admission_selects_refusal(change):
    with pytest.raises(NativeRefusal):
        admit_download(**arguments(**change))


@pytest.mark.parametrize("name", [
    "../output.json", "x/y.json", "x\\y.json", "C:output.json", "output.json:stream", "name. ",
    "CON", "con.txt", "con .txt", "COM1.json", "lpt²", "nul", "conout$", ".", "..", "bad\x00name", "?name",
])
def test_final_name_cannot_introduce_an_unsupported_windows_namespace(name):
    with pytest.raises(NativeRefusal, match="download_component"):
        admit_download(**arguments(final_name=name))


def test_component_limit_counts_utf16_units_and_refuses_unpaired_surrogates():
    name = "\U0001f642" * 127 + "x"  # 255 WCHARs, not 128.
    assert admit_download(**arguments(final_name=name)).final_name == name
    for invalid in ("\U0001f642" * 128, "bad\ud800name", "bad\udfffname"):
        with pytest.raises(NativeRefusal, match="download_component"):
            admit_download(**arguments(final_name=invalid))


def test_new_protected_root_on_revalidation_blocks_publication_even_if_file_ids_are_same():
    plan = admit_download(**arguments())
    expanded_roots = (*ROOTS, ProtectedRoot("custody", VOLUME, TARGET.components))
    with pytest.raises(NativeRefusal, match="download_protected_destination"):
        plan.revalidate(staging_parent=STAGE, final_parent=TARGET, roots=expanded_roots,
                        target_exists=False, operation_supported=True, **OWNED)


def test_staging_owner_cannot_contain_a_protected_subtree_under_another_attempt_name():
    roots = (*ROOTS, ProtectedRoot("profile", VOLUME, (*STAGE.components, "different-attempt")))
    with pytest.raises(NativeRefusal, match="download_protected_destination"):
        admit_download(**arguments(roots=roots))


@pytest.mark.parametrize("complete,count", [(False, 0), (False, 1), (True, 1), (True, 100)])
def test_incomplete_or_unknown_inventory_never_grants_native_download_admission(complete, count):
    with pytest.raises(NativeRefusal, match="download_incomplete_retained"):
        admit_download(**arguments(staging_inventory=StagingInventory(complete, count)))
    admit_download(**arguments())


def test_admission_requires_an_empty_slot_then_revalidation_requires_ownership_of_that_attempt():
    with pytest.raises(NativeRefusal, match="download_already_active"):
        admit_download(**arguments(slot=DownloadSlot("b" * 32)))
    plan = admit_download(**arguments())
    for slot in (DownloadSlot(None), DownloadSlot("b" * 32)):
        with pytest.raises(NativeRefusal, match="download_slot_changed"):
            plan.revalidate(staging_parent=STAGE, final_parent=TARGET, roots=ROOTS,
                            target_exists=False, operation_supported=True,
                            staging_inventory=StagingInventory(True, 0), slot=slot)
    with pytest.raises(NativeRefusal, match="download_incomplete_retained"):
        plan.revalidate(staging_parent=STAGE, final_parent=TARGET, roots=ROOTS,
                        target_exists=False, operation_supported=True,
                        staging_inventory=StagingInventory(True, 1), slot=DownloadSlot(ATTEMPT))
