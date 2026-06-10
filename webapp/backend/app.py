"""AssessHub FastAPI application.

REST surface over the snapshot store. The engine produces snapshots (CLI); this serves, slices,
diffs, trends, and renders them. Also serves the built frontend (webapp/frontend/dist) when present,
so the whole platform runs from one origin in production.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import cutover, deliverables, engine, execution, graph, ingest, summary
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


class ExecutionIn(BaseModel):
    label: str = ""
    operator: str = ""


class StepIn(BaseModel):
    wave: str
    index: int
    status: str  # pending | done | skipped
    note: str = ""
    operator: str = ""


class CheckIn(BaseModel):
    wave: str
    index: int
    result: str  # pending | pass | fail | na
    observed: str = ""
    operator: str = ""


class CloseoutIn(BaseModel):
    wave: str
    decision: str  # COMPLETE | ROLLED BACK | DEFERRED
    note: str = ""
    operator: str = ""


class EventIn(BaseModel):
    kind: str  # note | deviation
    text: str
    wave: str = ""
    operator: str = ""


class FinishIn(BaseModel):
    status: str  # completed | aborted
    note: str = ""
    operator: str = ""


def _parse_snapshot_bytes(raw: bytes) -> Dict[str, Any]:
    try:
        snap = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Not valid snapshot JSON: {e}") from e
    if not isinstance(snap, dict) or "devices" not in snap:
        raise HTTPException(status_code=400,
                            detail="JSON is not an engine snapshot (missing top-level 'devices').")
    return snap


def _send_file(path: str, media_type: str, filename_stem: str, suffix: str) -> FileResponse:
    """Stream a generated temp file and delete it afterwards; filename is sanitized."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename_stem).strip("_") or "file"
    return FileResponse(
        path, media_type=media_type, filename=f"{safe}{suffix}",
        background=BackgroundTask(lambda p=path: os.path.exists(p) and os.unlink(p)),
    )


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
            "deliverables": deliverables.catalogue(),
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
        # A bare 204 — JSONResponse(content=None) would serialize a "null" body, which uvicorn
        # rejects on a 204 with an ASGI RuntimeError on every delete.
        return Response(status_code=204)

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

    @app.post("/api/campaigns/{campaign_id}/ingest", status_code=201)
    async def ingest_collection(campaign_id: int, file: UploadFile = File(...),
                                label: str = Form("")) -> Dict[str, Any]:
        """Upload a raw collection ZIP (per-device show-command outputs); the real engine pipeline
        runs server-side and the resulting snapshot is stored like an uploaded one."""
        if not store.get_campaign(campaign_id):
            raise HTTPException(404, "Campaign not found")
        # Read with a hard cap — the uncompressed-size guard inside ingest can only run after the
        # whole body is in memory, which is too late against a multi-GB upload.
        chunks: List[bytes] = []
        received = 0
        while chunk := await file.read(1024 * 1024):
            received += len(chunk)
            if received > ingest.MAX_ARCHIVE_BYTES:
                raise HTTPException(
                    413, f"Archive exceeds the {ingest.MAX_ARCHIVE_BYTES // (1024 * 1024)} MB upload limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            # The engine run blocks for seconds-to-minutes; off the event loop so the rest of the
            # API (including a live war-room console) stays responsive.
            snap, report = await run_in_threadpool(ingest.run_collection_zip, raw)
        except ingest.IngestError as e:
            raise HTTPException(400, str(e)) from e
        except ingest.EngineRunError as e:
            raise HTTPException(500, str(e)) from e
        lbl = label.strip() or (file.filename or "collection").rsplit(".", 1)[0]
        meta = store.add_snapshot(campaign_id, lbl, snap, summary.summarize(snap))
        meta["ingest"] = report
        return meta

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

    @app.get("/api/snapshots/{snapshot_id}/graph")
    def snapshot_graph(snapshot_id: int) -> Dict[str, Any]:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        keystones = [k.get("host") for k in (meta["summary"].get("keystones") or []) if k.get("host")]
        return graph.build_graph(snap, keystones)

    @app.get("/api/snapshots/{snapshot_id}/cutover")
    def snapshot_cutover(snapshot_id: int) -> Dict[str, Any]:
        """Gated, pilot-first cutover plan (run-of-show) synthesized from the snapshot's migration model."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        return cutover.build_plan(snap)

    # -- execution runs (war room) ------------------------------------------
    def _mutate_execution(execution_id: int, fn) -> Dict[str, Any]:
        """Atomic read-modify-write on one run's state; returns the updated derived state."""
        with execution.MUTATION_LOCK:
            rec = store.get_execution(execution_id)
            if not rec:
                raise HTTPException(404, "Execution run not found")
            try:
                fn(rec["state"])
            except KeyError as e:
                raise HTTPException(404, f"Unknown wave {e}") from e
            except IndexError as e:
                raise HTTPException(400, "Step/check index out of range") from e
            except (execution.RunClosedError, execution.WaveClosedError) as e:
                raise HTTPException(409, str(e)) from e
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            if not store.save_execution(execution_id, rec["state"]):
                raise HTTPException(404, "Execution run was deleted")
            return execution.with_progress(execution_id, rec["snapshot_id"], rec["state"])

    @app.post("/api/snapshots/{snapshot_id}/executions", status_code=201)
    def start_execution(snapshot_id: int, body: ExecutionIn) -> Dict[str, Any]:
        """Materialize the snapshot's cutover plan into a live, frozen execution run."""
        snap = store.get_snapshot(snapshot_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        label = body.label.strip() or f"Cutover run {store.count_executions(snapshot_id) + 1}"
        state = execution.start_run(snap, label, body.operator)
        if not state["waves"]:
            raise HTTPException(400, "No migration waves were derived from this snapshot — nothing to execute")
        eid = store.create_execution(snapshot_id, state)
        return execution.with_progress(eid, snapshot_id, state)

    @app.get("/api/snapshots/{snapshot_id}/executions")
    def list_executions(snapshot_id: int) -> List[Dict[str, Any]]:
        if not store.get_snapshot_meta(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return store.list_executions(snapshot_id)

    @app.get("/api/executions/{execution_id}")
    def get_execution(execution_id: int) -> Dict[str, Any]:
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        return execution.with_progress(rec["id"], rec["snapshot_id"], rec["state"])

    @app.post("/api/executions/{execution_id}/step")
    def execution_step(execution_id: int, body: StepIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_step(st, body.wave, body.index, body.status,
                                            body.note, body.operator))

    @app.post("/api/executions/{execution_id}/check")
    def execution_check(execution_id: int, body: CheckIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_check(st, body.wave, body.index, body.result,
                                             body.observed, body.operator))

    @app.post("/api/executions/{execution_id}/closeout")
    def execution_closeout(execution_id: int, body: CloseoutIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.apply_closeout(st, body.wave, body.decision,
                                                body.note, body.operator))

    @app.post("/api/executions/{execution_id}/event")
    def execution_event(execution_id: int, body: EventIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.add_event(st, body.kind, body.text, body.wave, body.operator))

    @app.post("/api/executions/{execution_id}/finish")
    def execution_finish(execution_id: int, body: FinishIn) -> Dict[str, Any]:
        return _mutate_execution(
            execution_id,
            lambda st: execution.finish(st, body.status, body.note, body.operator))

    @app.get("/api/executions/{execution_id}/report")
    def execution_report(execution_id: int):
        """Post-Implementation Review / as-executed change record for this run, as .docx."""
        rec = store.get_execution(execution_id)
        if not rec:
            raise HTTPException(404, "Execution run not found")
        if not deliverables.have_docx():
            raise HTTPException(503, "python-docx is not installed on the server")
        from .pir_docx import write_pir_docx

        snap_meta = store.get_snapshot_meta(rec["snapshot_id"])
        snap_label = snap_meta["label"] if snap_meta else "snapshot"
        fd, path = tempfile.mkstemp(suffix=".docx", prefix="assesshub_pir_")
        os.close(fd)
        try:
            write_pir_docx(path, rec["state"], snap_label)
        except Exception as e:
            if os.path.exists(path):
                os.unlink(path)
            raise HTTPException(500, f"Failed to generate the PIR: {e}") from e
        return _send_file(
            path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            rec["state"].get("label", "run"), "_pir.docx")

    @app.delete("/api/executions/{execution_id}", status_code=204)
    def delete_execution(execution_id: int):
        # Under the mutation lock so a delete can't land inside another request's
        # read-modify-write window (whose save would then be a silent no-op).
        with execution.MUTATION_LOCK:
            if not store.delete_execution(execution_id):
                raise HTTPException(404, "Execution run not found")
        return Response(status_code=204)

    @app.get("/api/snapshots/{snapshot_id}/explorer", response_class=HTMLResponse)
    def snapshot_explorer(snapshot_id: int) -> HTMLResponse:
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        html = engine.render_explorer_html(snap, meta["label"])
        return HTMLResponse(content=html)

    @app.get("/api/snapshots/{snapshot_id}/deliverable/{kind}")
    def snapshot_deliverable(snapshot_id: int, kind: str):
        if kind not in deliverables.SPECS:
            raise HTTPException(400, f"Unknown deliverable '{kind}'")
        meta = store.get_snapshot_meta(snapshot_id)
        snap = store.get_snapshot(snapshot_id)
        if snap is None or meta is None:
            raise HTTPException(404, "Snapshot not found")
        if not deliverables.availability().get(kind):
            raise HTTPException(503, f"{deliverables.SPECS[kind].needs} is not installed on the server")
        try:
            path = deliverables.generate(kind, snap, meta["label"])
        except Exception as e:  # generation failure (e.g. a malformed snapshot)
            raise HTTPException(500, f"Failed to generate {kind}: {e}") from e
        spec = deliverables.SPECS[kind]
        return _send_file(path, spec.media, meta["label"], f"_{kind}.{spec.ext}")

    @app.delete("/api/snapshots/{snapshot_id}", status_code=204)
    def delete_snapshot(snapshot_id: int):
        if not store.delete_snapshot(snapshot_id):
            raise HTTPException(404, "Snapshot not found")
        return Response(status_code=204)

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
