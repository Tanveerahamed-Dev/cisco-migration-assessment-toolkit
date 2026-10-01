"""Build + smoke-verify the Atlas one-folder bundle (ADR-0004 P2).

    python portable/build_atlas.py [--skip-build] [--port 8479]

Refuses to build with missing assets — or with an Atlas Scope build that is not a /scope
runtime-source hub build — naming the exact commands that produce each (:func:`build_refusal`),
runs PyInstaller over portable/atlas.spec, then copies the RESULT into an isolated field-layout
directory and proves it the same way the field would:

1. ``Atlas.exe --selftest``     must exit 0 with every check green (fail-loud assets all bundled)
   and print each :data:`REQUIRED_SELFTEST_LINES` line exactly, ``[ ok ] atlas-scope-dist`` among them
2. ``Atlas.exe --version``      must report the checkout release (never stale pip metadata)
3. ``Atlas.exe --run-engine --help``  must reach the ENGINE's argparse (the frozen dispatch child)
   while writing its audit log only under ``Atlas\\data``; every other bundle member remains exact
4. boot the server, then over HTTP: /api/health, /api/meta (app identity block), and / must serve
   the SPA's index.html — proving the bundled webapp_dist is found via the _MEIPASS probe — and
   /scope/ must answer 200 with the bundled Atlas Scope shell carrying the runtime-source meta
   (:func:`scope_shell_gap`).

Exit code is non-zero on the first failed step. The bundle lands at portable/dist/Atlas/.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Same hardening the bundle's runtime hook gives Atlas.exe, for THIS script: it re-prints child
# output that may carry glyphs (or U+FFFD replacements) the console codepage cannot encode —
# mojibake beats a UnicodeEncodeError mid-smoke (which is exactly what happened on first run).
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(errors="replace")
    except Exception:
        pass

from portable.atlas_bundle import (  # noqa: E402
    BUILD_OUTPUTS,
    SCOPE_DIST_DEST,
    SCOPE_DIST_SOURCE,
    exe_name,
    missing_data_sources,
    root_files,
)
from portable.windows_version_info import version_expectations, version_strings  # noqa: E402

DIST = ROOT / "portable" / "dist" / exe_name()
EXE = DIST / f"{exe_name()}.exe"


def _run(
    cmd: list,
    timeout: int,
    *,
    cwd: str | Path,
    **kw,
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout,
                          cwd=str(Path(cwd).resolve(strict=True)), **kw)


def _bundle_directory_state(root: Path) -> frozenset[str]:
    """Non-following directory census; file bytes/types are owned by ``collect_members``."""
    root = Path(root).resolve(strict=True)
    directories: set[str] = set()
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as scan:
                entries = sorted(scan, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise SystemExit("field-layout directory census failed") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SystemExit("field-layout entry metadata could not be read") from exc
            reparse = int(getattr(metadata, "st_file_attributes", 0)) & int(
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            if entry.is_symlink() or reparse:
                raise SystemExit("field-layout bundle contains a reparse or symbolic-link entry")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(relative)
                pending.append(path)
            elif not stat.S_ISREG(metadata.st_mode):
                raise SystemExit("field-layout bundle contains a special entry")
    return frozenset(directories)


def _directory_gap(before: frozenset[str], after: frozenset[str]) -> str:
    added = sorted(after - before)
    removed = sorted(before - after)
    parts = []
    if added:
        parts.append(f"added={added[:5]!r}")
    if removed:
        parts.append(f"removed={removed[:5]!r}")
    return "; ".join(parts)


def _detach_runtime_data(bundle: Path, destination: Path) -> None:
    """Move the only mutable subtree away before authoritative member comparison."""
    data = bundle / "data"
    if not os.path.lexists(data):
        raise SystemExit("field-layout smoke did not create the Atlas data directory")
    metadata = data.lstat()
    reparse = int(getattr(metadata, "st_file_attributes", 0)) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if data.is_symlink() or reparse or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit("field-layout smoke data path is not one real directory")
    if data.resolve(strict=True).parent != bundle.resolve(strict=True):
        raise SystemExit("field-layout smoke data directory escapes the copied bundle")
    if os.path.lexists(destination):
        raise SystemExit("field-layout smoke data destination already exists")
    os.replace(data, destination)
    if os.path.lexists(data):
        raise SystemExit("field-layout smoke data directory was not detached atomically")


def _stop_server(server: subprocess.Popen, *, timeout: int = 10) -> None:
    """Stop and reap the smoke server before its temporary working directory is removed."""
    server.terminate()
    try:
        server.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=timeout)


def expected_release() -> str:
    """What the built bundle must report, read through the SAME owner the app reads it from
    (``serve._release_version`` -> ``pyproject.toml``), so there is one source of truth for it."""
    from webapp.backend.serve import _release_version

    return _release_version()


def version_gap(stdout: str, expected: str) -> str:
    """Why ``Atlas.exe --version`` does NOT prove the bundle reports the checkout release, or "".

    The step's docstring has always claimed it proves "the checkout release (never stale pip
    metadata)"; the check was ``"Atlas" not in stdout``, which every possible output of
    ``serve._version_line()`` satisfies — including ``Atlas - release unpackaged - engine schema N``,
    which is EXACTLY what a frozen bundle prints when ``pyproject.toml`` did not land in it
    (``_release_version`` then falls through to dist metadata, absent in a frozen build).

    So ``pyproject.toml`` was the one bundled asset whose absence degrades silently into a wrong
    version, and nothing caught it: ``missing_data_sources`` only proves the SOURCE exists on the
    build box, and ``--selftest`` checks the KB packs, the explorer template, docx/pptx, the dist
    and the engine entry — not this. The build would print "[ok] bundle verified" and every stick cut
    from it would misreport its own version, which is the field's first question in any bug report.
    """
    if "Atlas" not in stdout:
        return "the output does not name the app at all"
    if not expected:
        return "could not read the expected release from the checkout (pyproject.toml)"
    if expected not in stdout:
        return (f"reports {stdout.strip()!r}, not the checkout release {expected!r} — pyproject.toml "
                f"is missing from the bundle, so serve._release_version fell back to dist metadata "
                f"(stale) or 'unpackaged'")
    return ""


#: Lines the frozen ``--selftest`` must print, each EXACTLY (serve.run_selftest owns every name;
#: tests/test_atlas_bundle.py reconciles them against serve.py). Exit 0 alone is not enough: the
#: offline boundary must be proved in its exact mode, and on a frozen bundle the Atlas Scope build
#: must be one AssessHub would serve — a checkout-style "[ -- ] atlas-scope-dist" (not applicable)
#: still exits 0, and would ship a stick whose /scope answers "not built".
REQUIRED_SELFTEST_LINES = (
    "  [ ok ] network-boundary [offline-loopback-only]",
    "  [ ok ] atlas-scope-dist",
)

#: PyInstaller >= 6 one-folder contents directory (``sys._MEIPASS``), where the spec's datas land.
BUNDLE_CONTENTS_DIR = "_internal"
#: Upper bound on the /scope shell the smoke reads (the real shell is a few KiB).
SCOPE_SHELL_READ_LIMIT = 2 * 1024 * 1024


def selftest_gap(stdout: str) -> str:
    """Which required selftest lines are absent from ``stdout`` (exact line match), or ""."""
    printed = {line.rstrip() for line in (stdout or "").splitlines()}
    absent = [line.strip() for line in REQUIRED_SELFTEST_LINES if line not in printed]
    if not absent:
        return ""
    return (f"selftest did not print the required line(s) {absent!r}: the frozen offline network "
            "boundary must be proved in its exact mode, and the bundled Atlas Scope build must be "
            "one AssessHub serves at /scope")


def scope_shell_gap(status: int, content_type: str, body: bytes, bundled_shell: bytes) -> str:
    """Why a ``GET /scope/`` answer does not prove the stick serves its own Atlas Scope view, or "".

    Required: 200, an HTML document, a shell AssessHub reads as a runtime-source hub shell (its
    own reader, ``app._scope_shell_reading`` — exactly one ``atlas-scope-snapshot-source`` meta
    declaring ``assesshub-api-runtime``), and the byte-exact bundled ``atlas_scope_dist/index.html``
    (so a shell served from anywhere else — or AssessHub's own SPA shell — is not taken as proof)."""
    from webapp.backend import app as app_module  # lazy: pulls fastapi

    if status != 200:
        return f"GET /scope/ answered HTTP {status}, not 200 — the bundled Atlas Scope view is not served"
    if content_type.split(";", 1)[0].strip().casefold() != "text/html":
        return f"GET /scope/ answered {content_type!r}, not an HTML document"
    if len(body) > SCOPE_SHELL_READ_LIMIT:
        return f"GET /scope/ answered more than {SCOPE_SHELL_READ_LIMIT} bytes"
    # The reader's own reason (VQF-2): it refuses a shell for more than a missing runtime-source
    # meta (RQF-V2-1: markup in a raw-text element, an element that never ends, not UTF-8), so a
    # fixed wording would name the wrong cause for a shell that carries the meta.
    reason = app_module._scope_shell_tokens(body)
    if isinstance(reason, str):
        return (f"GET /scope/ did not serve a runtime-source hub shell: AssessHub's reader refuses "
                f"it ({reason}; the hub shell declares <meta "
                f"name=\"{app_module._SCOPE_RUNTIME_SOURCE_META}\" "
                f"content=\"{app_module._SCOPE_RUNTIME_SOURCE_VALUE}\"> exactly once)")
    if body != bundled_shell:
        return (f"GET /scope/ served a shell that is not the bundled "
                f"{SCOPE_DIST_DEST}/index.html byte for byte")
    return ""


def windows_version_info_gap(observed: dict, expected: dict) -> str:
    """Return why the PE string table does not match its exact source owners, or ``""``."""
    missing = {
        key: {"expected": value, "observed": observed.get(key)}
        for key, value in expected.items()
        if observed.get(key) != value
    }
    return f"Windows VERSIONINFO differs from source: {missing}" if missing else ""


def _windows_version_info(
    exe: Path,
    environment: dict[str, str],
    *,
    cwd: str | Path,
) -> dict:
    """Read the signed-policy-facing PE metadata through Windows' version API."""
    if os.name != "nt":
        raise SystemExit("Windows VERSIONINFO verification requires Windows")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        raise SystemExit(f"Windows PowerShell is unavailable for VERSIONINFO verification: {powershell}")
    names = tuple(version_strings(ROOT))
    projection = ";".join(f"{name}=$v.{name}" for name in names)
    fixed = (
        'FixedFileVersion="$($v.FileMajorPart).$($v.FileMinorPart).'
        '$($v.FileBuildPart).$($v.FilePrivatePart)";'
        'FixedProductVersion="$($v.ProductMajorPart).$($v.ProductMinorPart).'
        '$($v.ProductBuildPart).$($v.ProductPrivatePart)"'
    )
    script = (
        "$v=(Get-Item -LiteralPath $env:ATLAS_VERSION_INFO_EXE).VersionInfo;"
        f"[ordered]@{{{projection};{fixed}}}|ConvertTo-Json -Compress"
    )
    child_env = dict(environment)
    child_env["ATLAS_VERSION_INFO_EXE"] = str(exe)
    result = _run(
        [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=60,
        env=child_env,
        cwd=cwd,
    )
    if result.returncode:
        raise SystemExit(f"Windows VERSIONINFO probe failed: {result.stderr[-800:]}")
    try:
        value = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise SystemExit(f"Windows VERSIONINFO probe emitted invalid JSON: {result.stdout!r}") from exc
    if not isinstance(value, dict):
        raise SystemExit("Windows VERSIONINFO probe did not emit an object")
    return value


#: What produces each build output the bundle ships, as commands run one per line from the repository
#: root (a person pastes them into Windows PowerShell 5.1, where ``&&`` is a parser error). Keyed by
#: :data:`portable.atlas_bundle.BUILD_OUTPUTS`; ``tests/test_atlas_bundle.py`` fails when a build
#: output has no entry here, so a new one cannot be refused without saying how to make it.
BUILD_OUTPUT_COMMANDS = {
    "webapp/frontend/dist": ("cd webapp/frontend", "npm ci", "npm run build"),
    SCOPE_DIST_SOURCE: ("cd atlas-scope", "npm ci", "npm run build:hub"),
}


def _how_to_build(output: str) -> str:
    return "\n".join(["  Run, from the repository root:"]
                     + [f"    {command}" for command in BUILD_OUTPUT_COMMANDS[output]])


def build_refusal(root: Path) -> str:
    """Why a bundle must not be built from ``root`` (and exactly what to run), or "".

    Two ways the Atlas Scope hub build can be unfit, both refused before PyInstaller runs: it is
    absent (a missing source, as atlas.spec also refuses), or it is PRESENT but is not a /scope
    runtime-source hub build — the standalone root-mounted build, a shell without the
    runtime-snapshot declaration, a build carrying compiled evidence. The second is judged by the
    very index AssessHub serves /scope from (``app._scope_file_index``), so the build refuses
    exactly what the frozen app would refuse, rather than shipping a stick whose --selftest fails."""
    root = Path(root)
    missing = missing_data_sources(root)
    reasons: list[str] = []
    outputs_missing = set()
    for output in BUILD_OUTPUTS:
        base = root / output
        absent = [path for path in missing if Path(path) == base or Path(path).is_relative_to(base)]
        if absent:
            outputs_missing.add(output)
            reasons.append(f"{output} is missing ({len(absent)} required path(s) absent).\n"
                           + _how_to_build(output))
    others = [path for path in missing
              if not any(Path(path) == root / output or Path(path).is_relative_to(root / output)
                         for output in BUILD_OUTPUTS)]
    if others:
        # one checkout path per line, as a person would act on it (never a list repr whose doubled
        # backslashes cannot be pasted)
        named = [Path(path).relative_to(root).as_posix() if Path(path).is_relative_to(root) else str(path)
                 for path in others]
        reasons.append("tracked bundle assets are missing from this checkout:\n"
                       + "\n".join(f"    {path}" for path in named))
    if SCOPE_DIST_SOURCE not in outputs_missing:
        from webapp.backend import app as app_module  # lazy: pulls fastapi

        status = app_module._scope_file_index(root / SCOPE_DIST_SOURCE)[0]
        if status != "ready":
            reasons.append(
                f"{SCOPE_DIST_SOURCE} is present but is not a /scope runtime-source hub build "
                f"({status}): {app_module._SCOPE_UNAVAILABLE_DETAIL.get(status, status)}\n"
                + _how_to_build(SCOPE_DIST_SOURCE))
    if not reasons:
        return ""
    return "Refusing to build an Atlas bundle:\n" + "\n".join(f"- {reason}" for reason in reasons)


def build() -> None:
    refusal = build_refusal(ROOT)
    if refusal:
        raise SystemExit(refusal)
    # A release build never consumes a prior PyInstaller analysis or mixed dist tree.
    for generated in (ROOT / "portable" / "build", DIST):
        resolved = generated.resolve(strict=False)
        if ROOT not in resolved.parents:
            raise SystemExit(f"refusing to clean generated path outside the repository: {resolved}")
        if resolved.exists():
            shutil.rmtree(resolved)
    print("[build] PyInstaller over portable/atlas.spec …")
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "portable" / "atlas.spec"),
         "--clean", "--noconfirm", "--distpath", str(DIST.parent), "--workpath",
         str(ROOT / "portable" / "build")],
        cwd=str(ROOT), stdin=subprocess.DEVNULL, timeout=1800)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller failed (exit {proc.returncode})")
    # Bundle-ROOT tier (README-FIELD.txt): spec datas land under _internal\ on PyInstaller ≥6,
    # where no field engineer would look — copy beside the exe instead.
    for src in root_files(ROOT):
        shutil.copy2(src, DIST / Path(src).name)


