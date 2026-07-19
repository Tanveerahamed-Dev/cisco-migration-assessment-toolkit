# PyInstaller runtime hook: a frozen CONSOLE app inherits whatever codepage the field laptop's
# console has (cp437/cp850/…). The banner and selftest output carry em-dashes and middots — never
# let a glyph a legacy codepage can't encode crash a print; mojibake beats a traceback.
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(errors="replace")
    except Exception:
        pass
