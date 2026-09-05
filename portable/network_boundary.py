"""Default-deny outbound network boundary for the frozen Atlas Release-1 profile.

Loopback remains available for AssessHub. Live SSH/controller collection requires the
explicit launcher flag, which sets ``ATLAS_PORTABLE_ALLOW_LIVE_NETWORK=1`` before any
collector can connect. This is a process boundary, not a device authorization grant.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any


ALLOW_ENV = "ATLAS_PORTABLE_ALLOW_LIVE_NETWORK"
_INSTALLED_MARKER = "_atlas_portable_network_boundary"
_ORIGINALS_MARKER = "_atlas_portable_network_originals"


def live_network_allowed() -> bool:
    return os.environ.get(ALLOW_ENV, "").strip() == "1"


def _loopback_host(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return False
    value = str(host).strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _address_host(address: Any) -> object:
    return address[0] if isinstance(address, tuple) and address else address


def install() -> None:
    """Install the idempotent socket guard. Runtime hooks call this before app imports."""
    if getattr(socket, _INSTALLED_MARKER, False):
        return
    # Ambient process state is never an authority grant. Only the explicit command-line flag,
    # parsed after this hook runs, may opt one process into live network access.
    os.environ.pop(ALLOW_ENV, None)
    originals = {
        "connect": socket.socket.connect,
        "connect_ex": socket.socket.connect_ex,
        "getaddrinfo": socket.getaddrinfo,
        "gethostbyname": socket.gethostbyname,
        "gethostbyname_ex": socket.gethostbyname_ex,
        "gethostbyaddr": socket.gethostbyaddr,
        "getnameinfo": socket.getnameinfo,
        "sendto": socket.socket.sendto,
    }
    if hasattr(socket.socket, "sendmsg"):
        originals["sendmsg"] = socket.socket.sendmsg

    def require_allowed(sock: socket.socket, address: Any) -> None:
        if live_network_allowed() or sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return
        if not _loopback_host(_address_host(address)):
            raise PermissionError(
                "Atlas portable blocked outbound network access; restart with "
                "--allow-live-network only for an explicitly authorized read-only collection"
            )

    def guarded_connect(sock: socket.socket, address: Any):
        require_allowed(sock, address)
        return originals["connect"](sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any):
        require_allowed(sock, address)
        return originals["connect_ex"](sock, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not live_network_allowed() and not (
            _loopback_host(host) or host is None
        ):
            raise PermissionError("Atlas portable blocked non-loopback name resolution")
        result = originals["getaddrinfo"](host, *args, **kwargs)
        return result

    def guarded_gethostbyname(host):
        if not live_network_allowed() and not _loopback_host(host):
            raise PermissionError("Atlas portable blocked non-loopback name resolution")
        result = originals["gethostbyname"](host)
        if not live_network_allowed() and not _loopback_host(result):
            raise PermissionError("Atlas portable rejected a non-loopback localhost answer")
        return result

    def guarded_gethostbyname_ex(host):
        if not live_network_allowed() and not _loopback_host(host):
            raise PermissionError("Atlas portable blocked non-loopback name resolution")
        result = originals["gethostbyname_ex"](host)
        if not live_network_allowed() and any(not _loopback_host(item) for item in result[2]):
            raise PermissionError("Atlas portable rejected a non-loopback localhost answer")
        return result

    def guarded_gethostbyaddr(host):
        if not live_network_allowed() and not _loopback_host(host):
            raise PermissionError("Atlas portable blocked non-loopback reverse name resolution")
        return originals["gethostbyaddr"](host)

    def guarded_getnameinfo(address, flags):
        if not live_network_allowed() and not _loopback_host(_address_host(address)):
            raise PermissionError("Atlas portable blocked non-loopback reverse name resolution")
        return originals["getnameinfo"](address, flags)

    def guarded_sendto(sock: socket.socket, data, *args):
        if not args:
            raise TypeError("sendto requires a destination")
        require_allowed(sock, args[-1])
        return originals["sendto"](sock, data, *args)

    def guarded_sendmsg(sock: socket.socket, buffers, ancdata=(), flags=0, address=None):
        if address is not None:
            require_allowed(sock, address)
            return originals["sendmsg"](sock, buffers, ancdata, flags, address)
        return originals["sendmsg"](sock, buffers, ancdata, flags)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = guarded_gethostbyname
    socket.gethostbyname_ex = guarded_gethostbyname_ex
    socket.gethostbyaddr = guarded_gethostbyaddr
    socket.getnameinfo = guarded_getnameinfo
    socket.socket.sendto = guarded_sendto
    if "sendmsg" in originals:
        socket.socket.sendmsg = guarded_sendmsg
    if os.name == "nt":
        # The default Windows asyncio loop bypasses ``socket.socket.connect`` and invokes
        # ConnectEx/WSAConnect through IocpProactor. Guard that public connection seam too.
        from asyncio import windows_events

        originals["iocp_connect"] = windows_events.IocpProactor.connect

        def guarded_iocp_connect(proactor, connection, address):
            require_allowed(connection, address)
            return originals["iocp_connect"](proactor, connection, address)

        windows_events.IocpProactor.connect = guarded_iocp_connect
    setattr(socket, _ORIGINALS_MARKER, originals)
    setattr(socket, _INSTALLED_MARKER, True)


def installed() -> bool:
    return bool(getattr(socket, _INSTALLED_MARKER, False))


def offline_probe() -> bool:
    """Exercise each guarded standard-library egress seam without sending a packet."""
    if live_network_allowed() or not installed():
        return False
    expected_functions = {
        socket.getaddrinfo: "guarded_getaddrinfo",
        socket.getnameinfo: "guarded_getnameinfo",
        socket.socket.connect: "guarded_connect",
        socket.socket.connect_ex: "guarded_connect_ex",
        socket.socket.sendto: "guarded_sendto",
    }
    if any(
        getattr(function, "__module__", None) != __name__
        or getattr(function, "__name__", None) != expected_name
        for function, expected_name in expected_functions.items()
    ):
        return False

    class ProbeSocket:
        family = socket.AF_INET

    probe_socket = ProbeSocket()
    checks = []
    try:
        socket.getaddrinfo("atlas-offline-probe.example.invalid", 443)
    except PermissionError:
        checks.append(True)
    try:
        socket.getnameinfo(("192.0.2.1", 443), 0)
    except PermissionError:
        checks.append(True)
    try:
        socket.socket.connect(probe_socket, ("192.0.2.1", 9))
    except PermissionError:
        checks.append(True)
    try:
        socket.socket.connect(probe_socket, ("localhost", 9))
    except PermissionError:
        checks.append(True)
    try:
        socket.socket.connect_ex(probe_socket, ("192.0.2.1", 9))
    except PermissionError:
        checks.append(True)
    try:
        socket.socket.sendto(probe_socket, b"atlas", ("192.0.2.1", 9))
    except PermissionError:
        checks.append(True)
    if os.name == "nt":
        from asyncio import windows_events

        if (
            getattr(windows_events.IocpProactor.connect, "__module__", None) != __name__
            or getattr(windows_events.IocpProactor.connect, "__name__", None)
            != "guarded_iocp_connect"
        ):
            return False
        try:
            # Both objects are deliberately inert; the guard rejects before dereferencing them.
            windows_events.IocpProactor.connect(
                object(), probe_socket, ("192.0.2.1", 9)
            )
        except PermissionError:
            checks.append(True)
    expected = 7 if os.name == "nt" else 6
    return len(checks) == expected and bool(socket.getaddrinfo("127.0.0.1", 0))
