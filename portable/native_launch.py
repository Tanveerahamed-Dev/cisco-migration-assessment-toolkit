"""Packaging presentation preparation; the held release keeps the existing browser.

This callback is not a server-ready notification. A future native owner must
establish the actual bound socket/instance before launching its GUI group.
"""

from __future__ import annotations

from portable.native_origin import NativeRefusal
from portable.native_window import require_native_release_admission


def prepare_presentation(app, url, *, browser_schedule):
    """No optional imports, profiles, GUI, socket probes, Store or server controls.

    Release admission remains closed while dependency assets and frozen native
    proof are held. Even an ambient webview package cannot activate this path.
    """
    try:
        require_native_release_admission()
        # This is still a source slice, not an implemented Windows renderer.
        raise NativeRefusal("native_adapter_not_implemented")
    except NativeRefusal:
        browser_schedule(url)
    return None  # retain the exact original app, lifespan and Store owner
