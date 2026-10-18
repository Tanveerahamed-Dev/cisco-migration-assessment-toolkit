"""Directory identity acquisition: deterministic faults plus hosted Windows handles.

The real-handle case has no deadline/UI requirement and is shared-runner safe.
Non-Windows runs assert refusal; they do not stand in for Windows execution.
"""

import ctypes
import os
from types import SimpleNamespace

import pytest

from portable.native_origin import NativeRefusal
from portable import native_windows_identity as identity


VOLUME = "11111111-2222-3333-4444-555555555555"


class KernelFixture:
    def __init__(self):
        self.calls = []
        self.paths = {}
        self.closed = []
        self.close_failures = set()
        self.attribute_bits = 0x10
        self.case_flags = 0
        self.filesystem = "NTFS"
        self.maximum = 255
        self.redirect = False
        self.replace_id = False
        self.fail_open = None

    def GetDriveTypeW(self, root):
        assert root == "C:\\"
        return 3

    def CreateFileW(self, path, access, share, security, disposition, flags, template):
        self.calls.append((path, access, share, disposition, flags))
        assert security is template is None
        assert disposition == 3 and share == 3 and flags == 0x02200000
        if path == self.fail_open:
            return identity._INVALID_HANDLE
        handle = len(self.paths) + 1
        self.paths[handle] = path
        return handle

    def info(self, handle, kind, value):
        if kind == 9:
            value.attributes = self.attribute_bits
            value.tag = 0
        elif kind == 23:
            value.flags = self.case_flags
        elif kind == 18:
            value.serial = 1
            value.identifier[:] = bytes([handle + 10 * self.replace_id]) * 16
        else:
            raise AssertionError("unexpected information class")
        return value

    def GetFinalPathNameByHandleW(self, handle, buffer, length, flags):
        assert length == 32768 and flags == 1
        suffix = self.paths[handle][3:]
        if self.redirect and suffix:
            suffix = "elsewhere\\" + suffix
        buffer.value = "\\\\?\\Volume{" + VOLUME + "}\\" + suffix
        return len(buffer.value)

    def GetVolumeInformationByHandleW(self, handle, name, size, serial, maximum, flags, fs, length):
        assert name is None and size == 0 and length == 32
        ctypes.cast(maximum, ctypes.POINTER(ctypes.c_uint32))[0] = self.maximum
        fs.value = self.filesystem
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return handle not in self.close_failures


def fixture_kernel(monkeypatch):
    kernel = KernelFixture()
    monkeypatch.setattr(identity, "_Kernel", lambda: kernel)
    return kernel


@pytest.mark.parametrize("path", [
    "", "relative", "C:relative", "\\server\\share", "\\\\?\\C:\\safe",
    "C:\\safe\\..\\output", "C:\\safe\\", "C:\\safe:stream", "C:\\NUL", "C:\\bad. ",
])
def test_namespace_refusal_precedes_any_os_open(monkeypatch, path):
    kernel = fixture_kernel(monkeypatch)
    with pytest.raises(NativeRefusal):
        identity.WindowsDirectory(path)
    assert kernel.calls == []


