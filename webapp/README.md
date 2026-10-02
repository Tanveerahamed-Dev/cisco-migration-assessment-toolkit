# AssessHub — web cockpit for the Cisco Migration-Assessment engine

AssessHub is the **served web application over the existing engine**. It imports `cisco_toolkit`
for snapshot projections, comparisons, trends and deliverable generation. The Python engine owns
analysis facts; AssessHub gives its evidence a live surface and runs that engine for collection
ingest.

```
SSH collection (CLI engine)  →  snapshot.json  ─┐
                                                ├→  AssessHub store  →  cockpit · planner · war room
raw show-output ZIP  →  engine runs server-side ─┘
```

Three ways in: upload a finished `*.snapshot.json`, **upload a ZIP of raw show-command outputs**
(one folder per device — the collector's own layout), **or ingest a server-local collection
folder** (`/api/campaigns/{id}/ingest-folder` — the portable-app path, where the collection already
sits on disk beside the app). Either way AssessHub runs the real engine pipeline server-side and
stores the result as a first-class snapshot.

## What it does

- **Campaigns & waves** — a campaign is a fleet tracked over time; each uploaded snapshot is one wave
  (one collection / cutover checkpoint), persisted in SQLite.
- **Core assessment** — `/snapshots/{id}` opens Overview, Trust, Inventory with device details,
  and Findings. These screens consume only the typed engine projection, retain missing/withheld
  evidence states, page large lists and expose exact source references in a shared evidence drawer.
  Existing operational panels and downloads remain under `/snapshots/{id}/tools`.
- **Tools risk cockpit** — per-snapshot: avg-health gauge, health-band distribution, punch-list triaged by
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
- **Artifact downloads** — the snapshot catalogue is derived from `docmeta.ARTIFACT_SPECS`, not a
  web-local list. Engine-backed entries reuse their CLI writer; the engagement plan additionally
  receives the campaign's recorded gate sign-offs, so sharing a writer is not a byte-equality claim.
  The registry also declares the AssessHub-owned **Cutover Plan (run-of-show)** and **NRFU /
  Acceptance Test Plan** syntheses. Conditional PIR is deliberately absent from the snapshot
  catalogue: it is generated only from an execution run's report route.
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
    ui_projection_api.py  validated, paged transport for engine-owned core-screen facts
    serve.py          Atlas production entry (ADR-0004 P1): uvicorn.run(app) — no reload/workers,
                      frozen engine-child sentinel (--run-engine), --selftest, browser auto-open
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

# 3) serve everything on http://127.0.0.1:8000 — the one door (auto-opens the browser)
python -m webapp.backend.serve
#    For a factory-driven local Uvicorn process (serve.py remains the production entry):
python -m uvicorn backend.app:create_default_app --factory --app-dir webapp --port 8000
```

Once pip-installed with the web layer (`pip install -e .[webapp]`), the same entry is the
`assesshub` console command. `python -m webapp.backend.serve --selftest` verifies the assets that
otherwise degrade *silently* when missing (explorer template, authoritative OUI/port packs with
their manifested row counts/provenance, docx/pptx extras,
frontend dist, engine entry, DB dir) and exits non-zero on any failure — run it before a field
engagement.

`assesshub --verify-manifest <path>` re-checks a transferred run manifest and every listed
artifact byte by default. Use `--metadata-only` only when the manifest was deliberately separated
from its artifact set; the output states that bytes were skipped. Engine runs already perform the
same full verification immediately after writing the manifest, while this receiver-side command
detects damage introduced later in storage or transfer. The hash chain is corruption-evident, not
producer authentication: retain the full `chain_root` out of band and pass `--expect-root <root>`
when identity to a particular run matters.

Open <http://127.0.0.1:8000>, click **“Open a sample fleet”**, and explore — the sample is the
bundled demo snapshot, no live network needed.

### Access model (client data lives here)

Snapshots are **client data** (topology, IPs, serials, parsed configs), so the API is
locked down by default:

- **Zero-config localhost** — with no token configured, `/api` answers **loopback clients
  only**; CORS allows **localhost origins only** (never `*`). The workflows above are
  unchanged.
- **DNS-rebinding guard** — in zero-config (no-token) mode the request's `Host` header must
  also name a loopback target (`localhost` / `127.0.0.1` / `[::1]`, any port). A page that
  rebinds an attacker domain to `127.0.0.1` carries its own name in `Host`, so it is refused
  even though the socket is loopback. Trust an extra same-host name (e.g. a reverse-proxy
  vhost) with `ASSESSHUB_ALLOWED_HOSTS=host1,host2`. (Token mode is Host-agnostic — the
  Bearer credential, which a rebound page cannot forge, is the authority there.)
- **Any non-local access needs a token and TLS** — set `ASSESSHUB_TOKEN=<secret>` and start
  `assesshub --host <address> --ssl-certfile cert.pem --ssl-keyfile key.pem`. Plain-HTTP bearer
  access from a non-loopback client is refused. The shipped SPA prompts for the token once and
  exchanges it for an HttpOnly, SameSite=Strict browser session, so downloads and the explorer
  iframe work without putting the token in browser storage. Non-browser clients can continue to
  send `Authorization: Bearer <secret>` on every request. Only `/api/health` stays open. Add
  trusted extra UI origins with `ASSESSHUB_CORS_ORIGINS=https://host1,https://host2` if needed.
- The embedded explorer renders in a **sandboxed iframe without `allow-same-origin`**, so
  even its own scripts cannot reach this app's API or storage.

### Dev mode

One command runs both servers and stops their complete process trees on Ctrl+C. Vite keeps HMR;
FastAPI auto-reloads on POSIX. Windows deliberately runs one Uvicorn process so a reloader child
cannot survive teardown:

```bash
python webapp/dev.py        # API :8000 + UI :5173 (HMR, proxies /api -> :8000)
```

Or run them in two terminals yourself:

```bash
python -m uvicorn backend.app:create_default_app --factory --app-dir webapp --port 8000 --reload
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
| `POST` | `/api/campaigns/{id}/ingest-folder` | ingest a **server-local** collection folder (JSON `{path, label}`) — same pipeline, no ZIP round-trip |
| `GET`  | `/api/campaigns/{id}/trend` | campaign trajectory verdict + per-metric trend |
| `GET`  | `/api/campaigns/{id}/gates` | gate board: cadence + derivable waves + recorded sign-offs |
| `POST` | `/api/campaigns/{id}/gates` | record a gate decision (`go`/`no-go`/`slipped`; `pending` clears) |
| `GET`  | `/api/snapshots/{id}` | snapshot meta + derived KPI summary |
| `GET`  | `/api/snapshots/{id}/ui-projection/{view}` | typed core view with first pages of its primary lists |
| `GET`  | `/api/snapshots/{id}/ui-projection/{view}/lists` | one schema-declared list page (`pointer`, `offset`, `limit`) |
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

### Core projection contract

The core views are `overview`, `trust`, `inventory`, `findings` and `device`. Device requests
require the exact hostname as a `host` query parameter, including on subsequent list requests.
An unknown hostname returns the engine's withheld device document; an unknown snapshot is 404.
Unsupported views, list selectors or paging bounds are 422.

The response identifies `ui_projection_transport/1` and `ui_projection/1`, includes the engine
metadata and common limitations registry, and binds the exact stored snapshot bytes by SHA-256,
byte count and `assesshub-store-blob` digest form. Consumers must not combine pages with different
bindings. The backend validates the complete engine document before selecting or slicing it,
then validates its ordinary response through the route's declared response model.

Each primary FactList becomes `{pointer, source_list, page}`. `source_list` retains every owner
field except `items`; `page` carries `offset`, `limit`, `returned`, `total`, `has_more` and the
unchanged selected rows. The default limit is 50 and maximum is 200. Page totals describe the
projected list, not a new engine census. Paging never changes the source evidence state: withheld
lists can retain rows, and an empty end page does not turn a published list into an empty finding.
Original indexes, pointers, evidence references and engine cap disclosures remain intact.
Primary arrays are bounded; this does not bound full projection computation or nested row bytes.

OpenAPI hoists a mechanically rewritten copy of the engine schema; owner-schema parity is
tested. To refresh the frontend types from the actual app without starting a server or opening
a user store, run these commands from the repository root:

```text
python -m webapp.backend.export_ui_projection_openapi --output webapp/frontend/.generated/openapi.json
npm --prefix webapp/frontend run api:generate
npm --prefix webapp/frontend run api:check
```

The generated OpenAPI JSON is temporary; generated TypeScript is tracked. CI exports the current
backend schema and runs the nonwriting type-drift check before building the frontend.
