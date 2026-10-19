"""Download admission model for the Windows handle owner; this module writes nothing.

Snapshots must come from held physical directory handles, not a SaveFileDialog
string or renderer claim. The OS writer is deliberately not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from portable.native_origin import NativeRefusal


MAX_NATIVE_DOWNLOAD_BYTES = 128 * 1024 * 1024
ROOT_KINDS = frozenset({"installation", "active", "previous", "incoming", "helper", "transaction",
                        "backup", "profile", "custody"})
_VOLUME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$",
                       *(f"com{digit}" for digit in "123456789¹²³"),
                       *(f"lpt{digit}" for digit in "123456789¹²³")})


def _utf16_units(value):
    try:
        return len(value.encode("utf-16-le", errors="strict")) // 2
    except UnicodeError as error:
        raise NativeRefusal("download_component") from error


def _component(value):
    if (type(value) is not str or not value or value in {".", ".."} or len(value) > 255
            or _utf16_units(value) > 255
            or value[-1] in " ." or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(char in value for char in '\\/:*?"<>|')
            or value.split(".", 1)[0].rstrip(" ").casefold() in _RESERVED):
        raise NativeRefusal("download_component")


@dataclass(frozen=True, repr=False)
class DirectorySnapshot:
    """Trusted OS observation, not independently verified by this pure model.

    The future owner holds every ancestor without delete sharing, resolves a
    volume-GUID physical path, rejects reparse/case-sensitive/unsupported roots,
    and keeps the handles alive. Components contain resolved long names; case
    folding is valid only under that case-insensitive NTFS admission contract.
    """

    volume: str
    file_id: bytes
    components: tuple[str, ...]
    filesystem: str
    writable: bool
    volume_serial: int | None = None

    def __repr__(self):
        return "DirectorySnapshot(<private>)"

    def __post_init__(self):
        if (type(self.volume) is not str or _VOLUME.fullmatch(self.volume) is None
                or type(self.file_id) is not bytes or len(self.file_id) != 16
                or type(self.components) is not tuple or len(self.components) > 256
                or type(self.filesystem) is not str or type(self.writable) is not bool
                or self.volume_serial is not None and (
                    type(self.volume_serial) is not int or not 0 <= self.volume_serial < 2**64)):
            raise NativeRefusal("download_directory_identity")
        for component in self.components:
            _component(component)


@dataclass(frozen=True, repr=False)
class ProtectedRoot:
    kind: str
    volume: str
    components: tuple[str, ...]

    def __repr__(self):
        return "ProtectedRoot(<private>)"

    def __post_init__(self):
        if (type(self.kind) is not str or self.kind not in ROOT_KINDS
                or type(self.volume) is not str or _VOLUME.fullmatch(self.volume) is None
                or type(self.components) is not tuple or len(self.components) > 256):
            raise NativeRefusal("download_protected_root")
        for component in self.components:
            _component(component)


def _root_inventory(roots):
    if (type(roots) is not tuple or not roots or len(roots) > 128
            or any(type(root) is not ProtectedRoot for root in roots)
            or {root.kind for root in roots} != ROOT_KINDS):
        raise NativeRefusal("download_root_inventory")


def _outside(directory, leaf, roots):
    components = tuple(component.casefold() for component in (*directory.components, leaf))
    for root in roots:
        protected = tuple(component.casefold() for component in root.components)
        if directory.volume == root.volume and components[:len(protected)] == protected:
            raise NativeRefusal("download_protected_destination")


def _staging_disjoint(directory, roots):
    components = tuple(component.casefold() for component in directory.components)
    for root in roots:
        protected = tuple(component.casefold() for component in root.components)
        if directory.volume == root.volume and (
            components[:len(protected)] == protected or protected[:len(components)] == components
        ):
            raise NativeRefusal("download_protected_destination")


@dataclass(frozen=True, repr=False)
class DownloadPlan:
    staging_parent: DirectorySnapshot
    final_parent: DirectorySnapshot
    final_name: str
    expected_bytes: int
    expected_sha256: str | None
    attempt_id: str

    def __repr__(self):
        return "DownloadPlan(<private>)"

    def revalidate(self, *, staging_parent, final_parent, roots, target_exists, operation_supported,
                   staging_inventory, slot):
        _inventory(staging_inventory)
        if type(slot) is not DownloadSlot or slot.active_attempt != self.attempt_id:
            raise NativeRefusal("download_slot_changed")
        if staging_parent != self.staging_parent or final_parent != self.final_parent:
            raise NativeRefusal("download_parent_changed")
        refreshed = _path_plan(staging_parent=staging_parent, final_parent=final_parent,
                               final_name=self.final_name, expected_bytes=self.expected_bytes,
                               expected_sha256=self.expected_sha256, roots=roots,
                               target_exists=target_exists, operation_supported=operation_supported,
                               attempt_id=self.attempt_id)
        if refreshed != self:
            raise NativeRefusal("download_plan_changed")


def _path_plan(*, staging_parent, final_parent, final_name, expected_bytes,
               expected_sha256, roots, target_exists, operation_supported, attempt_id) -> DownloadPlan:
    """No creation, network acceptance, SDK deferral completion or writing occurs.

    A caller must revalidate this plan before writes and again before same-volume
    handle-relative atomic no-replace publication. SDK Completed is not final
    publication. Pure-model tests cannot certify those Windows observations.
    """
    if type(staging_parent) is not DirectorySnapshot or type(final_parent) is not DirectorySnapshot:
        raise NativeRefusal("download_directory_identity")
    _component(final_name)
    _root_inventory(roots)
    if (type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_NATIVE_DOWNLOAD_BYTES
            or expected_sha256 is not None and (type(expected_sha256) is not str
                                               or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None)):
        raise NativeRefusal("download_length_digest")
    if type(target_exists) is not bool or target_exists:
        raise NativeRefusal("download_collision_or_unknown")
    if type(operation_supported) is not bool or not operation_supported:
        raise NativeRefusal("download_publication_unsupported")
    if (staging_parent.volume != final_parent.volume
            or staging_parent.volume_serial is None or final_parent.volume_serial is None
            or staging_parent.volume_serial != final_parent.volume_serial or staging_parent.filesystem != "NTFS"
            or final_parent.filesystem != "NTFS" or not staging_parent.writable or not final_parent.writable):
        raise NativeRefusal("download_volume_or_media")
    # The whole planned staging directory and final parent must be outside every
    # protected root, not merely the selected final filename.
    _staging_disjoint(staging_parent, roots)
    _outside(final_parent, final_name, roots)
    return DownloadPlan(staging_parent, final_parent, final_name, expected_bytes, expected_sha256, attempt_id)


def _inventory(inventory):
    if type(inventory) is not StagingInventory:
        raise NativeRefusal("download_staging_inventory")
    inventory.require_empty()


def admit_download(*, staging_parent, final_parent, final_name, expected_bytes,
                   expected_sha256, roots, target_exists, operation_supported,
                   staging_inventory, slot, attempt_id) -> DownloadPlan:
    """Require inventory and the empty GUI download slot before constructing a plan.

    The real owner must atomically claim the slot for attempt_id, then revalidate
    the plan before creating anything. The slot remains owned through publication
    or explicit incomplete settlement; a plan by itself is never write authority.
    """
    _inventory(staging_inventory)
    if type(slot) is not DownloadSlot or slot.active_attempt is not None:
        raise NativeRefusal("download_already_active")
    if type(attempt_id) is not str or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
        raise NativeRefusal("download_attempt")
    return _path_plan(staging_parent=staging_parent, final_parent=final_parent, final_name=final_name,
                      expected_bytes=expected_bytes, expected_sha256=expected_sha256, roots=roots,
                      target_exists=target_exists, operation_supported=operation_supported,
                      attempt_id=attempt_id)


@dataclass(frozen=True)
class StagingInventory:
    """Observation of the private staging owner, independent of profile quotas.

    Unknown inventory disables native downloads; it never authorizes deletion.
    Persistence/identity admission of the actual inventory remains with the OS
    owner. No constructor parameter is accepted from the page or public IPC.
    """

    complete: bool
    incomplete_attempts: int

    def __post_init__(self):
        if (type(self.complete) is not bool or type(self.incomplete_attempts) is not int
                or self.incomplete_attempts < 0):
            raise NativeRefusal("download_staging_inventory")

    def require_empty(self):
        if not self.complete or self.incomplete_attempts != 0:
            raise NativeRefusal("download_incomplete_retained")


@dataclass(frozen=True)
class DownloadSlot:
    """One GUI-owned slot observation, never a backend lease or idle catalogue."""

    active_attempt: str | None

    def __post_init__(self):
        if self.active_attempt is not None and (
            type(self.active_attempt) is not str or re.fullmatch(r"[0-9a-f]{32}", self.active_attempt) is None
        ):
            raise NativeRefusal("download_slot_identity")
