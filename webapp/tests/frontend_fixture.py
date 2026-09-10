"""Small complete SPA distribution used by web-backend tests."""

from pathlib import Path


def write_frontend_dist(
    dist: Path,
    marker: str = "SPA-SHELL",
    *,
    asset_name: str = "app.js",
    asset_bytes: bytes = b"export const ready = true;",
) -> tuple[bytes, Path]:
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    asset = assets / asset_name
    asset.write_bytes(asset_bytes)
    index_bytes = (
        "<!doctype html><html><head>"
        f'<script type="module" src="/assets/{asset_name}"></script>'
        "</head><body>"
        f'<div id="root">{marker}</div>'
        "</body></html>"
    ).encode("utf-8")
    (dist / "index.html").write_bytes(index_bytes)
    return index_bytes, asset
