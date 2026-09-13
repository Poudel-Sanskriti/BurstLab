import asyncio
import csv
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .engine import Engine
from .models import RunConfig

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentChoice(BaseModel):
    mode: Literal["aws", "local"]


def create_app(directory=None):
    directory = Path(directory or os.environ.get("BURSTLAB_DATA", ROOT / ".data"))
    mode = "aws"
    preference_path = directory / "environment.json"
    if preference_path.is_file():
        try:
            saved = json.loads(preference_path.read_text()).get("mode")
            if saved in ("aws", "local"):
                mode = saved
        except (ValueError, OSError):
            pass
    cloud = None
    setup_message = "Deploy your AWS stack, run scripts/aws.py configure, then restart the controller."
    if (directory / "aws-config.json").is_file():
        from .cloud import Cloud
        try:
            cloud = Cloud(directory / "aws-config.json")
        except Exception:
            setup_message = "AWS configuration could not be loaded. Check aws-config.json and your AWS profile, then restart the controller."
    engine = Engine(directory, mode, cloud)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine.task and not engine.task.done():
            engine.task.cancel()
            await asyncio.gather(engine.task, return_exceptions=True)

    app = FastAPI(
        title="BurstLab",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).hostname not in (
                "localhost",
                "127.0.0.1",
                "testserver",
            ):
                return JSONResponse(
                    {"detail": "Only the local dashboard may access this API."},
                    status_code=403,
                )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    {"detail": "Cross-site requests are not allowed."}, status_code=403
                )
            if request.url.path != "/api/session":
                supplied = request.headers.get(
                    "x-burstlab-token"
                ) or request.cookies.get("burstlab_session", "")
                if not secrets.compare_digest(supplied, token):
                    return JSONResponse(
                        {"detail": "Open the dashboard to establish a local session."},
                        status_code=401,
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def session_info():
        return {
                "token": token,
                "mode": engine.mode,
                "region": cloud.region if cloud else None,
                "configured": cloud is not None,
                "setup_message": None if cloud else setup_message,
                "max_jobs": 100,
                "version": "0.1.0",
                "active_run_id": engine.active["id"]
                if engine.active and engine.task and not engine.task.done()
                else None,
            }

    @app.get("/api/session")
    async def session():
        response = JSONResponse(session_info())
        response.set_cookie("burstlab_session", token, httponly=True, samesite="strict")
        return response

    @app.post("/api/environment")
    async def change_environment(choice: EnvironmentChoice):
        if engine.starting or (engine.task and not engine.task.done()):
            raise HTTPException(409, "Finish the active experiment before switching environments.")
        engine.mode = choice.mode
        engine.active = None
        preference_path.write_text(json.dumps({"mode": choice.mode}))
        return session_info()

    @app.get("/api/runs")
    async def history():
        return [run for run in engine.history() if run["mode"] == engine.mode]

    @app.post("/api/runs", status_code=201)
    async def start(config: RunConfig):
        if engine.mode == "aws" and cloud is None:
            raise HTTPException(503, setup_message)
        try:
            return await engine.start(config)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"AWS preflight failed: {str(exc)[:300]}") from exc

    def get_run(run_id):
        run = engine.get(run_id)
        if run is None or run["mode"] != engine.mode:
            raise HTTPException(404, "Experiment not found")
        return run

    @app.get("/api/runs/{run_id}")
    async def snapshot(run_id: str):
        return get_run(run_id)

    @app.post("/api/runs/{run_id}/stop")
    async def stop(run_id: str):
        get_run(run_id)
        if not engine.active or engine.active["id"] != run_id:
            raise HTTPException(409, "This experiment is not active")
        return engine.stop()

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str, format: str = "json"):
        run = get_run(run_id)
        if format == "csv":
            buffer = io.StringIO()
            fields = [
                "environment",
                "lane",
                "id",
                "status",
                "attempts",
                "submitted_at",
                "started_at",
                "finished_at",
                "duration_ms",
                "error",
            ]
            writer = csv.DictWriter(buffer, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({"environment": run["mode"], **job} for job in run["jobs"])
            return Response(
                buffer.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="burstlab-{run_id}.csv"'
                },
            )
        return Response(
            json.dumps(run, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="burstlab-{run_id}.json"'
            },
        )

    @app.get("/api/runs/{run_id}/artifacts/{lane}/{job_id}")
    async def artifact(run_id: str, lane: str, job_id: str):
        run = get_run(run_id)
        job = next(
            (j for j in run["jobs"] if j["id"] == job_id and j["lane"] == lane), None
        )
        if not job or job["status"] != "succeeded":
            raise HTTPException(404, "No successful artifact for this job")
        if run["mode"] == "aws":
            if cloud is None:
                raise HTTPException(503, setup_message)
            return RedirectResponse(cloud.result_url(job["object_key"]))
        path = directory / "outputs" / run_id / lane / f"{job_id}.png"
        if not path.is_file():
            raise HTTPException(404, "Artifact was cleaned up")
        return FileResponse(path, media_type="image/png")

    @app.get("/{path:path}")
    async def frontend(path: str):
        build = ROOT / "frontend" / "dist"
        candidate = (build / path).resolve()
        if build.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        if (build / "index.html").exists():
            return FileResponse(build / "index.html")
        return JSONResponse(
            {"message": "Backend ready. Build the frontend or run its Vite dev server."}
        )

    return app


app = create_app()
