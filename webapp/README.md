# AssessHub — web cockpit for the Cisco Migration-Assessment engine

AssessHub is a **served, full-stack web platform layered on top of the existing engine**. It is
*additive*: it imports `cisco_toolkit` and re-uses its snapshot contract, diff, trend, and explorer
rendering — it never re-runs analysis, and it does not modify a single line of the engine (the
262-test golden suite is untouched). The CLI engine stays the single source of truth; AssessHub gives
the snapshots it already produces a live surface.

```
SSH collection (CLI engine)  →  snapshot.json  →  AssessHub store  →  cockpit + deep explorer
```

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
  remediation and its post-cutover validation commands.
- **Detail sections** — 15+ tabs (punch-list, health scores, failure impact, chokepoints, causality,
  cross-layer, readiness, wave sequencing, application domains, segmentation, protocols, remediation,
  validation plan, capacity, endpoints, lifecycle/EoL…) sliced straight from the snapshot.
- **Deep explorer** — opens the full single-file `blast_radius_explorer.html` for any snapshot,
  rendered through the engine's own `html.write_html_explorer`.
- **Fleet topology** — a native force-directed graph of the switch fabric (d3-force), nodes coloured by
  health band, single-points-of-failure highlighted, click-a-node to trace its blast radius.
- **Deliverable downloads** — generate and download the engine's narrative outputs for any snapshot:
  the Runbook (DOCX), As-Built Design Document (DOCX), per-wave MOP (DOCX), and Executive Deck (PPTX),
  each produced by the engine's own writer (`runbook`/`design`/`mop`/`deck`) — byte-identical to the CLI.
- **Campaign trajectory** — across ≥2 waves: an IMPROVING / REGRESSING / MIXED verdict plus a
  per-metric trajectory, and a pairwise **compare** (opened/resolved findings, regressed/improved
  health) — both via the engine's `compute_campaign_trend` / `compute_snapshot_delta`.

## Architecture

```
webapp/
  backend/            FastAPI + SQLite (stdlib sqlite3); imports cisco_toolkit
    app.py            REST surface + serves the built SPA (with history fallback)
    storage.py        campaign / snapshot persistence
    summary.py        read-only KPI projection of a snapshot (re-uses engine._trend_point)
    cutover.py        read-only synthesis of a gated, pilot-first cutover plan (run-of-show)
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
richer **2-core + 15-access** fleet (regenerate with `python webapp/sample_data/build_sample.py`,
which clones the test fixtures and runs the real engine). If that file is absent the backend falls
back to the small bundled `tests/golden/snapshot.json`.

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
| `GET`  | `/api/campaigns/{id}/trend` | campaign trajectory verdict + per-metric trend |
| `GET`  | `/api/snapshots/{id}` | snapshot meta + derived KPI summary |
| `GET`  | `/api/snapshots/{id}/section/{name}` | one detail section, sliced from the snapshot |
| `GET`  | `/api/snapshots/{id}/graph` | switch-topology nodes + edges (for the force graph) |
| `GET`  | `/api/snapshots/{id}/cutover` | gated, pilot-first cutover plan (run-of-show) synthesized from the migration model |
| `GET`  | `/api/snapshots/{id}/explorer` | the rendered single-file deep explorer (HTML) |
| `GET`  | `/api/snapshots/{id}/deliverable/{kind}` | generate & download a deliverable (`runbook`/`design`/`mop`/`deck`) |
| `POST` | `/api/compare` | diff two snapshots (`{old_id, new_id}`) |

Interactive API docs at `/docs` when the server is running.
