import asyncio
import csv
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .engine import Engine
from .models import RunConfig

ROOT = Path(__file__).resolve().parents[1]


def create_app(directory=None, mode=None):
    directory = Path(directory or os.environ.get("BURSTLAB_DATA", ROOT / ".data"))
    mode = mode or os.environ.get("BURSTLAB_MODE", "local")
    if mode not in ("local", "aws"):
        raise ValueError("BURSTLAB_MODE must be local or aws")
    cloud = None
    if mode == "aws":
        from .cloud import Cloud
        cloud = Cloud(directory / "aws-config.json")
    engine = Engine(directory, mode, cloud)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine.task and not engine.task.done():
            engine.task.cancel()
            await asyncio.gather(engine.task, return_exceptions=True)

    app = FastAPI(title="BurstLab", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1", "testserver"):
                return JSONResponse({"detail": "Only the local dashboard may access this API."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
            if request.url.path != "/api/session":
                supplied = request.headers.get("x-burstlab-token") or request.cookies.get("burstlab_session", "")
                if not secrets.compare_digest(supplied, token):
                    return JSONResponse({"detail": "Open the dashboard to establish a local session."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/session")
    async def session():
        response = JSONResponse({"token": token, "mode": mode, "region": cloud.region if cloud else "local", "max_jobs": 100, "version": "0.1.0", "active_run_id": engine.active["id"] if engine.active and engine.task and not engine.task.done() else None})
        response.set_cookie("burstlab_session", token, httponly=True, samesite="strict")
        return response

    @app.get("/api/runs")
    async def history():
        return engine.history()

    @app.post("/api/runs", status_code=201)
    async def start(config: RunConfig):
        try:
            return await engine.start(config)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"AWS preflight failed: {str(exc)[:300]}") from exc

    def get_run(run_id):
        run = engine.get(run_id)
        if run is None:
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
            fields = ["lane", "id", "status", "attempts", "submitted_at", "started_at", "finished_at", "duration_ms", "error"]
            writer = csv.DictWriter(buffer, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(run["jobs"])
            return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="burstlab-{run_id}.csv"'})
        return Response(json.dumps(run, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="burstlab-{run_id}.json"'})

    @app.get("/api/runs/{run_id}/artifacts/{lane}/{job_id}")
    async def artifact(run_id: str, lane: str, job_id: str):
        run = get_run(run_id)
        job = next((j for j in run["jobs"] if j["id"] == job_id and j["lane"] == lane), None)
        if not job or job["status"] != "succeeded":
            raise HTTPException(404, "No successful artifact for this job")
        if run["mode"] == "aws":
            if cloud is None:
                raise HTTPException(409, "Restart in AWS mode to open cloud artifacts")
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
        return JSONResponse({"message": "Backend ready. Build the frontend or run its Vite dev server."})

    return app


app = create_app()
