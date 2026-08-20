"""Refresh reviewed visual-baseline privacy pins without widening the image allowlist.

The visual suite owns two screenshots for every component registered in
``.design-sync/config.json``: ``<Name>.png`` at its configured primary viewport
(900 CSS pixels by default) and ``<Name>-728.png`` at the product-pane bound.
This helper refuses partial, extra, malformed, linked, or wrongly-sized sets. Its default mode is a
read-only freshness check.  Rewriting the verifier requires both ``--write``
and the explicit ``--reviewed`` acknowledgement and changes only the
sentinel-bounded generated block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


_CONFIG = PurePosixPath(".design-sync/config.json")
_BASELINE_DIR = PurePosixPath(
    "webapp/frontend/visual-e2e/__screenshots__/windows-2025-x64"
)
_VERIFIER = PurePosixPath(".github/scripts/verify_repository_privacy.py")
_PIN_START = "# BEGIN GENERATED SYNTHETIC VISUAL BASELINE PINS"
_PIN_END = "# END GENERATED SYNTHETIC VISUAL BASELINE PINS"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_BYTES = 5_000_000
_MAX_PNG_HEIGHT = 20_000
_MAX_CONFIG_BYTES = 1_000_000
_MAX_VERIFIER_BYTES = 4_000_000
_DEFAULT_PRIMARY_WIDTH = 900
_PRODUCT_PANE_WIDTH = 728
_COMPONENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_VIEWPORT = re.compile(r"([1-9]\d*)x([1-9]\d*)\Z")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PinRefreshError(ValueError):
    """The reviewed baseline set is incomplete, unsafe, or internally inconsistent."""


def _disk_path(root: Path, relative: PurePosixPath) -> Path:
    return root.joinpath(*relative.parts)


def _metadata_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _directory_identity(info: os.stat_result) -> tuple[int, int, int]:
    # Directory size and mtime legitimately change when this helper creates its atomic temp file.
    return (int(info.st_dev), int(info.st_ino), int(info.st_mode))


def _is_reparse_point(info: os.stat_result) -> bool:
    return bool(int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT)


def _directory_chain(
    root: Path, relative: PurePosixPath
) -> tuple[tuple[Path, tuple[int, ...]], ...]:
    """Pin every directory from ``root`` through ``relative`` without following aliases."""
    if relative.is_absolute() or ".." in relative.parts:
        raise PinRefreshError(f"unsafe repository-relative path: {relative}")
    paths = [root]
    current = root
    for part in relative.parts:
        current /= part
        paths.append(current)

    chain = []
    for path in paths:
        try:
            info = path.lstat()
        except OSError as exc:
            raise PinRefreshError(f"directory chain is unavailable: {path}") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or _is_reparse_point(info)
            or not stat.S_ISDIR(info.st_mode)
        ):
            raise PinRefreshError(
                f"directory chain must contain only ordinary directories: {path}"
            )
        chain.append((path, _directory_identity(info)))
    return tuple(chain)


def _assert_directory_chain(
    chain: tuple[tuple[Path, tuple[int, ...]], ...]
) -> None:
    for path, expected in chain:
        try:
            info = path.lstat()
        except OSError as exc:
            raise PinRefreshError(f"directory chain changed while reading: {path}") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or _is_reparse_point(info)
            or not stat.S_ISDIR(info.st_mode)
            or _directory_identity(info) != expected
        ):
            raise PinRefreshError(f"directory chain changed while reading: {path}")


def _relative_file(
    root: Path, relative: PurePosixPath
) -> tuple[Path, tuple[tuple[Path, tuple[int, ...]], ...]]:
    if relative.is_absolute() or not relative.name or ".." in relative.parts:
        raise PinRefreshError(f"unsafe repository-relative file path: {relative}")
    parent = PurePosixPath(*relative.parts[:-1])
    return _disk_path(root, relative), _directory_chain(root, parent)


def _relative_directory(
    root: Path, relative: PurePosixPath
) -> tuple[Path, tuple[tuple[Path, tuple[int, ...]], ...]]:
    chain = _directory_chain(root, relative)
    return _disk_path(root, relative), chain


def _read_regular_bounded(
    path: Path, maximum: int
) -> tuple[bytes, tuple[int, int, int, int, int]]:
    """Read one stable ordinary file through a bounded, non-following descriptor."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise PinRefreshError(f"file is unreadable: {path}") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise PinRefreshError(f"file must be a regular non-link file: {path}")
    if before.st_size <= 0 or before.st_size > maximum:
        raise PinRefreshError(f"file size is outside 1..{maximum} bytes: {path}")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _metadata_identity(before) != _metadata_identity(opened)
        ):
            raise PinRefreshError(f"file identity changed before it was read: {path}")
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, maximum + 1 - len(data)),
            )
            if not chunk:
                break
            data.extend(chunk)
        after_open = os.fstat(descriptor)
    except OSError as exc:
        raise PinRefreshError(f"file is unreadable: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        after_path = path.lstat()
    except OSError as exc:
        raise PinRefreshError(f"file identity changed while it was read: {path}") from exc
    identities = {
        _metadata_identity(before),
        _metadata_identity(opened),
        _metadata_identity(after_open),
        _metadata_identity(after_path),
    }
    if (
        len(identities) != 1
        or stat.S_ISLNK(after_path.st_mode)
        or _is_reparse_point(after_path)
        or not stat.S_ISREG(after_path.st_mode)
    ):
        raise PinRefreshError(f"file identity changed while it was read: {path}")
    if not data or len(data) > maximum:
        raise PinRefreshError(f"file size is outside 1..{maximum} bytes: {path}")
    return bytes(data), _metadata_identity(after_path)


def _read_relative(
    root: Path, relative: PurePosixPath, maximum: int
) -> tuple[
    bytes,
    tuple[int, int, int, int, int],
    tuple[tuple[Path, tuple[int, ...]], ...],
]:
    path, chain = _relative_file(root, relative)
    _assert_directory_chain(chain)
    data, identity = _read_regular_bounded(path, maximum)
    _assert_directory_chain(chain)
    return data, identity, chain


def _component_widths(root: Path) -> dict[str, int]:
    try:
        raw, _, _ = _read_relative(root, _CONFIG, _MAX_CONFIG_BYTES)
        config = json.loads(raw.decode("utf-8", errors="strict"))
        source_map = config["componentSrcMap"]
        overrides = config.get("overrides", {})
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise PinRefreshError(f"cannot read component contract: {_CONFIG}") from exc
    if not isinstance(source_map, dict) or not source_map:
        raise PinRefreshError("componentSrcMap must be a non-empty object")
    names = tuple(sorted(source_map))
    if any(not isinstance(name, str) or not _COMPONENT_NAME.fullmatch(name) for name in names):
        raise PinRefreshError("componentSrcMap contains a name unsafe for a baseline filename")
    if not isinstance(overrides, dict):
        raise PinRefreshError("overrides must be an object when present")

    widths: dict[str, int] = {}
    for name in names:
        override = overrides.get(name, {})
        if not isinstance(override, dict):
            raise PinRefreshError(f"override for {name} must be an object")
        viewport = override.get("viewport")
        if viewport is None:
            widths[name] = _DEFAULT_PRIMARY_WIDTH
            continue
        match = _VIEWPORT.fullmatch(viewport) if isinstance(viewport, str) else None
        if not match:
            raise PinRefreshError(f'invalid viewport for {name}: "{viewport}"')
        widths[name] = min(int(match.group(1)), 2000)
    return widths


def configured_components(root: Path) -> tuple[str, ...]:
    return tuple(_component_widths(root))


def expected_relative_paths(root: Path) -> tuple[str, ...]:
    paths = []
    for name in configured_components(root):
        paths.append((_BASELINE_DIR / f"{name}.png").as_posix())
        paths.append((_BASELINE_DIR / f"{name}-728.png").as_posix())
    return tuple(sorted(paths))


def _invalid_png(relative: str, reason: str) -> PinRefreshError:
    return PinRefreshError(
        f"baseline is not a structurally valid PNG ({reason}): {relative}"
    )


def _png_contract(relative: str, data: bytes, expected_width: int) -> dict[str, Any]:
    if len(data) < 8 or data[:8] != _PNG_SIGNATURE:
        raise _invalid_png(relative, "signature")

    offset = 8
    ihdr: bytes | None = None
    idat = bytearray()
    saw_iend = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise _invalid_png(relative, "truncated chunk")
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise _invalid_png(relative, "truncated chunk payload")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(data[offset + 8 + length : chunk_end], "big")
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise _invalid_png(relative, "chunk CRC")

        if chunk_type == b"IHDR":
            if ihdr is not None or offset != 8 or length != 13:
                raise _invalid_png(relative, "IHDR order or length")
            ihdr = payload
        elif chunk_type == b"IDAT":
            if ihdr is None or saw_iend:
                raise _invalid_png(relative, "IDAT order")
            idat.extend(payload)
        elif chunk_type == b"IEND":
            if ihdr is None or not idat or saw_iend or length != 0:
                raise _invalid_png(relative, "IEND order or length")
            saw_iend = True
            offset = chunk_end
            if offset != len(data):
                raise _invalid_png(relative, "trailing bytes")
            break
        else:
            raise _invalid_png(relative, f"unexpected {chunk_type!r} chunk")
        offset = chunk_end

    if ihdr is None or not idat or not saw_iend:
        raise _invalid_png(relative, "incomplete chunk stream")
    width = int.from_bytes(ihdr[:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
    # Playwright screenshots are non-interlaced, 8-bit true-colour PNGs. Pin that encoder shape
    # as well as the pixels so palette/metadata carriers cannot enter through this exception.
    if ihdr[8:] != b"\x08\x02\x00\x00\x00":
        raise _invalid_png(relative, "unsupported IHDR fields")
    if width != expected_width or not 700 <= height <= _MAX_PNG_HEIGHT:
        raise PinRefreshError(
            f"baseline dimensions are invalid for {relative}: {width}x{height}; "
            f"expected {expected_width}x700..{_MAX_PNG_HEIGHT}"
        )

    expected_decoded = height * (1 + width * 3)
    decoder = zlib.decompressobj()
    pending = bytes(idat)
    decoded = bytearray()
    try:
        while pending:
            room = max(1, expected_decoded + 1 - len(decoded))
            before_pending = len(pending)
            decoded.extend(decoder.decompress(pending, room))
            if len(decoded) > expected_decoded:
                raise _invalid_png(relative, "decoded payload exceeds dimensions")
            pending = decoder.unconsumed_tail
            if pending and len(pending) == before_pending:
                raise _invalid_png(relative, "decoder made no progress")
    except zlib.error as exc:
        raise _invalid_png(relative, "invalid IDAT stream") from exc
    if (
        not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or len(decoded) != expected_decoded
    ):
        raise _invalid_png(relative, "IDAT stream does not match dimensions")
    stride = 1 + width * 3
    if any(decoded[row * stride] > 4 for row in range(height)):
        raise _invalid_png(relative, "invalid scanline filter")
    return {
        "bytes": len(data),
        "height": height,
        "media_type": "image/png",
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": width,
    }


def build_pin_contracts(root: Path) -> dict[str, dict[str, Any]]:
    widths = _component_widths(root)
    expected_widths = {
        (_BASELINE_DIR / f"{name}.png").as_posix(): width
        for name, width in widths.items()
    }
    expected_widths.update(
        {
            (_BASELINE_DIR / f"{name}-728.png").as_posix(): _PRODUCT_PANE_WIDTH
            for name in widths
        }
    )
    expected = tuple(sorted(expected_widths))
    baseline_dir, baseline_chain = _relative_directory(root, _BASELINE_DIR)
    try:
        entries = list(baseline_dir.iterdir())
    except OSError as exc:
        raise PinRefreshError(f"baseline directory is unavailable: {_BASELINE_DIR}") from exc
    _assert_directory_chain(baseline_chain)
    observed = {
        (_BASELINE_DIR / entry.name).as_posix()
        for entry in entries
    }
    missing = sorted(set(expected) - observed)
    extra = sorted(observed - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise PinRefreshError(
            "visual baseline set must be exactly two PNGs per configured component; "
            + "; ".join(details)
        )

    contracts: dict[str, dict[str, Any]] = {}
    for relative in expected:
        data, _, _ = _read_relative(root, PurePosixPath(relative), _MAX_PNG_BYTES)
        contracts[relative] = _png_contract(relative, data, expected_widths[relative])
    return contracts


def render_pin_block(contracts: dict[str, dict[str, Any]]) -> str:
    lines = ["_SYNTHETIC_VISUAL_BASELINES = {"]
    for relative in sorted(contracts):
        contract = contracts[relative]
        lines.extend(
            [
                f'    "{relative}": {{',
                f'        "bytes": {contract["bytes"]:_},',
                f'        "height": {contract["height"]},',
                '        "media_type": "image/png",',
                f'        "sha256": "{contract["sha256"]}",',
                f'        "width": {contract["width"]},',
                "    },",
            ]
        )
    lines.append("}")
    return "\n".join(lines)


def replace_generated_block(source: str, generated: str) -> str:
    if source.count(_PIN_START) != 1 or source.count(_PIN_END) != 1:
        raise PinRefreshError("verifier must contain exactly one visual-pin sentinel pair")
    start = source.index(_PIN_START) + len(_PIN_START)
    end = source.index(_PIN_END)
    if end <= start:
        raise PinRefreshError("visual-pin sentinels are out of order")
    newline = "\r\n" if "\r\n" in source else "\n"
    block = generated.replace("\n", newline)
    return source[:start] + newline + block + newline + source[end:]


def _write_atomic(
    path: Path,
    text: str,
    expected_identity: tuple[int, int, int, int, int],
    parent_chain: tuple[tuple[Path, tuple[int, ...]], ...],
) -> None:
    _assert_directory_chain(parent_chain)
    try:
        current = path.lstat()
    except OSError as exc:
        raise PinRefreshError("verifier changed before pin refresh") from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or _is_reparse_point(current)
        or not stat.S_ISREG(current.st_mode)
        or _metadata_identity(current) != expected_identity
    ):
        raise PinRefreshError("verifier changed before pin refresh")
    mode = current.st_mode
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.chmod(temporary, stat.S_IMODE(mode))
        _assert_directory_chain(parent_chain)
        if _metadata_identity(path.lstat()) != expected_identity:
            raise PinRefreshError("verifier changed before pin refresh")
        os.replace(temporary, path)
        _assert_directory_chain(parent_chain)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or refresh exact privacy pins for reviewed visual baselines."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true", help="replace the generated pin block")
    parser.add_argument(
        "--reviewed",
        action="store_true",
        help="confirm every changed PNG was visually reviewed before pinning",
    )
    args = parser.parse_args(argv)
    if args.write != args.reviewed:
        parser.error("--write and --reviewed must be supplied together")

    root = Path(os.path.abspath(args.root))
    try:
        contracts = build_pin_contracts(root)
        generated = render_pin_block(contracts)
        source_raw, verifier_identity, verifier_chain = _read_relative(
            root, _VERIFIER, _MAX_VERIFIER_BYTES
        )
        verifier = _disk_path(root, _VERIFIER)
        source = source_raw.decode("utf-8", errors="strict")
        refreshed = replace_generated_block(source, generated)
    except (OSError, UnicodeError, PinRefreshError) as exc:
        print(f"visual baseline pin refresh failed: {exc}")
        return 1

    if not args.write:
        if refreshed != source:
            print(
                "visual baseline privacy pins are stale; visually review the PNGs, then run "
                "with --write --reviewed"
            )
            return 1
        print(f"visual baseline privacy pins are current ({len(contracts)} exact files)")
        return 0

    try:
        _write_atomic(verifier, refreshed, verifier_identity, verifier_chain)
    except (OSError, PinRefreshError) as exc:
        print(f"visual baseline pin refresh failed: {exc}")
        return 1
    print(f"updated {len(contracts)} exact visual baseline privacy pins after review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
