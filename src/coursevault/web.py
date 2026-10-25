"""CourseVault local web application.

The server binds to loopback by default. Canvas tokens remain in server memory.
"""
from __future__ import annotations

import atexit
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from .backend import Session, validate_origin
from .offline import archive

app = FastAPI(title="CourseVault", docs_url=None, redoc_url=None)
BASE = Path(tempfile.mkdtemp(prefix="coursevault-web-"))
SESSIONS: dict[str, "WebSession"] = {}
LOCK = threading.RLock()
TTL = 4 * 60 * 60


@dataclass
class WebSession:
    origin: str
    token: str
    created: float = field(default_factory=time.time)
    jobs: dict = field(default_factory=dict)


class ConnectPayload(BaseModel):
    origin: str
    token: str = Field(min_length=10, max_length=8192)


class ExportPayload(BaseModel):
    course_id: int


def current(request: Request) -> WebSession:
    sid = request.cookies.get("cv_session")
    with LOCK:
        session = SESSIONS.get(sid or "")
        if session and time.time() - session.created <= TTL:
            return session
        if sid: SESSIONS.pop(sid, None)
    raise HTTPException(401, "Please connect to Canvas.")


def check_origin(request: Request):
    """Protect state-changing endpoints from cross-site form requests."""
    origin = request.headers.get("origin")
    if origin:
        parsed = urlparse(origin)
        if parsed.hostname not in ("127.0.0.1", "localhost"):
            raise HTTPException(403, "Cross-origin request rejected.")
        if parsed.port != request.url.port:
            raise HTTPException(403, "Unexpected port.")
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "JSON required.")


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "web_index.html").read_text(encoding="utf-8")


@app.post("/api/connect")
def connect(payload: ConnectPayload, request: Request):
    check_origin(request)
    origin = validate_origin(payload.origin)
    # No secrets are persisted to disk or returned to the browser.
    client = Session(origin=origin, access_token=payload.token)
    try:
        courses = client.courses()
    except Exception as exc:
        raise HTTPException(401, "Canvas authentication failed: " + str(exc))
    sid = secrets.token_urlsafe(36)
    with LOCK:
        SESSIONS[sid] = WebSession(origin=origin, token=payload.token)
    response = JSONResponse({"courses": [{"id":c["id"],"name":c.get("name","Untitled"),"course_code":c.get("course_code","")} for c in courses]})
    response.set_cookie("cv_session",sid,httponly=True,samesite="strict",secure=False,max_age=TTL,path="/")
    return response


@app.get("/api/courses")
def courses(request: Request):
    session = current(request)
    try:
        result = Session(origin=session.origin,access_token=session.token).courses()
        return {"courses":[{"id":c["id"],"name":c.get("name","Untitled"),"course_code":c.get("course_code","")} for c in result]}
    except Exception as exc:
        raise HTTPException(502, "Canvas API error: " + str(exc))


@app.post("/api/export")
def start_export(payload: ExportPayload, request: Request):
    check_origin(request)
    session = current(request)
    try:
        available = Session(origin=session.origin,access_token=session.token).courses()
    except Exception as exc:
        raise HTTPException(502, str(exc))
    course = next((c for c in available if int(c["id"]) == payload.course_id), None)
    if not course: raise HTTPException(404, "Course is not available to this account.")
    with LOCK:
        if any(j["status"] in ("queued","running") for j in session.jobs.values()):
            raise HTTPException(409, "An export is already running.")
        job_id = secrets.token_urlsafe(20)
        job = {"status":"queued","message":"Preparing export…","error":None,"report":None,
               "cancel":threading.Event(),"path":BASE / (job_id + ".zip")}
        session.jobs[job_id] = job
    def execute():
        job["status"] = "running"
        try:
            def notify(message):
                job["message"] = message
            client = Session(origin=session.origin, access_token=session.token)
            with __import__("playwright.sync_api",fromlist=["sync_playwright"]).sync_playwright() as pw:
                request = client._request_context(pw)
                try:
                    inventory = client.inventory(request, int(course["id"]), notify)
                finally:
                    request.dispose()
            report = archive(client, course, inventory, job["path"], notify=notify, cancel=job["cancel"])
            job["report"] = report
            job["status"] = "done"
            job["message"] = "Archive ready to download."
        except Exception as exc:
            job["status"] = "cancelled" if job["cancel"].is_set() else "error"
            job["error"] = str(exc)
            job["path"].unlink(missing_ok=True)
    threading.Thread(target=execute,daemon=True).start()
    return {"job_id":job_id}


@app.get("/api/export/{job_id}")
def export_status(job_id: str, request: Request):
    job = current(request).jobs.get(job_id)
    if not job: raise HTTPException(404, "Export not found.")
    return {"status":job["status"],"message":job["message"],"error":job["error"],
            "report":job["report"]}


@app.get("/api/export/{job_id}/download")
def download(job_id: str, request: Request):
    job = current(request).jobs.get(job_id)
    if not job or job["status"] != "done" or not job["path"].exists():
        raise HTTPException(404, "Archive is not ready.")
    return FileResponse(job["path"],media_type="application/zip",filename="CourseVault-export.zip")


@app.post("/api/export/{job_id}/cancel")
def cancel_export(job_id: str, request: Request):
    check_origin(request)
    job = current(request).jobs.get(job_id)
    if not job: raise HTTPException(404, "Export not found.")
    job["cancel"].set()
    return {"ok":True}


@app.post("/api/logout")
def logout(request: Request):
    check_origin(request)
    sid = request.cookies.get("cv_session")
    with LOCK:
        session = SESSIONS.pop(sid or "",None)
    if session:
        for job in session.jobs.values():
            job["cancel"].set()
    response = JSONResponse({"ok":True})
    response.delete_cookie("cv_session")
    return response


def main():
    import uvicorn
    import webbrowser
    import threading
    url = "http://127.0.0.1:8765"
    threading.Timer(1.2,lambda: webbrowser.open(url)).start()
    print("CourseVault is running at " + url)
    uvicorn.run(app,host="127.0.0.1",port=8765,log_level="warning")


if __name__ == "__main__":
    main()
