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

DIST = ROOT / "portable" / "dist" / exe_name()
EXE = DIST / f"{exe_name()}.exe"


def _run(cmd: list, timeout: int, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout, **kw)


def build() -> None:
    missing = missing_data_sources(ROOT)
    if missing:
        raise SystemExit(f"missing bundle assets: {missing}\n"
                         "Build the frontend first: cd webapp/frontend && npm ci && npm run build")
    print("[build] PyInstaller over portable/atlas.spec …")
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "portable" / "atlas.spec"),
         "--noconfirm", "--distpath", str(DIST.parent), "--workpath",
         str(ROOT / "portable" / "build")],
        cwd=str(ROOT), stdin=subprocess.DEVNULL, timeout=1800)
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller failed (exit {proc.returncode})")
    # Bundle-ROOT tier (README-FIELD.txt): spec datas land under _internal\ on PyInstaller ≥6,
    # where no field engineer would look — copy beside the exe instead.
    for src in root_files(ROOT):
        shutil.copy2(src, DIST / Path(src).name)


def smoke(port: int) -> None:
    if not EXE.is_file():
        raise SystemExit(f"no exe at {EXE} — build first")
    for src in root_files(ROOT):
        if not (DIST / Path(src).name).is_file():
            raise SystemExit(f"{Path(src).name} missing from the bundle root — the field guide "
                             "must ride beside the exe (ADR-0004 P3)")

    with tempfile.TemporaryDirectory(prefix="atlas_smoke_") as td:
        db = str(Path(td) / "data" / "hub.db")

        print("[smoke 1/4] --selftest")
        p = _run([str(EXE), "--selftest", "--db", db], timeout=180)
        print("\n".join("    " + ln for ln in (p.stdout or "").strip().splitlines()))
        if p.returncode != 0:
            raise SystemExit(f"selftest FAILED (exit {p.returncode})\n{p.stderr}")

        print("[smoke 2/4] --version")
        p = _run([str(EXE), "--version"], timeout=120)
        print(f"    {p.stdout.strip()}")
        if p.returncode != 0 or "Atlas" not in p.stdout:
            raise SystemExit(f"--version FAILED (exit {p.returncode}): {p.stdout!r} {p.stderr!r}")

        print("[smoke 3/4] --run-engine --help (frozen engine-child dispatch)")
        p = _run([str(EXE), "--run-engine", "--help"], timeout=180)
        if p.returncode != 0 or "cisco-assess" not in p.stdout:
            raise SystemExit(f"engine dispatch FAILED (exit {p.returncode}):\n{p.stderr[-800:]}")
        print("    engine argparse reached (usage: cisco-assess …)")

        print(f"[smoke 4/4] serve + HTTP probes on 127.0.0.1:{port}")
        srv = subprocess.Popen([str(EXE), "--no-browser", "--port", str(port), "--db", db],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
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
                        if r.status == 200:
                            break
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

    print(f"[ok] bundle verified: {DIST}")


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
