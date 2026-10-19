"""Windows directory identity reader for native presentation (not yet wired).

Only OPEN_EXISTING handles are obtained. This module creates/deletes/publishes
no file, profile, directory or process and grants no native release admission.
It must run only in the authorized hosted/runtime path, never as a local probe.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import re

from portable.native_download import DirectorySnapshot, _component, _utf16_units
from portable.native_origin import NativeRefusal


_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_BOOL = ctypes.c_int32
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_PHYSICAL = re.compile(r"\\\\\?\\Volume\{([0-9a-fA-F-]{36})\}\\(.*)")


class _AttributeTag(ctypes.Structure):
    _fields_ = [("attributes", _DWORD), ("tag", _DWORD)]


class _FileId(ctypes.Structure):
    _fields_ = [("serial", ctypes.c_uint64), ("identifier", ctypes.c_ubyte * 16)]


class _CaseSensitive(ctypes.Structure):
    _fields_ = [("flags", _DWORD)]


class _Guid(ctypes.Structure):
    _fields_ = [("data1", _DWORD), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16),
                ("data4", ctypes.c_ubyte * 8)]


_LOCAL_APP_DATA = bytes.fromhex("8527b3f1ba6fcf4f9d557b8e7f157091")


def _mark_cleanup_unconfirmed(exception):
    try:
        exception.native_cleanup_unconfirmed = True
    except BaseException:
        # Diagnostic metadata is best-effort. It must not replace the original
        # failure/interrupt, including for a custom non-assignable exception.
        pass


def _known_local_app_data_path():
    """Query the current-user Known Folder without CREATE or environment lookup.

    The returned path is only an input to held-handle admission, not authority
    to create a profile or download directory. Do not print or serialize it.
    """
    if os.name != "nt" or ctypes.sizeof(_HANDLE) != 8:
        raise NativeRefusal("windows_x64_identity_required")
    try:
        shell = ctypes.WinDLL("shell32.dll", winmode=0x800)
        ole = ctypes.WinDLL("ole32.dll", winmode=0x800)
        query = shell.SHGetKnownFolderPath
        query.restype = ctypes.c_int32
        query.argtypes = [ctypes.POINTER(_Guid), _DWORD, _HANDLE, ctypes.POINTER(ctypes.c_void_p)]
        free = ole.CoTaskMemFree
        free.restype = None
        free.argtypes = [ctypes.c_void_p]
    except (AttributeError, OSError) as error:
        raise NativeRefusal("windows_known_folder_capability") from error
    value = ctypes.c_void_p()
    try:
        # DONT_VERIFY avoids Shell probing a redirected network location before
        # our local-namespace guard. No CREATE flag; OPEN_EXISTING below owns
        # the actual directory existence and identity checks.
        result = query(ctypes.byref(_Guid.from_buffer_copy(_LOCAL_APP_DATA)), 0x4000, None, ctypes.byref(value))
        if result != 0 or not value.value:
            raise NativeRefusal("windows_known_folder_unavailable")
        path = ctypes.wstring_at(value)
        local_directory_parts(path)
        return path
    finally:
        # The API contract requires freeing its result on both success and
        # failure; this is allocation disposal, not profile/file deletion.
        if value.value:
            free(value)


def open_local_app_data() -> WindowsDirectory:
    """Hold the existing OS-selected parent; no profile/staging is created."""
    return WindowsDirectory(_known_local_app_data_path(), writable=True)


def local_directory_parts(value):
    """Reject indirection spellings before any Windows path lookup or resolution."""
    if (type(value) is not str or not value or len(value) > 32760 or _utf16_units(value) > 32760
            or value.startswith("\\")):
        raise NativeRefusal("windows_directory_namespace")
    spelling = value.replace("/", "\\")
    drive, tail = ntpath.splitdrive(spelling)
    if re.fullmatch(r"[A-Za-z]:", drive) is None or not tail.startswith("\\"):
        raise NativeRefusal("windows_directory_namespace")
    components = () if tail == "\\" else tuple(tail[1:].split("\\"))
    if len(components) > 256:
        raise NativeRefusal("windows_directory_namespace")
    for component in components:
        _component(component)
    return drive.upper() + "\\", components


class _Kernel:
    def __init__(self):
        if os.name != "nt" or ctypes.sizeof(_HANDLE) != 8:
            raise NativeRefusal("windows_x64_identity_required")
        try:
            # LOAD_LIBRARY_SEARCH_SYSTEM32; never use inherited DLL/PATH search.
            self.dll = ctypes.WinDLL("kernel32.dll", winmode=0x800, use_last_error=True)
            self._bind("CreateFileW", _HANDLE,
                       [ctypes.c_wchar_p, _DWORD, _DWORD, ctypes.c_void_p, _DWORD, _DWORD, _HANDLE])
            self._bind("CloseHandle", _BOOL, [_HANDLE])
            self._bind("GetCurrentProcess", _HANDLE, [])
            self._bind("IsWow64Process2", _BOOL,
                       [_HANDLE, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16)])
            self._bind("GetDriveTypeW", _DWORD, [ctypes.c_wchar_p])
            self._bind("GetFileInformationByHandleEx", _BOOL, [_HANDLE, ctypes.c_int32, ctypes.c_void_p, _DWORD])
            self._bind("GetFinalPathNameByHandleW", _DWORD, [_HANDLE, ctypes.c_wchar_p, _DWORD, _DWORD])
            self._bind("GetVolumeInformationByHandleW", _BOOL,
                       [_HANDLE, ctypes.c_wchar_p, _DWORD, ctypes.POINTER(_DWORD), ctypes.POINTER(_DWORD),
                        ctypes.POINTER(_DWORD), ctypes.c_wchar_p, _DWORD])
        except (AttributeError, OSError) as error:
            raise NativeRefusal("windows_identity_capability") from error
        process_machine, native_machine = ctypes.c_uint16(), ctypes.c_uint16()
        if (not self.IsWow64Process2(self.GetCurrentProcess(), ctypes.byref(process_machine),
                                    ctypes.byref(native_machine))
                or process_machine.value != 0 or native_machine.value != 0x8664):
            raise NativeRefusal("windows_x64_identity_required")

    def _bind(self, name, result, arguments):
        function = getattr(self.dll, name)
        function.restype = result
        function.argtypes = arguments
        setattr(self, name, function)

    def info(self, handle, kind, value):
        if not self.GetFileInformationByHandleEx(handle, kind, ctypes.byref(value), ctypes.sizeof(value)):
            raise NativeRefusal("windows_directory_information")
        return value


class WindowsDirectory:
    """Hold every existing ancestor against rename/delete and reject reparse paths.

    Input must be an ordinary absolute local-drive spelling. Physical GUID/long
    names come from the held handles; UNC/device, case-sensitive and non-NTFS
    paths are unsupported. This does not establish protected-root completeness,
    a private DACL/owner, runtime trust, profile ownership or publication support.
    """

    def __init__(self, path: str, *, writable: bool = False):
        if type(writable) is not bool:
            raise NativeRefusal("windows_directory_access")
        root, components = local_directory_parts(path)
        self._api = _Kernel()
        self._handles = []
        self._initial = []
        self._writable = writable
        self._retiring = False
        if self._api.GetDriveTypeW(root) not in {2, 3}:  # removable/fixed local media only
            raise NativeRefusal("windows_directory_drive")
        current = root
        paths = [root]
        for component in components:
            current = ntpath.join(current, component)
            paths.append(current)
        try:
            for index, spelling in enumerate(paths):
                final = index == len(paths) - 1
                access = 0x20000 | 0x80 | 0x1  # READ_CONTROL, READ_ATTRIBUTES, LIST_DIRECTORY
                if final and writable:
                    access |= 0x2 | 0x4  # ADD_FILE/SUBDIRECTORY access check; still OPEN_EXISTING
                handle = self._api.CreateFileW(
                    spelling, access, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None,
                )  # no FILE_SHARE_DELETE; BACKUP_SEMANTICS + OPEN_REPARSE_POINT
                if handle in {None, _INVALID_HANDLE}:
                    raise NativeRefusal("windows_directory_open")
                self._handles.append(handle)
                self._initial.append(self._snapshot(handle, final=final))
            self.revalidate()
        except BaseException as original:
            try:
                self.close()
            except NativeRefusal:
                # Preserve interrupts and the original refusal. This is a fixed
                # diagnostic only; never attach paths, handles or OS messages.
                _mark_cleanup_unconfirmed(original)
            raise

    def __repr__(self):
        return "WindowsDirectory(<private>)"

    def _snapshot(self, handle, *, final):
        attributes = self._api.info(handle, 9, _AttributeTag())
        if not attributes.attributes & 0x10 or attributes.attributes & 0x400 or attributes.tag:
            raise NativeRefusal("windows_directory_reparse_or_type")
        if self._api.info(handle, 23, _CaseSensitive()).flags:
            raise NativeRefusal("windows_directory_case_sensitive")
        identity = self._api.info(handle, 18, _FileId())
        name = ctypes.create_unicode_buffer(32768)
        count = self._api.GetFinalPathNameByHandleW(handle, name, len(name), 0x1)
        if not 0 < count < len(name):
            raise NativeRefusal("windows_directory_physical_name")
        physical = _PHYSICAL.fullmatch(name.value)
        if physical is None:
            raise NativeRefusal("windows_directory_physical_namespace")
        volume, relative = physical.groups()
        components = tuple(relative.split("\\")) if relative else ()
        serial, maximum, flags = _DWORD(), _DWORD(), _DWORD()
        filesystem = ctypes.create_unicode_buffer(32)
        if not self._api.GetVolumeInformationByHandleW(
            handle, None, 0, ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags),
            filesystem, len(filesystem),
        ) or filesystem.value != "NTFS" or maximum.value != 255:
            raise NativeRefusal("windows_directory_filesystem")
        return DirectorySnapshot(volume.lower(), bytes(identity.identifier), components, filesystem.value,
                                 bool(final and self._writable and not flags.value & 0x80000),
                                 identity.serial)

    def revalidate(self) -> DirectorySnapshot:
        if self._retiring or not self._handles or len(self._handles) != len(self._initial):
            raise NativeRefusal("windows_directory_closed")
        current = [self._snapshot(handle, final=index == len(self._handles) - 1)
                   for index, handle in enumerate(self._handles)]
        for parent, child in zip(current, current[1:]):
            if (child.volume != parent.volume or child.volume_serial != parent.volume_serial
                    or tuple(part.casefold() for part in child.components[:-1])
                    != tuple(part.casefold() for part in parent.components)
                    or len(child.components) != len(parent.components) + 1):
                raise NativeRefusal("windows_directory_chain_changed")
        if current != self._initial:
            raise NativeRefusal("windows_directory_changed")
        return current[-1]

    def close(self):
        self._retiring = True
        failed = []
        for handle in reversed(self._handles):
            try:
                closed = self._api.CloseHandle(handle)
            except OSError:
                closed = False
            if not closed:
                failed.append(handle)
        # A failed close is retained for a retry and never reported as proved
        # cleanup. The future GUI owner must select unconfirmed/manual fallback.
        self._handles = list(reversed(failed))
        if failed:
            raise NativeRefusal("windows_directory_cleanup_unconfirmed")

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        try:
            self.close()
        except NativeRefusal:
            if exception is None:
                raise
            _mark_cleanup_unconfirmed(exception)
