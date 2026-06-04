# Cisco Migration-Assessment Toolkit

A Python toolkit that connects to Cisco switches, parses their `show`-command
output, and rolls the full **L1 → L4 + cross-layer + protocol** picture up into
two decision-ready outputs: a per-switch **health score (0–100)** and a per
move-group **migration-readiness verdict** (`READY` / `CAUTION` / `NOT READY`).
Results are written to an Excel workbook and to a self-contained, interactive
**Blast-Radius Explorer** HTML viewer.

> ℹ️ The topology embedded in the bundled `blast_radius_explorer.html` is
> **demo/sample data** (private `10.0.x.x` addresses, generic `CORE` / `DIST`
> labels) — not a real network capture.

## Repository contents

| File | What it is |
|------|------------|
| [`COLLECT_PARSE_V3_23_0.py`](COLLECT_PARSE_V3_23_0.py) | The toolkit — collects over SSH (netmiko), parses, scores health, computes migration readiness, and writes the workbook + explorer. |
| [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) | Documentation for the current version (health scoring, the 10-check readiness checklist, the HTML Health mode) plus the change log. |
| [`blast_radius_explorer.html`](blast_radius_explorer.html) | The interactive single-file explorer that renders a collected snapshot (topology, findings, and the 🏥 Health view). |
| [`compass_artifact_..._markdown1.md`](compass_artifact_wf-4178d659-b124-4412-9854-fc7bea5b9094_text_markdown1.md) | Design playbook — best-practice layout, color, and interaction redesign for the Explorer. |
| [`compass_artifact_..._markdown.md`](compass_artifact_wf-6d4cf577-c82e-4281-8744-55bdc473f75d_text_markdown.md) | Hardening playbook — parsing robustness, collection, scoring validation, and an accessible Explorer. |

## Requirements

- **Python 3** (3.8+ recommended)
- [`netmiko`](https://pypi.org/project/netmiko/) — SSH collection
- [`openpyxl`](https://pypi.org/project/openpyxl/) — Excel read/write
- Everything else is the standard library.

```bash
pip install netmiko openpyxl
```

## Inputs & outputs

**Inputs**
- A **devices file** (`--devices-file`, JSON) describing what to connect to (see below).
- A **template workbook** (`--template`, default `Migration_Assessment_Template_Updated.xlsx`)
  used as the starting point for the filled report. *Provide your own; it is not
  included in this repo.*

**Outputs** (written to the working directory)
- `Migration_Assessment_AUTOFILLED_<timestamp>.xlsx` — the filled workbook,
  including the `Health Scores` and `Migration Readiness` sheets.
- A Blast-Radius Explorer HTML file beside the workbook (unless `--no-html`).

## Usage

```bash
# Collect from devices, then build the workbook and explorer
python COLLECT_PARSE_V3_23_0.py \
    --devices-file devices.json \
    --template Migration_Assessment_Template_Updated.xlsx

# Diff two previously saved snapshots into a change workbook (no SSH, no template)
python COLLECT_PARSE_V3_23_0.py --compare old_snapshot.json new_snapshot.json

# See every option
python COLLECT_PARSE_V3_23_0.py --help
```

Useful flags: `--workers N` (parallel SSH workers, default 5; `1` = sequential),
`--no-html` (skip the explorer), `--output FILE` (override the workbook name),
and `--flow-src IP` / `--flow-dst IP` (add an optional flow-trace sheet between
two endpoints). See [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md) for
the full feature set.

### Devices file

A JSON file — accepted as an array, a single object, or one object per line.
Each entry needs `ip`, `hostname`, and `username` (common aliases like `host`,
`name`, and `user` are accepted). `platform` is optional and autodetected when
omitted (`ios` / `nxos` / `auto`).

```json
[
  { "hostname": "core-1", "ip": "10.0.0.1", "username": "netadmin", "platform": "ios" },
  { "hostname": "dist-1", "ip": "10.0.0.2", "username": "netadmin", "password_env": "DIST1_PASS", "platform": "nxos" }
]
```

**Passwords** resolve in this order, so secrets need not live in the file:

1. an explicit `"password"` on the entry,
2. `"password_env": "VAR"` — read from that environment variable,
3. the global `$CISCO_PASS` environment variable,
4. a secure `getpass` prompt (interactive terminals only).

Authentication failures are **never** retried (this avoids account lockout);
transient connection/timeout failures are retried with backoff.

## Health score & migration readiness

The score starts at 100 with weighted, **per-category-capped** deductions across
L1, L3, cross-layer, and protocol findings, banded **Excellent / Good / Fair /
Poor / Critical**. Migration readiness runs a 10-check pre-migration checklist
per move group: any hard-fail check → `NOT READY`, otherwise any warn →
`CAUTION`, otherwise `READY`. Both the weights and band thresholds are a
defensible default, not calibrated against a labelled dataset — tune to taste.
Full details are in [`COLLECT_PARSE_V3_23_0.md`](COLLECT_PARSE_V3_23_0.md).
