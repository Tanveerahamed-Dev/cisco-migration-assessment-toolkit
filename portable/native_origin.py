"""Native presentation URI policy. No socket, renderer, engine or credential access."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit


class NativeRefusal(ValueError):
    """A presentation capability was not established; use browser/manual continuation."""


def _parts(uri: str):
    if type(uri) is not str or not uri or len(uri) > 16384:
        raise NativeRefusal("uri_shape")
    if any(ord(character) <= 32 or ord(character) == 127 for character in uri) or "\\" in uri:
        raise NativeRefusal("uri_spelling")
    try:
        parsed = urlsplit(uri)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or parsed.netloc.endswith(":")
                or any(character in parsed.netloc for character in "%@")):
            raise NativeRefusal("uri_authority")
        address = ipaddress.ip_address(parsed.hostname or "")
        if not address.is_loopback:
            raise NativeRefusal("uri_loopback")
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        if not 1 <= port <= 65535:
            raise NativeRefusal("uri_port")
    except ValueError as error:
        raise NativeRefusal("uri_authority") from error
    return parsed, str(address), port


@dataclass(frozen=True)
class NativeOrigin:
    """Immutable tuple supplied by the actual server binding, never by page content."""

    scheme: str
    address: str
    port: int

    @classmethod
    def from_bound_url(cls, uri: str) -> NativeOrigin:
        parsed, address, port = _parts(uri)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise NativeRefusal("bound_origin_shape")
        return cls(parsed.scheme, address, port)

    def __post_init__(self):
        if (type(self.scheme) is not str or type(self.address) is not str or type(self.port) is not int
                or self.scheme not in {"http", "https"} or not 1 <= self.port <= 65535):
            raise NativeRefusal("bound_origin_shape")
        try:
            address = ipaddress.ip_address(self.address)
        except ValueError as error:
            raise NativeRefusal("bound_origin_shape") from error
        if not address.is_loopback or str(address) != self.address:
            raise NativeRefusal("bound_origin_shape")

    @property
    def url(self) -> str:
        host = f"[{self.address}]" if ":" in self.address else self.address
        return f"{self.scheme}://{host}:{self.port}/"

    def require_request(self, uri: str) -> None:
        parsed, address, port = _parts(uri)
        if (parsed.scheme, address, port) != (self.scheme, self.address, self.port):
            raise NativeRefusal("foreign_origin")

    def require_download(self, uri: str, *, document: str) -> None:
        self.require_request(document)
        if type(uri) is str and uri.startswith("blob:"):
            uri = uri[5:]
        self.require_request(uri)


# Additive to the application's existing headers. This is never authentication.
NATIVE_HEADER = (b"x-atlas-native", b"1")
NATIVE_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:; frame-src 'self'; "
    "worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
)


class NativeResponsePolicy:
    """Append a second CSP without altering auth, request headers or existing CSP."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        marked = scope["type"] == "http" and NATIVE_HEADER in scope.get("headers", ())

        async def restricted_send(message):
            if marked and message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", ()),
                                                  (b"content-security-policy", NATIVE_CSP.encode("ascii"))]}
            await send(message)

        await self.app(scope, receive, restricted_send)
