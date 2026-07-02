# AssessHub — web cockpit for the Cisco Migration-Assessment engine

AssessHub is a **served, full-stack web platform layered on top of the existing engine**. It is
*additive*: it imports `cisco_toolkit` and re-uses its snapshot contract, diff, trend, and explorer
rendering — it never re-runs analysis, and it does not modify a single line of the engine (the
262-test golden suite is untouched). The CLI engine stays the single source of truth; AssessHub gives
the snapshots it already produces a live surface.

```
SSH collection (CLI engine)  →  snapshot.json  ─┐
                                                ├→  AssessHub store  →  cockpit · planner · war room
raw show-output ZIP  →  engine runs server-side ─┘
```

Two ways in: upload a finished `*.snapshot.json`, **or upload a ZIP of raw show-command outputs**
(one folder per device — the collector's own layout) and AssessHub runs the real engine pipeline
server-side and stores the result as a first-class snapshot.

## What it does

- **Campaigns & waves** — a campaign is a fleet tracked over time; each uploaded snapshot is one wave
  (one collection / cutover checkpoint), persisted in SQLite.
- **Risk cockpit** — per-snapshot: avg-health gauge, health-band distribution, punch-list triaged by
  severity & category, move-group readiness, and the **keystone devices** the fleet most depends on by
  migration blast radius.
- **Cutover planner (run-of-show)** — a synthesis layer over the engine's migration model: a per-wave
  **Go / Conditional-Go / No-Go gate** (from the engine's own readiness checks + any Critical
  cross-layer hit), **pilot-first sequencing** (the safe zero-outage waves scheduled before the risky
  NOT-READY ones), a first-order **maintenance-window estimate** for the single-homed (hard-cutover)
  switches, and a PPDIOO-phased **run-of-show** per wave that wires in that wave's pre-cutover
  remediation and its post-cutover validation commands. Grounded in standard cutover practice:
  make-before-break is a soft/zero-downtime cutover while hard-cutover is break-before-make (needs a
  window); hard-cutover waves get a **dry-run rehearsal** step; the run-of-show captures config +
  live-state backups for rollback; and the window figure is a first-order anchor to calibrate against
  the rehearsal (there is no universal per-device standard).
- **Detail sections** — 15+ tabs (punch-list, health scores, failure impact, chokepoints, causality,
  cross-layer, readiness, wave sequencing, application domains, segmentation, protocols, remediation,
  validation plan, capacity, endpoints, lifecycle/EoL…) sliced straight from the snapshot.
- **Deep explorer** — opens the full single-file `blast_radius_explorer.html` for any snapshot,
  rendered through the engine's own `html.write_html_explorer`.
- **Fleet topology** — a native force-directed graph of the switch fabric (d3-force), nodes coloured by
  health band, single-points-of-failure highlighted, click-a-node to trace its blast radius.
- **Deliverable downloads** — generate and download narrative outputs for any snapshot: the
  Engagement Workflow & Plan of Record (DOCX), CRD (Customer Requirements Document, DOCX),
  Runbook (DOCX), As-Built Design Document (DOCX), per-wave MOP (DOCX), and Executive Deck (PPTX) —
  each produced by the engine's own writer (`engagement`/`crd`/`runbook`/`design`/`mop`/`deck`),
  byte-identical to the CLI (the engagement plan additionally carries the campaign's recorded gate
  sign-offs in its §4.3 "Gate record (as signed)") —
  plus two web-layer syntheses the engine has no CLI writer for: the **Cutover Plan (run-of-show) DOCX**
  (`cutover`) from the planner, and the **Network Ready-For-Use / Acceptance Test Plan DOCX** (`nrfu`) —
  a Cisco-standard NRFU with document-control + sign-off front matter and three test phases (device /
  logical / service) built from the snapshot's lifecycle, `validation_plan`, and service-map data.
- **Gate board** — on the campaign page: per-wave T-minus sign-offs (commit T-28 → checkpoint T-14 →
  readiness T-7 → go/no-go T-1 → window T-0 → hypercare exit T+5). Click a cell to cycle
  pending → GO → NO-GO → SLIPPED → pending; decisions are campaign state and land in the engagement
  deliverable's as-signed gate record.
- **Campaign trajectory** — across ≥2 waves: an IMPROVING / REGRESSING / MIXED verdict plus a
  per-metric trajectory, and a pairwise **compare** (opened/resolved findings, regressed/improved
  health) — both via the engine's `compute_campaign_trend` / `compute_snapshot_delta`.
- **Execution console (war room)** — the cutover plan, made live for the change window: starting a
  run **freezes** the gated plan into an execution record, then every run-of-show step is checked
  off with a timestamp and operator attribution, every validation check records PASS / FAIL / N-A
  against its captured 'expect' baseline (a FAIL records the *observed* output and auto-scribes a
  deviation), waves are closed out (Complete / Rolled back / Deferred — a closed wave's record is
  immutable), and a scribe log keeps the attributed timeline next to a live elapsed-vs-planned-window
  clock. Finishing derives the standard change-management outcome (`SUCCESSFUL · SUCCESSFUL WITH
  DEVIATIONS · PARTIALLY IMPLEMENTED · ROLLED BACK · ABORTED`).
- **Post-Implementation Review (PIR)** — any run (finished or interim) exports an **As-Executed
  Cutover Record DOCX**: document control, planned-vs-actual per wave (the window-calibration loop
  the planner's methodology calls for), the per-wave as-executed log, validation results with
  observed output, the full deviation timeline, and a review-verdict + sign-off section.
- **Raw-collection ingest** — POST a ZIP of `show`-command outputs and the **real engine pipeline**
  runs in a sandboxed subprocess (traversal/zip-bomb guards, hard timeout, off the event loop). A
  bundled `devices.json` is honoured (matched through the engine's own `safe_fs_name`); folders it
  doesn't cover are synthesized with platform autodetection, and an empty parse is rejected rather
  than stored.

## Architecture

```
webapp/
  backend/            FastAPI + SQLite (stdlib sqlite3); imports cisco_toolkit
    app.py            REST surface + serves the built SPA (with history fallback)
    storage.py        campaign / snapshot / execution-run persistence
    summary.py        read-only KPI projection of a snapshot (re-uses engine._trend_point)
    graph.py          switch-topology nodes/edges for the force graph
    cutover.py        read-only synthesis of a gated, pilot-first cutover plan (run-of-show)
    execution.py      live cutover-execution runs (frozen plan, step/check/closeout, outcome)
    ingest.py         raw-collection ZIP → run the real engine in a subprocess → snapshot
    deliverables.py   snapshot deliverables (engine writers reused verbatim + web syntheses)
    cutover_docx.py / nrfu_docx.py / pir_docx.py    web-layer DOCX writers
    docx_style.py     shared python-docx house style (Calibri body, navy headings, banded tables)
    engine.py         the ONLY coupling to cisco_toolkit (path bootstrap + reused fns)
  frontend/           Vite + React + TypeScript SPA; mirrors the explorer's design tokens
  tests/              end-to-end backend tests (FastAPI TestClient, isolated temp DB)
```

The frontend is intentionally one visual family with the explorer: `src/theme.css` mirrors the
explorer's exact `:root` design tokens (dark default + light), so the cockpit and the deep explorer
read as one product.

## Run it

**Prerequisites:** Python 3.10+ with the engine deps installed (`pip install -e .` from the repo
root, or at least `openpyxl`), Node 18+.

```bash
# 1) backend deps
pip install -r webapp/requirements.txt

# 2) build the frontend (the backend serves the built SPA from one origin)
cd webapp/frontend && npm install && npm run build && cd ../..

# 3) serve everything on http://127.0.0.1:8000
python -m uvicorn backend.app:app --app-dir webapp --port 8000
```

Open <http://127.0.0.1:8000>, click **“Open a sample fleet”**, and explore — the sample is the
bundled demo snapshot, no live network needed.

### Access model (client data lives here)

Snapshots are **client data** (topology, IPs, serials, parsed configs), so the API is
locked down by default:

- **Zero-config localhost** — with no token configured, `/api` answers **loopback clients
  only**; CORS allows **localhost origins only** (never `*`). The workflows above are
  unchanged.
- **Any non-local access needs a token** — set `ASSESSHUB_TOKEN=<secret>` on the server
  and send `Authorization: Bearer <secret>`; once set, the token is required on every
  `/api` route (only the `/api/health` liveness probe stays open). Add trusted extra UI
  origins with `ASSESSHUB_CORS_ORIGINS=https://host1,https://host2` if you reverse-proxy.
- The embedded explorer renders in a **sandboxed iframe without `allow-same-origin`**, so
  even its own scripts cannot reach this app's API or storage.

### Dev mode (hot reload)

One command runs both servers (FastAPI autoreload + Vite HMR) and stops both on Ctrl+C:

```bash
python webapp/dev.py        # API :8000 (autoreload) + UI :5173 (HMR, proxies /api -> :8000)
```

Or run them in two terminals yourself:

```bash
python -m uvicorn backend.app:app --app-dir webapp --port 8000 --reload
cd webapp/frontend && npm run dev          # http://localhost:5173
```

### Sample data

The demo "Open a sample fleet" button loads `webapp/sample_data/sample_fleet.snapshot.json` — a
**23-device fleet spanning the full health spectrum** (Excellent 2 / Good 3 / Fair 6 / Poor 6 /
Critical 6: two cores, a redundant HSRP distribution pod, and access archetypes from dual-homed to
err-disabled). Regenerate with `python webapp/sample_data/build_sample.py`, which clones the test
fixtures and runs the real engine. If that file is absent the backend falls back to the small
bundled `tests/golden/snapshot.json`.

### CI

`.github/workflows/webapp-ci.yml` gives the webapp the same treatment as the engine: backend e2e
tests + frontend type-check & build, path-filtered to `webapp/**` and the engine it imports.

## Tests

```bash
python -m pytest webapp/tests -q           # backend e2e (isolated temp DB)
```

## API (selected)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/demo/seed` | create a sample campaign + snapshot from the bundled fixture |
| `GET`  | `/api/campaigns` | list campaigns (+ latest posture summary) |
| `POST` | `/api/campaigns` | create a campaign |
| `POST` | `/api/campaigns/{id}/snapshots` | upload a snapshot `.json` (multipart) |
| `POST` | `/api/campaigns/{id}/ingest` | upload a raw-collection ZIP — the engine runs server-side and the snapshot is stored |
| `GET`  | `/api/campaigns/{id}/trend` | campaign trajectory verdict + per-metric trend |
| `GET`  | `/api/campaigns/{id}/gates` | gate board: cadence + derivable waves + recorded sign-offs |
| `POST` | `/api/campaigns/{id}/gates` | record a gate decision (`go`/`no-go`/`slipped`; `pending` clears) |
| `GET`  | `/api/snapshots/{id}` | snapshot meta + derived KPI summary |
| `GET`  | `/api/snapshots/{id}/section/{name}` | one detail section, sliced from the snapshot |
| `GET`  | `/api/snapshots/{id}/graph` | switch-topology nodes + edges (for the force graph) |
| `GET`  | `/api/snapshots/{id}/cutover` | gated, pilot-first cutover plan (run-of-show) synthesized from the migration model |
| `GET`  | `/api/snapshots/{id}/explorer` | the rendered single-file deep explorer (HTML) |
| `GET`  | `/api/snapshots/{id}/deliverable/{kind}` | generate & download a deliverable (`engagement`/`crd`/`runbook`/`design`/`mop`/`cutover`/`nrfu`/`deck`) |
| `POST` | `/api/compare` | diff two snapshots (`{old_id, new_id}`) |
| `POST` | `/api/snapshots/{id}/executions` | start a war-room run (freezes the cutover plan) |
| `GET`  | `/api/executions/{id}` | run state + derived live progress |
| `POST` | `/api/executions/{id}/step` · `/check` · `/closeout` · `/event` · `/finish` | record the change window: step check-off, validation results, wave closeouts, scribe entries, finish/abort |
| `GET`  | `/api/executions/{id}/report` | Post-Implementation Review / as-executed record (DOCX) |

Interactive API docs at `/docs` when the server is running.
