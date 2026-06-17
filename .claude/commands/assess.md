---
description: Run / drive a full Cisco migration assessment and report the current-state inventory + gap analysis.
argument-hint: [devices.json | --no-collect --collection-dir migration_collection_<stamp>]
---
Drive an end-to-end assessment of the brownfield estate, then report.

SCOPE: $ARGUMENTS

Delegate the analysis to the **assessment-analyst** subagent. The engine is the source of truth — entry point `cisco-assess` (`COLLECT_PARSE_V3_23_0:main`):
- Fresh run (SSHes to live gear — only if explicitly requested): `cisco-assess --devices-file devices.json --template Migration_Assessment_Template_Updated.xlsx --output Migration_Assessment_AUTOFILLED_<stamp>.xlsx`
- Re-analyze an existing collection (default, safe): add `--no-collect --collection-dir migration_collection_<stamp>`.
- If a `*.snapshot.json` is given, read it directly rather than re-running.

Report: device / VLAN / endpoint inventory, software & EoL lifecycle, topology, and a prioritized **gap analysis** (each gap: severity, owner, success metric). Include an explicit "not collected / low confidence" section — never let silence read as healthy. Cite evidence for every claim. Do not run a live collection unless the scope above explicitly says to.
