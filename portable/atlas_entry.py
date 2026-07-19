"""Atlas.exe entry point (PyInstaller). Everything real lives in webapp.backend.serve.main —
freeze_support first, the --run-engine sentinel, --selftest, then uvicorn.run(app)."""
import sys

from webapp.backend.serve import main

if __name__ == "__main__":
    sys.exit(main())
