"""Build + smoke-verify the Atlas one-folder bundle (ADR-0004 P2).

    python portable/build_atlas.py [--skip-build] [--port 8479]

Refuses to build with missing assets, runs PyInstaller over portable/atlas.spec, then treats the
RESULT as untrusted and proves it the same way the field would:

1. ``Atlas.exe --selftest``     must exit 0 with every check green (fail-loud assets all bundled)
2. ``Atlas.exe --version``      must report the checkout release (never stale pip metadata)
3. ``Atlas.exe --run-engine --help``  must reach the ENGINE's argparse (the frozen dispatch child)
4. boot the server, then over HTTP: /api/health, /api/meta (app identity block), and / must serve
   the SPA's index.html — proving the bundled webapp_dist is found via the _MEIPASS probe.

Exit code is non-zero on the first failed step. The bundle lands at portable/dist/Atlas/.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
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

from portable.atlas_bundle import exe_name, missing_data_sources, root_files  # noqa: E402
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


def build() -> None:
    missing = missing_data_sources(ROOT)
    if missing:
        raise SystemExit(f"missing bundle assets: {missing}\n"
                         "Build the frontend first: cd webapp/frontend && npm ci && npm run build")
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
    dist = Path(dist)
    exe = dist / f"{exe_name()}.exe"
    runtime_env = dict(os.environ if environment is None else environment)
    if not exe.is_file():
        raise SystemExit(f"no exe at {exe} — build first")
    for src in root_files(ROOT):
        if not (dist / Path(src).name).is_file():
            raise SystemExit(
                f"{Path(src).name} missing from the bundle root — required field/legal files "
                "must ride beside the exe"
            )

    with tempfile.TemporaryDirectory(prefix="atlas_smoke_") as td:
        smoke_root = Path(td).resolve(strict=True)
        db = str(smoke_root / "data" / "hub.db")

        print("[smoke 1/4] --selftest")
        p = _run(
            [str(exe), "--selftest", "--db", db],
            timeout=180,
            env=runtime_env,
            cwd=smoke_root,
        )
        print("\n".join("    " + ln for ln in (p.stdout or "").strip().splitlines()))
        if p.returncode != 0:
            raise SystemExit(f"selftest FAILED (exit {p.returncode})\n{p.stderr}")
        network_line = "  [ ok ] network-boundary [offline-loopback-only]"
        if network_line not in p.stdout:
            raise SystemExit(
                "selftest did not prove the frozen offline network boundary in its exact mode"
            )

        print("[smoke 2/4] --version")
        p = _run([str(exe), "--version"], timeout=120, env=runtime_env, cwd=smoke_root)
        print(f"    {p.stdout.strip()}")
        gap = version_gap(p.stdout, expected_release()) if p.returncode == 0 else "non-zero exit"
        if gap:
            raise SystemExit(f"--version FAILED (exit {p.returncode}): {gap}\n{p.stderr!r}")
        resource = _windows_version_info(exe, runtime_env, cwd=smoke_root)
        resource_gap = windows_version_info_gap(resource, version_expectations(ROOT))
        if resource_gap:
            raise SystemExit(f"--version resource FAILED: {resource_gap}")
        print("    Windows VERSIONINFO matches pyproject, brand, and license owners")

        print("[smoke 3/4] --run-engine --help (frozen engine-child dispatch)")
        p = _run(
            [str(exe), "--run-engine", "--help"],
            timeout=180,
            env=runtime_env,
            cwd=smoke_root,
        )
        if p.returncode != 0 or "cisco-assess" not in p.stdout:
            raise SystemExit(f"engine dispatch FAILED (exit {p.returncode}):\n{p.stderr[-800:]}")
        print("    engine argparse reached (usage: cisco-assess …)")

        print(f"[smoke 4/4] serve + HTTP probes on 127.0.0.1:{port}")
        instance_nonce = secrets.token_urlsafe(24)
        child_env = dict(runtime_env)
        child_env["ASSESSHUB_INSTANCE_NONCE"] = instance_nonce
        srv = subprocess.Popen([str(exe), "--no-browser", "--port", str(port), "--db", db],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                               env=child_env, cwd=str(smoke_root))
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
        finally:
            srv.terminate()
            try:
                srv.wait(timeout=10)
            except subprocess.TimeoutExpired:
                srv.kill()

    print(f"[ok] bundle verified: {dist}")
    return {
        "selftest": "pass",
        "version": "pass",
        "engine_help": "pass",
        "loopback_http_api_spa": "pass",
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