def test_path_limit_counts_wchars_before_opening_even_the_first_ancestor(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    path = "C:\\" + ("a" * 255 + "\\") * 127 + "\U0001f642" * 127 + "x"
    assert len(path) < 32760
    with pytest.raises(NativeRefusal, match="windows_directory_namespace"):
        identity.WindowsDirectory(path)
    assert kernel.calls == []


def test_every_ancestor_is_held_without_delete_sharing_and_revalidated(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    with identity.WindowsDirectory("C:\\synthetic\\reports", writable=True) as directory:
        snapshot = directory.revalidate()
        assert snapshot.volume == VOLUME
        assert snapshot.components == ("synthetic", "reports")
        assert snapshot.file_id == b"\x03" * 16 and snapshot.writable
        assert snapshot.volume_serial == 1
        assert [row[0] for row in kernel.calls] == ["C:\\", "C:\\synthetic", "C:\\synthetic\\reports"]
        assert all(not row[2] & 4 for row in kernel.calls)
        assert kernel.calls[-1][1] & 6 == 6
        assert all(not row[1] & 6 for row in kernel.calls[:-1])
        assert "synthetic" not in repr(directory)
    assert kernel.closed == [3, 2, 1]
    with pytest.raises(NativeRefusal, match="windows_directory_closed"):
        directory.revalidate()


@pytest.mark.parametrize("fault,code", [
    ("reparse", "windows_directory_reparse_or_type"),
    ("case", "windows_directory_case_sensitive"),
    ("media", "windows_directory_filesystem"),
    ("component-limit", "windows_directory_filesystem"),
    ("chain", "windows_directory_chain_changed"),
])
def test_uncertain_identity_refuses_and_closes_every_acquired_handle(monkeypatch, fault, code):
    kernel = fixture_kernel(monkeypatch)
    if fault == "reparse":
        kernel.attribute_bits |= 0x400
    elif fault == "case":
        kernel.case_flags = 1
    elif fault == "media":
        kernel.filesystem = "FAT32"
    elif fault == "component-limit":
        kernel.maximum = 254
    else:
        kernel.redirect = True
    with pytest.raises(NativeRefusal, match=code):
        identity.WindowsDirectory("C:\\synthetic\\reports")
    assert kernel.closed == list(reversed(kernel.paths))


def test_failed_descendant_open_closes_ancestors(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    kernel.fail_open = "C:\\synthetic\\reports"
    with pytest.raises(NativeRefusal, match="windows_directory_open"):
        identity.WindowsDirectory(kernel.fail_open)
    assert kernel.closed == [2, 1]


def test_live_identity_change_blocks_readmission(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    with identity.WindowsDirectory("C:\\synthetic") as directory:
        kernel.replace_id = True
        with pytest.raises(NativeRefusal, match="windows_directory_changed"):
            directory.revalidate()
    assert kernel.closed == [2, 1]


def test_failed_close_is_unconfirmed_and_retry_cannot_readmit_identity(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    directory = identity.WindowsDirectory("C:\\synthetic")
    kernel.close_failures.add(2)
    with pytest.raises(NativeRefusal, match="windows_directory_cleanup_unconfirmed"):
        directory.close()
    assert kernel.closed == [2, 1] and directory._handles == [2]
    with pytest.raises(NativeRefusal, match="windows_directory_closed"):
        directory.revalidate()
    kernel.close_failures.clear()
    directory.close()
    assert kernel.closed == [2, 1, 2] and not directory._handles


def test_close_fault_does_not_mask_the_original_interrupt(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    with pytest.raises(KeyboardInterrupt) as caught:
        with identity.WindowsDirectory("C:\\synthetic"):
            kernel.close_failures.add(2)
            raise KeyboardInterrupt
    assert caught.value.native_cleanup_unconfirmed is True
    assert kernel.closed == [2, 1]


def test_cleanup_metadata_cannot_replace_a_nonassignable_base_exception(monkeypatch):
    class RefusesMetadata(BaseException):
        def __setattr__(self, name, value):
            raise RuntimeError("metadata refused")

    kernel = fixture_kernel(monkeypatch)
    original = RefusesMetadata()
    with pytest.raises(RefusesMetadata) as caught:
        with identity.WindowsDirectory("C:\\synthetic"):
            kernel.close_failures.add(2)
            raise original
    assert caught.value is original
    assert kernel.closed == [2, 1]


def test_known_folder_parent_is_handle_admitted_without_environment_substitution(monkeypatch):
    kernel = fixture_kernel(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", "C:\\untrusted")
    monkeypatch.setenv("TEMP", "C:\\also-untrusted")
    monkeypatch.setattr(identity, "_known_local_app_data_path", lambda: "C:\\synthetic\\known-folder")
    with identity.open_local_app_data() as directory:
        snapshot = directory.revalidate()
        assert snapshot.components == ("synthetic", "known-folder")
        assert snapshot.writable
        assert all("untrusted" not in row[0] for row in kernel.calls)
    assert kernel.closed == [3, 2, 1]


@pytest.mark.parametrize("status,path,code", [
    (0, "C:\\synthetic\\known-folder", None),
    (-2147467259, "C:\\synthetic\\known-folder", "windows_known_folder_unavailable"),
    (0, "\\\\server\\share", "windows_directory_namespace"),
    (0, None, "windows_known_folder_unavailable"),
])
def test_known_folder_api_uses_current_user_no_create_and_disposes_even_failed_results(
    monkeypatch, status, path, code,
):
    buffer = ctypes.create_unicode_buffer(path) if path is not None else None
    freed = []
    calls = []

    def query(guid, flags, token, output):
        assert ctypes.string_at(guid, 16) == identity._LOCAL_APP_DATA
        assert flags == 0x4000 and not flags & 0x8000 and token is None
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = (
            ctypes.addressof(buffer) if buffer is not None else None
        )
        calls.append("query")
        return status

    def free(pointer):
        freed.append(pointer.value)

    def library(name, *, winmode):
        assert winmode == 0x800
        calls.append(name)
        if name == "shell32.dll":
            return SimpleNamespace(SHGetKnownFolderPath=query)
        assert name == "ole32.dll"
        return SimpleNamespace(CoTaskMemFree=free)

    monkeypatch.setattr(identity, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(identity.ctypes, "WinDLL", library, raising=False)
    if code is None:
        assert identity._known_local_app_data_path() == path
    else:
        with pytest.raises(NativeRefusal, match=code):
            identity._known_local_app_data_path()
    assert calls == ["shell32.dll", "ole32.dll", "query"]
    assert freed == ([ctypes.addressof(buffer)] if buffer is not None else [])


def test_real_windows_directory_identity_and_delete_exclusion(tmp_path):
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        with pytest.raises(NativeRefusal, match="windows_x64_identity_required"):
            identity.WindowsDirectory("C:\\synthetic")
        return
    # This branch must execute on hosted Windows; a missing required API or
    # unsupported hosted filesystem is a failure, never a skipped proof.
    parent = tmp_path / "synthetic-parent"
    parent.mkdir()
    destination = tmp_path / "synthetic-renamed"
    with identity.WindowsDirectory(str(parent), writable=True) as directory:
        snapshot = directory.revalidate()
        assert snapshot.filesystem == "NTFS" and snapshot.writable
        assert len(snapshot.file_id) == 16
        with pytest.raises(OSError):
            parent.rename(destination)
        assert parent.is_dir() and not destination.exists()
        assert directory.revalidate() == snapshot
    parent.rename(destination)
    assert destination.is_dir() and not parent.exists()


def test_real_known_folder_is_existing_and_handle_admitted_on_hosted_windows():
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        with pytest.raises(NativeRefusal, match="windows_x64_identity_required"):
            identity.open_local_app_data()
        return
    with identity.open_local_app_data() as directory:
        snapshot = directory.revalidate()
        assert snapshot.filesystem == "NTFS" and snapshot.writable
        assert snapshot.components
        assert len(snapshot.file_id) == 16