def smoke(port: int, *, dist: Path = DIST, environment: dict[str, str] | None = None) -> dict:
    dist = Path(dist).resolve(strict=True)
    source_exe = dist / f"{exe_name()}.exe"
    runtime_env = dict(os.environ if environment is None else environment)
    if not source_exe.is_file():
        raise SystemExit(f"no exe at {source_exe} — build first")
    if os.path.lexists(dist / "data"):
        raise SystemExit("build output already contains runtime data — use a fresh bundle")
    for src in root_files(ROOT):
        if not (dist / Path(src).name).is_file():
            raise SystemExit(
                f"{Path(src).name} missing from the bundle root — required field/legal files "
                "must ride beside the exe"
            )

    with tempfile.TemporaryDirectory(prefix="atlas_smoke_") as td:
        from portable.release_contract import collect_members

        smoke_root = Path(td).resolve(strict=True)
        smoke_bundle = smoke_root / exe_name()
        source_directories = _bundle_directory_state(dist)
        source_members = collect_members(dist)
        shutil.copytree(dist, smoke_bundle, copy_function=shutil.copy2)
        copied_directories = _bundle_directory_state(smoke_bundle)
        copy_gap = _directory_gap(source_directories, copied_directories)
        if copy_gap:
            raise SystemExit(f"field-layout smoke copy differs from build output: {copy_gap}")
        if collect_members(smoke_bundle) != source_members:
            raise SystemExit("field-layout smoke copy has a different verified member set")
        exe = smoke_bundle / f"{exe_name()}.exe"
        db = str(smoke_bundle / "data" / "hub.db")

        print("[smoke 1/4] --selftest")
        p = _run(
            [str(exe), "--selftest", "--db", db],
            timeout=180,
            env=runtime_env,
            cwd=smoke_bundle,
        )
        print("\n".join("    " + ln for ln in (p.stdout or "").strip().splitlines()))
        if p.returncode != 0:
            raise SystemExit(f"selftest FAILED (exit {p.returncode})\n{p.stderr}")
        gap = selftest_gap(p.stdout)
        if gap:
            raise SystemExit(gap)

        print("[smoke 2/4] --version")
        p = _run([str(exe), "--version"], timeout=120, env=runtime_env, cwd=smoke_bundle)
        print(f"    {p.stdout.strip()}")
        gap = version_gap(p.stdout, expected_release()) if p.returncode == 0 else "non-zero exit"
        if gap:
            raise SystemExit(f"--version FAILED (exit {p.returncode}): {gap}\n{p.stderr!r}")
        resource = _windows_version_info(exe, runtime_env, cwd=smoke_bundle)
        resource_gap = windows_version_info_gap(resource, version_expectations(ROOT))
        if resource_gap:
            raise SystemExit(f"--version resource FAILED: {resource_gap}")
        print("    Windows VERSIONINFO matches pyproject, brand, and license owners")

        print("[smoke 3/4] --run-engine --help (frozen engine-child dispatch)")
        p = _run(
            [str(exe), "--run-engine", "--help"],
            timeout=180,
            env=runtime_env,
            cwd=smoke_bundle,
        )
        if p.returncode != 0 or "cisco-assess" not in p.stdout:
            raise SystemExit(f"engine dispatch FAILED (exit {p.returncode}):\n{p.stderr[-800:]}")
        from cisco_toolkit import __version__ as engine_schema_version

        engine_log = smoke_bundle / "data" / (
            f"cisco_migration_autofill_v{engine_schema_version.replace('.', '_')}.log"
        )
        if not engine_log.is_file():
            raise SystemExit("frozen engine dispatch did not place its audit log under Atlas\\data")
        print("    engine argparse reached (usage: cisco-assess …)")
        print("    engine audit log confined to Atlas\\data")

        print(f"[smoke 4/4] serve + HTTP probes on 127.0.0.1:{port}")
        instance_nonce = secrets.token_urlsafe(24)
        child_env = dict(runtime_env)
        child_env["ASSESSHUB_INSTANCE_NONCE"] = instance_nonce
        srv = subprocess.Popen([str(exe), "--no-browser", "--port", str(port), "--db", db],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                               env=child_env, cwd=str(smoke_bundle))
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 60
            last_err = None
            while time.monotonic() < deadline:
                if srv.poll() is not None:
                    out = srv.stdout.read() if srv.stdout else ""
                    raise SystemExit(f"server exited early (code {srv.returncode}):\n{out[-1200:]}")
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=3) as r:
                        health = json.load(r)
                        if (r.status == 200
                                and health.get("instance_nonce") == instance_nonce
                                and srv.poll() is None):
                            break
                        last_err = RuntimeError(
                            "health response did not identify the spawned Atlas child")
                        time.sleep(0.5)
                except (urllib.error.URLError, OSError) as e:  # not up yet
                    last_err = e
                    time.sleep(0.5)
            else:
                raise SystemExit(f"server never answered /api/health: {last_err}")

            with urllib.request.urlopen(base + "/api/meta", timeout=5) as r:
                meta = json.load(r)
            app = meta.get("app") or {}
            if app.get("name") != "Atlas":
                raise SystemExit(f"/api/meta app block wrong: {app!r}")
            print(f"    /api/meta app: {app['title']} · release {app['release']}")

            req = urllib.request.Request(base + "/", headers={"Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=5) as r:
                index = r.read(4096).decode("utf-8", "replace")
            if "<div id=\"root\"" not in index and "<script" not in index:
                raise SystemExit(f"/ did not serve the SPA index: {index[:200]!r}")
            print("    / serves the bundled SPA (webapp_dist found via _MEIPASS)")

            bundled_shell_path = (smoke_bundle / BUNDLE_CONTENTS_DIR / SCOPE_DIST_DEST
                                  / "index.html")
            if not bundled_shell_path.is_file():
                raise SystemExit(f"the bundle carries no {SCOPE_DIST_DEST}/index.html under "
                                 f"{BUNDLE_CONTENTS_DIR} — /scope/ has no shell to serve")
            req = urllib.request.Request(base + "/scope/", headers={"Accept": "text/html"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    scope_status = r.status
                    scope_type = r.headers.get("Content-Type", "") or ""
                    scope_body = r.read(SCOPE_SHELL_READ_LIMIT + 1)
            except urllib.error.HTTPError as refused:
                scope_status = refused.code
                scope_type = (refused.headers.get("Content-Type", "") if refused.headers else "") or ""
                scope_body = b""
            gap = scope_shell_gap(scope_status, scope_type, scope_body,
                                  bundled_shell_path.read_bytes())
            if gap:
                raise SystemExit(gap)
            print("    /scope/ serves the bundled Atlas Scope runtime-source hub shell")
        finally:
            _stop_server(srv)

        _detach_runtime_data(smoke_bundle, smoke_root / "runtime-data")
        final_copied_directories = _bundle_directory_state(smoke_bundle)
        immutable_gap = _directory_gap(copied_directories, final_copied_directories)
        if immutable_gap:
            raise SystemExit(f"smoke mutated the immutable Atlas application tree: {immutable_gap}")
        if collect_members(smoke_bundle) != source_members:
            raise SystemExit("smoke changed the verified Atlas application member set")
        if _bundle_directory_state(smoke_bundle) != final_copied_directories:
            raise SystemExit("smoke directory set changed during final member verification")

    retained_directories = _bundle_directory_state(dist)
    retained_gap = _directory_gap(source_directories, retained_directories)
    if retained_gap:
        raise SystemExit(f"retained build directory set changed during smoke: {retained_gap}")
    if collect_members(dist) != source_members:
        raise SystemExit("retained build output changed while its field-layout copy was tested")
    if _bundle_directory_state(dist) != retained_directories:
        raise SystemExit("retained build directory set changed during final member verification")
    print(f"[ok] field-layout copy verified from: {dist}")
    return {
        "selftest": "pass",
        "version": "pass",
        "engine_help": "pass",
        "loopback_http_api_spa": "pass",
        "loopback_http_scope_runtime_shell": "pass",
        "standard_socket_tcp_udp_dns_denied_loopback_retained": "pass",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true", help="smoke an existing bundle only")
    ap.add_argument("--port", type=int, default=8479, help="smoke-serve port (uncommon on purpose)")
    args = ap.parse_args()
    if not args.skip_build:
        build()
    smoke(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
