"""Owner-held native dependency release block; no licence is selected or authored."""

from portable.native_origin import NativeRefusal


PROXY_TOOLS_010_LICENSE_CONFLICT = "PROXY_TOOLS_010_LICENSE_CONFLICT"
PROXY_SDIST_SHA256 = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
PROXY_LICENSE_REFERENCES = (
    ("proxy_tools-0.1.0/PKG-INFO", 8, "MIT declaration"),
    ("proxy_tools-0.1.0/setup.py", 14, "MIT declaration"),
    ("proxy_tools-0.1.0/proxy_tools/__init__.py", 8, "BSD declaration; references absent LICENSE"),
)


def require_native_dependency_promotion() -> None:
    """Named BLOCK, not resolvable by supplied hashes, JSON status or environment.

    The owner must supply an attributable applicable-text/copyright resolution.
    No dependency build/execution, promotion or publication is authorized here.
    An evidence-only route that omits this dependency is not an adopted route.
    """
    raise NativeRefusal(PROXY_TOOLS_010_LICENSE_CONFLICT)
