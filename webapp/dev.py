#!/usr/bin/env python
"""One-command dev mode for AssessHub: FastAPI (autoreload) + Vite (HMR), together.

    python webapp/dev.py

Backend on http://127.0.0.1:8000 (autoreloads on .py changes), UI on http://localhost:5173
(hot-reloads on frontend changes, proxies /api -> :8000). Ctrl+C stops both. Cross-platform.

For a production-style single-origin run instead, build the frontend (`npm run build` in
webapp/frontend) and serve only uvicorn — see webapp/README.md.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FRONTEND = os.path.join(HERE, "frontend")


def main() -> int:
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        print("frontend deps missing — run:  cd webapp/frontend && npm install", file=sys.stderr)
        return 1

    npm = "npm.cmd" if os.name == "nt" else "npm"
    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.app:app",
                   "--app-dir", HERE, "--port", "8000", "--reload"]
    frontend_cmd = [npm, "run", "dev"]

    procs: list[subprocess.Popen] = []
    try:
        # cwd=REPO so both `backend.*` (via --app-dir) and `cisco_toolkit` resolve on sys.path.
        procs.append(subprocess.Popen(backend_cmd, cwd=REPO))
        procs.append(subprocess.Popen(frontend_cmd, cwd=FRONTEND))
        print("\n  AssessHub dev mode")
        print("  API : http://127.0.0.1:8000   (autoreload)")
        print("  UI  : http://localhost:5173   (HMR, proxies /api -> :8000)")
        print("  Ctrl+C to stop both.\n")
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"\n[dev] a process exited (code {p.returncode}); shutting down.", file=sys.stderr)
                    return p.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[dev] stopping…")
        return 0
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
