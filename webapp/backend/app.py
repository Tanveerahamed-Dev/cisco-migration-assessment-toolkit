"""AssessHub FastAPI application.

REST surface over the snapshot store. The engine produces snapshots (CLI); this serves, slices,
diffs, trends, and renders them. Also serves the built frontend (webapp/frontend/dist) when present,
so the whole platform runs from one origin in production.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, summary
from .storage import Store

_HERE = Path(__file__).resolve().parent
_WEBAPP = _HERE.parent
DEFAULT_DB = os.environ.get("ASSESSHUB_DB", str(_WEBAPP / "data" / "assesshub.db"))
FRONTEND_DIST = _WEBAPP / "frontend" / "dist"

# Prefer the richer, engine-computed demo fleet (webapp/sample_data/build_sample.py); fall back to the
# small bundled golden snapshot if it hasn't been generated.
_RICH_SAMPLE = _WEBAPP / "sample_data" / "sample_fleet.snapshot.json"
_GOLDEN_SAMPLE = _WEBAPP.parent / "tests" / "golden" / "snapshot.json"
SAMPLE_SNAPSHOT = _RICH_SAMPLE if _RICH_SAMPLE.exists() else _GOLDEN_SAMPLE

# Sections the UI may request as a detail slice (top-level snapshot keys it knows how to render).
_ALLOWED_SECTIONS = {k for k, _ in summary.SECTION_LABELS} | {
    "devices", "interfaces", "stp_roots", "routing_neighbors", "subnet_intelligence",
    "endpoint_dependencies", "migration_scenarios", "operational_drift", "security",
    "config_hygiene", "service_map", "addressing_conflicts", "calibration", "score_sensitivity",
}


class CampaignIn(BaseModel):
    name: str
    description: str = ""


class CompareIn(BaseModel):
    old_id: int
    new_id: int


def _parse_snapshot_bytes(raw: bytes) -> Dict[str, Any]:
    try:
        snap = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Not valid snapshot JSON: {e}") from e
    if not isinstance(snap, dict) or "devices" not in snap:
        raise HTTPException(status_code=400,
                            detail="JSON is not an engine snapshot (missing top-level 'devices').")
    return snap


def create_app(db_path: str | None = None) -> FastAPI:
    store = Store(db_path or DEFAULT_DB)
    app = FastAPI(
        title="AssessHub",
        version=engine.ENGINE_SCHEMA_VERSION,
        description="A live web platform over the Cisco Migration-Assessment engine.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.state.store = store

    # -- meta --------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "engine_schema": engine.ENGINE_SCHEMA_VERSION,
                "sample_available": SAMPLE_SNAPSHOT.exists()}

    @app.get("/api/meta")
    def meta() -> Dict[str, Any]:
        return {
            "engine_schema": engine.ENGINE_SCHEMA_VERSION,
            "severity_order": summary.SEVERITY_ORDER,
            "bands": summary.BANDS,
            "section_labels": [{"key": k, "label": v} for k, v in summary.SECTION_LABELS],
        }

    # -- campaigns ---------------------------------------------------------
    @app.get("/api/campaigns")
    def list_campaigns() -> List[Dict[str, Any]]:
        return store.list_campaigns()

    @app.post("/api/campaigns", status_code=201)
    def create_campaign(body: CampaignIn) -> Dict[str, Any]:
        return store.create_campaign(body.name, body.description)

    @app.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: int) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        return c

    @app.delete("/api/campaigns/{campaign_id}", status_code=204)
    def delete_campaign(campaign_id: int):
        if not store.delete_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        return JSONResponse(status_code=204, content=None)

    @app.get("/api/campaigns/{campaign_id}/trend")
    def campaign_trend(campaign_id: int) -> Dict[str, Any]:
        c = store.get_campaign(campaign_id)
        if not c:
            raise HTTPException(404, "Campaign not found")
        snaps = [store.get_snapshot(s["id"]) for s in c["snapshots"]]
        snaps = [s for s in snaps if s]
        return engine.campaign_trend(snaps)

    # -- snapshots ---------------------------------------------------------
    @app.post("/api/campaigns/{campaign_id}/snapshots", status_code=201)
    async def upload_snapshot(campaign_id: int, file: UploadFile = File(...),
                              label: str = Form("")) -> Dict[str, Any]:
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        snap = _parse_snapshot_bytes(await file.read())
        lbl = label.strip() or (file.filename or "snapshot").rsplit(".", 1)[0]
        return store.add_snapshot(campaign_id, lbl, snap, summary.summarize(snap))

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        if not meta:
            raise HTTPException(404, "Snapshot not found")
        return meta

    @app.get("/api/snapshots/{snapshot_id}/section/{name}")
    def get_section(snapshot_id: int, name: str) -> Dict[str, Any]:
        if name not in _ALLOWED_SECTIONS:
            raise HTTPException(400, f"Unknown section '{name}'")
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        if name not in snap:
            raise HTTPException(404, f"Section '{name}' not present in this snapshot")
        return {"section": name, "data": snap[name]}

    @app.get("/api/snapshots/{snapshot_id}/explorer", response_class=HTMLResponse)
    def snapshot_explorer(snapshot_id: int) -> HTMLResponse:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        html = engine.render_explorer_html(snap, meta["label"])
        return HTMLResponse(content=html)

    @app.delete("/api/snapshots/{snapshot_id}", status_code=204)
    def delete_snapshot(snapshot_id: int):
        if not store.delete_snapshot(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return JSONResponse(status_code=204, content=None)

    @app.post("/api/compare")
    def compare(body: CompareIn) -> Dict[str, Any]:
        old = store.get_snapshot(body.old_id)
        new = store.get_snapshot(body.new_id)
        if old is None or new is None:
            raise HTTPException(404, "One or both snapshots not found")
        return engine.snapshot_delta(old, new)

    # -- demo --------------------------------------------------------------
    @app.post("/api/demo/seed")
    def demo_seed() -> Dict[str, Any]:
        """One-click: create a 'Sample Fleet' campaign seeded with the bundled sample snapshot."""
        if not SAMPLE_SNAPSHOT.exists():
            raise HTTPException(503, "No bundled sample snapshot available")
        snap = json.loads(SAMPLE_SNAPSHOT.read_text(encoding="utf-8"))
        c = store.create_campaign("Sample Fleet (demo)",
                                  "Bundled sample snapshot — explore AssessHub with zero setup.")
        s = store.add_snapshot(c["id"], "Baseline collection", snap, summary.summarize(snap))
        return {"campaign": store.get_campaign(c["id"]), "snapshot": s}

    # -- frontend (production) --------------------------------------------
    # Serve the built SPA with a history-fallback: hashed assets are served directly, every other
    # non-API path returns index.html so client-side deep links survive a hard refresh. The /api
    # routes above are registered first, so they always win over this catch-all.
    if FRONTEND_DIST.exists():
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "Not found")
            candidate = FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
