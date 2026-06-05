"""cisco_toolkit - incremental package extraction of COLLECT_PARSE_V3_23_0.py.

PHASE 2.7 (gated) decomposes the single-file script into a stdlib-only package,
one self-contained layer per PR, with the golden regression net verifying each
step. Step 1 (this module set) extracts the pure, leaf-level interface-name /
text normalization helpers into `textutils`; the monolith imports them back so
its references — and the `import COLLECT_PARSE_V3_23_0` entrypoint/tests — keep
working unchanged. Behaviour is byte-identical.
"""

__version__ = "3.23.0"
# NEW-V3.23.40 (PHASE 2.7 step 30): single source of truth for the version, hoisted from the
# monolith so snapshot_state (now in cisco_toolkit.html) and the monolith entrypoint both import it.
