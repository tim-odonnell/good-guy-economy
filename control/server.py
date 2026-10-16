"""Good-Guy-Economy control server — the backend behind the single desktop icon.

Serves the frontend (static/) and a small API that starts/stops the backend
services, manages the current research topic, and controls the investigation
cron jobs. Loopback-only, single-user machine — no auth layer.
"""
import shutil
from datetime import datetime, timezone
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import orchestration
import state

app = FastAPI(title="Good-Guy-Economy Control")

_op_lock = threading.Lock()


class TopicIn(BaseModel):
    description: str


@app.on_event("startup")
def _startup() -> None:
    state.startup_repair()


def _with_lock(fn, *args, **kwargs):
    if not _op_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="operation_in_progress")
    try:
        return fn(*args, **kwargs)
    finally:
        _op_lock.release()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def get_status():
    ss = orchestration.stack_status()
    core_up = all(ss.get(svc) == "active" for svc in ("good-guy-economy-llm", "camofox-browser"))
    ready = core_up and orchestration.model_ready()

    topic = state.read_topic()
    if not ready:
        phase = "loading"
    elif topic is None:
        phase = "needs_topic"
    else:
        phase = "dashboard"

    jobs = orchestration.load_jobs()
    jobs_out = {}
    for name, j in jobs.items():
        jobs_out[name] = {
            "label": config.JOB_LABELS.get(name, name),
            "state": j.get("state"),
            "last_status": j.get("last_status"),
            "next_run_at": j.get("next_run_at"),
        }

    # Jobs whose scheduled time passed while the gateway was down. Starting the
    # gateway makes Hermes run all of them back to back (~2 h), so the UI warns.
    missed = []
    if ss.get("hermes-gateway") != "active":
        now = datetime.now(timezone.utc)
        for j in jobs_out.values():
            try:
                due = datetime.fromisoformat(j["next_run_at"])
            except Exception:
                continue
            if j["state"] == "scheduled" and due.tzinfo and due < now:
                missed.append(j["label"])

    try:
        total, used, _free = shutil.disk_usage("/home")
        disk_pct = round(used * 100 / total)
    except Exception:
        disk_pct = None

    return {
        "phase": phase,
        "services": ss,
        "model_ready": orchestration.model_ready() if core_up else False,
        "camofox_ready": orchestration.camofox_ready() if core_up else False,
        "gateway_active": ss.get("hermes-gateway") == "active",
        "topic": topic,
        "jobs": jobs_out,
        "missed_jobs": missed,
        "highlights": state.read_highlights(5),
        "disk_percent": disk_pct,
        "busy": _op_lock.locked(),
    }


@app.post("/api/stack/start")
def stack_start():
    results = _with_lock(orchestration.start_core_stack)
    return {"results": [{"service": s, "ok": ok, "detail": e} for s, ok, e in results]}


@app.post("/api/stack/stop")
def stack_stop(force: bool = False):
    if not force and orchestration.llama_busy():
        return JSONResponse({
            "needs_confirm": True,
            "message": "A session looks actively running. Saved findings are safe either "
                       "way — only unsaved in-progress work would be cut off. Stop anyway?",
        })

    def _stop():
        gw_ok, gw_err = orchestration.stop_gateway()
        core = orchestration.stop_core_stack()
        return gw_ok, gw_err, core

    gw_ok, gw_err, core = _with_lock(_stop)
    return {
        "gateway": {"ok": gw_ok, "error": gw_err},
        "results": [{"service": s, "ok": ok, "detail": e} for s, ok, e in core],
    }


@app.post("/api/gateway/start")
def gateway_start():
    ok, err = _with_lock(orchestration.start_gateway)
    if not ok:
        raise HTTPException(status_code=500, detail=err)
    return {"ok": True}


@app.post("/api/gateway/stop")
def gateway_stop():
    ok, err = _with_lock(orchestration.stop_gateway)
    if not ok:
        raise HTTPException(status_code=500, detail=err)
    return {"ok": True}


@app.get("/api/topic")
def topic_get():
    return {"topic": state.read_topic()}


@app.post("/api/topic")
def topic_post(body: TopicIn):
    try:
        record = _with_lock(state.set_topic, body.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"topic": record}


@app.post("/api/jobs/pause")
def jobs_pause():
    results = _with_lock(orchestration.pause_all_jobs)
    return {"results": [{"job": n, "ok": ok, "detail": e} for n, ok, e in results]}


@app.post("/api/jobs/resume")
def jobs_resume():
    results = _with_lock(orchestration.resume_all_jobs)
    return {"results": [{"job": n, "ok": ok, "detail": e} for n, ok, e in results]}


@app.post("/api/jobs/run/{key}")
def jobs_run(key: str):
    name = f"good-guy-economy-{key}"
    if name not in config.JOB_NAMES:
        raise HTTPException(status_code=404, detail="unknown job")
    ok, msg = _with_lock(orchestration.run_job, name)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
