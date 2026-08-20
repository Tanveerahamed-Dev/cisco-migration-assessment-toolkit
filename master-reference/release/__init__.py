"""Deterministic Atlas Master Reference release tooling.

The release layer consumes, but never weakens, the whole-repository compiler's
manifest.  It deliberately contains no key-generation or network code.
"""

from .pipeline import ReleaseError, build_release

__all__ = ["ReleaseError", "build_release"]
