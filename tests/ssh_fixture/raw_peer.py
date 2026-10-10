"""Stdlib-only SSH wire helpers for the W59 interop tests -- no cryptography, cleartext phase only.

* :func:`probe_kexinit` -- the NON-VACUITY reader (design section 8): connect, read the server's cleartext
  version line and KEXINIT, and return its algorithm lists, so "this fixture is SHA-1-only" is proven by the
  bytes on the wire before a test relies on it, never assumed from the fixture's configuration.
* :class:`RawResponder` -- a scripted RFC 4253 peer for the disconnect race (T17): it either disconnects
  before sending any KEXINIT, or sends a KEXINIT with no algorithm the client shares and disconnects at once.
  It counts connections, which is how a test proves "exactly one attempt" / "the same-profile retry".

Everything here precedes key exchange (RFC 4253 section 6: before NEWKEYS the binary packet protocol is
unencrypted, MAC-less and uncompressed), so a ~100-line responder suffices.
"""
from __future__ import annotations

import os
import socket
import struct
import threading
from typing import Dict, List, Optional, Sequence

MSG_DISCONNECT = 1
MSG_KEXINIT = 20
_BLOCK = 8                     # the unencrypted packet block size paramiko enforces before NEWKEYS


def name_list(names: Sequence[str]) -> bytes:
    raw = ",".join(names).encode("ascii")
    return struct.pack(">I", len(raw)) + raw


def ssh_string(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def kexinit_payload(kex: Sequence[str], host_key: Sequence[str], cipher: Sequence[str],
                    mac: Sequence[str]) -> bytes:
    """RFC 4253 section 7.1 SSH_MSG_KEXINIT: cookie, ten name-lists, first_kex_packet_follows, reserved."""
    body = bytes([MSG_KEXINIT]) + os.urandom(16)
    for names in (kex, host_key, cipher, cipher, mac, mac, ["none"], ["none"], [], []):
        body += name_list(names)
    return body + b"\x00" + struct.pack(">I", 0)


def disconnect_payload(reason: int = 11, text: str = "fixture disconnect") -> bytes:
    """RFC 4253 section 11.1 SSH_MSG_DISCONNECT (11 = SSH_DISCONNECT_BY_APPLICATION)."""
    return bytes([MSG_DISCONNECT]) + struct.pack(">I", reason) + ssh_string(text.encode("ascii")) + ssh_string(b"")


def packet(payload: bytes) -> bytes:
    """Frame one cleartext binary packet: total length a multiple of 8, at least 4 bytes of padding."""
    padding = _BLOCK - ((5 + len(payload)) % _BLOCK)
    if padding < 4:
        padding += _BLOCK
    return struct.pack(">IB", 1 + len(payload) + padding, padding) + payload + os.urandom(padding)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise EOFError("peer closed")
        data += chunk
    return data


def read_version_line(sock: socket.socket) -> str:
    line = b""
    while not line.endswith(b"\n"):
        ch = sock.recv(1)
        if not ch:
            raise EOFError("peer closed before its version line")
        line += ch
        if len(line) > 255:
            raise ValueError("version line too long")
    return line.decode("ascii", "replace").rstrip("\r\n")


def read_payload(sock: socket.socket) -> bytes:
    length, padding = struct.unpack(">IB", _recv_exact(sock, 5))
    body = _recv_exact(sock, length - 1)
    return body[: len(body) - padding]


def parse_kexinit(payload: bytes) -> Dict[str, List[str]]:
    if not payload or payload[0] != MSG_KEXINIT:
        raise ValueError("not a KEXINIT")
    pos = 1 + 16
    keys = ("kex", "host_key", "cipher_c2s", "cipher_s2c", "mac_c2s", "mac_s2c",
            "compression_c2s", "compression_s2c", "lang_c2s", "lang_s2c")
    out: Dict[str, List[str]] = {}
    for key in keys:
        (n,) = struct.unpack(">I", payload[pos:pos + 4])
        pos += 4
        raw = payload[pos:pos + n].decode("ascii")
        pos += n
        out[key] = raw.split(",") if raw else []
    return out


def probe_kexinit(host: str, port: int, timeout: float = 15.0) -> Dict[str, List[str]]:
    """The server's own KEXINIT lists, read off the wire (non-vacuity of every fixture profile)."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(b"SSH-2.0-W59KexinitProbe\r\n")
        while True:
            line = read_version_line(sock)
            if line.startswith("SSH-"):
                break
        return parse_kexinit(read_payload(sock))


class RawResponder:
    """A scripted cleartext SSH peer on 127.0.0.1.

    ``mode="disconnect_before_kexinit"``: version line, then DISCONNECT, then close -- no server lists exist.
    ``mode="kexinit_then_disconnect"``: version line, a KEXINIT offering ``kex``/``host_key``/... , then
    DISCONNECT at once -- the stream is ordered, so the client parses the KEXINIT first.
    ``connections`` counts accepted TCP connections; ``received_after_kexinit`` records whether the client sent
    anything beyond its own KEXINIT (it must not, for a refused negotiation)."""

    def __init__(self, mode: str, *, kex: Sequence[str] = (), host_key: Sequence[str] = (),
                 cipher: Sequence[str] = ("aes128-ctr",), mac: Sequence[str] = ("hmac-sha2-256",)) -> None:
        if mode not in ("disconnect_before_kexinit", "kexinit_then_disconnect"):
            raise ValueError(mode)
        self.mode = mode
        self.kex, self.host_key, self.cipher, self.mac = list(kex), list(host_key), list(cipher), list(mac)
        self.connections = 0
        self.client_payload_types: List[List[int]] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="w59-raw-responder", daemon=True)

    def __enter__(self) -> "RawResponder":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._sock.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            seen: List[int] = []
            self.client_payload_types.append(seen)
            try:
                self._script(conn, seen)
            except (OSError, EOFError, ValueError, struct.error):
                pass
            finally:
                conn.close()

    def _script(self, conn: socket.socket, seen: List[int]) -> None:
        conn.settimeout(5)
        conn.sendall(b"SSH-2.0-W59RawResponder\r\n")
        if self.mode == "disconnect_before_kexinit":
            conn.sendall(packet(disconnect_payload()))
            return
        conn.sendall(packet(kexinit_payload(self.kex, self.host_key, self.cipher, self.mac))
                     + packet(disconnect_payload(3, "key exchange failed")))
        # Drain what the client sends until it closes: its version line, then its packets. A refused client
        # sends exactly one packet type, its own KEXINIT (20); anything after it would be a protocol step past
        # the refusal.
        try:
            read_version_line(conn)
            while True:
                payload = read_payload(conn)
                seen.append(payload[0] if payload else -1)
        except (OSError, EOFError, ValueError, struct.error):
            return


def kexinit_names(lists: Optional[Dict[str, List[str]]], key: str) -> List[str]:
    return [n for n in (lists or {}).get(key, []) if not n.startswith(("ext-info-", "kex-strict-"))]
