import asyncio
import hashlib
import json
import math
import random
import time
import uuid
from pathlib import Path
from .models import RunConfig, TERMINAL
from .store import Store
from .worker.core import render_qr


def now_ms():
    return int(time.time() * 1000)


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(run, lane):
    jobs = [j for j in run["jobs"] if j["lane"] == lane]
    counts = {s: sum(j["status"] == s for j in jobs) for s in ("planned", "waiting", "running", "retrying", *sorted(TERMINAL))}
    latencies = [max(0, j["finished_at"] - j["submitted_at"]) for j in jobs if j["status"] == "succeeded" and j.get("submitted_at")]
    waits = [max(0, j["started_at"] - j["submitted_at"]) for j in jobs if j.get("started_at") and j.get("submitted_at")]
    phase = run.get("phases", {}).get(lane, {})
    elapsed = max(0, (phase.get("ended_at") or now_ms()) - phase.get("started_at", now_ms()))
    return {"counts": counts, "total": len(jobs), "completed": counts["succeeded"], "unsuccessful": sum(counts[s] for s in ("failed", "rejected", "dead_letter", "unresolved")), "dispatched": sum(bool(j.get("submitted_at")) for j in jobs), "attempts": sum(j.get("attempts", 0) for j in jobs), "retries": sum(max(0, j.get("attempts", 0) - 1) for j in jobs), "p50_ms": percentile(latencies, .5), "p95_ms": percentile(latencies, .95), "wait_p95_ms": percentile(waits, .95), "latency_samples": len(latencies), "elapsed_ms": elapsed, "throughput": round(len(latencies) / max(.001, elapsed / 1000), 2) if phase else 0}


class Engine:
    def __init__(self, directory: Path, mode="local", cloud=None):
        self.store = Store(directory)
        self.store.recover()
        self.directory = directory
        self.mode = mode
        self.cloud = cloud
        self.active = None
        self.task = None
        self.stop_requested = False

    def emit(self, run, kind, job=None, **fields):
        event = {"seq": len(run["events"]) + 1, "at": now_ms(), "kind": kind, **fields}
        if job is not None:
            event.update(job_id=job["id"], lane=job["lane"], job=json.loads(json.dumps(job)))
        run["events"].append(event)
        self.store.save(run)

    def update(self, run, job, status, **fields):
        job.update(status=status, **fields)
        self.emit(run, "job", job)

    async def start(self, config: RunConfig):
        if self.task and not self.task.done():
            raise ValueError("An experiment is already running.")
        if self.mode == "aws":
            await asyncio.to_thread(self.cloud.preflight, config)
        selected = set(random.Random(config.seed).sample(range(config.count), round(config.count * config.failure_percent / 100)))
        run_id = uuid.uuid4().hex[:16]
        manifest = [{"id": f"job-{i+1:03d}", "payload": f"{config.payload}#job-{i+1:03d}", "fail_first": i in selected} for i in range(config.count)]
        run = {
            "id": run_id, "name": config.name, "mode": self.mode,
            "status": "running", "phase": config.first_lane,
            "created_at": now_ms(), "finished_at": None,
            "config": config.model_dump(),
            "manifest_hash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "worker_version": "qr-v1", "region": self.cloud.region if self.cloud else "local",
            "phases": {}, "events": [],
            "jobs": [dict(item, run_id=run_id, lane=lane, status="planned", attempts=0,
                          attempt_log=[], submitted_at=0, started_at=0, finished_at=0,
                          delay_ms=config.delay_ms, max_attempts=config.max_attempts)
                     for lane in ("direct", "queued") for item in manifest],
            "notes": [
                "Direct: one synchronous attempt, no caller retries. Queued: bounded retries.",
                "Trials run sequentially; compare phase-relative durations.",
                "Configured delays and selected first-attempt failures are artificial experiment conditions.",
                "Local mode models capacity with real QR work; it does not reproduce AWS scheduling or SQS redelivery timing."
                if self.mode == "local" else "AWS trial: queue redelivery may take 90 seconds; cross-machine timing has clock uncertainty.",
            ],
        }
        self.active, self.stop_requested = run, False
        self.emit(run, "created")
        self.task = asyncio.create_task(self._run(run))
        return self.snapshot(run)

    async def _run(self, run):
        order = [run["config"]["first_lane"], "queued" if run["config"]["first_lane"] == "direct" else "direct"]
        try:
            for lane in order:
                run["phase"] = lane
                run["phases"][lane] = {"started_at": now_ms()}
                self.emit(run, "phase_start", lane=lane)
                if self.mode == "aws":
                    await self.cloud.run_lane(self, run, lane)
                else:
                    await self._local_lane(run, lane)
                run["phases"][lane]["ended_at"] = now_ms()
                self.emit(run, "phase_end", lane=lane)
            run["status"] = "stopped" if self.stop_requested else "completed"
        except asyncio.CancelledError:
            run["status"] = "interrupted"
            run["error"] = "Controller stopped; incomplete jobs have unknown outcomes."
        except Exception as exc:
            run["status"] = "error"
            run["error"] = str(exc)[:500]
        finally:
            for job in run["jobs"]:
                if job["status"] not in TERMINAL:
                    self.update(run, job, "unresolved", error="Run ended before a terminal outcome was observed")
            run["finished_at"] = now_ms()
            self.emit(run, "finished")

    async def _local_lane(self, run, lane):
        config = run["config"]
        jobs = [j for j in run["jobs"] if j["lane"] == lane]
        queue = asyncio.Queue()
        active = 0
        tasks = []

        async def attempt(job):
            job["attempts"] += 1
            start = now_ms()
            clock = time.monotonic()
            self.update(run, job, "running", started_at=job["started_at"] or start, last_started_at=start, error="")
            await asyncio.sleep(config["delay_ms"] / 1000)
            injected = job["fail_first"] and job["attempts"] == 1
            if injected:
                duration = round((time.monotonic() - clock) * 1000)
                job["attempt_log"].append({"attempt": job["attempts"], "started_at": start, "ended_at": now_ms(), "duration_ms": duration, "outcome": "injected_failure"})
                status = "failed" if lane == "direct" else ("retrying" if job["attempts"] < config["max_attempts"] else "dead_letter")
                self.update(run, job, status, error="Injected first-attempt failure", duration_ms=duration, finished_at=0 if status == "retrying" else now_ms())
                return False
            try:
                artifact = await asyncio.to_thread(render_qr, job["payload"])
                folder = self.directory / "outputs" / run["id"] / lane
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{job['id']}.png").write_bytes(artifact.content)
                duration = round((time.monotonic() - clock) * 1000)
                job["attempt_log"].append({"attempt": job["attempts"], "started_at": start, "ended_at": now_ms(), "duration_ms": duration, "outcome": "succeeded"})
                self.update(run, job, "succeeded", finished_at=now_ms(), duration_ms=duration, checksum=artifact.checksum, size_bytes=len(artifact.content), result_url=f"/api/runs/{run['id']}/artifacts/{lane}/{job['id']}", error="")
                return True
            except Exception as exc:
                self.update(run, job, "failed", finished_at=now_ms(), error=str(exc)[:300])
                return False

        async def direct(job):
            nonlocal active
            try:
                await attempt(job)
            finally:
                active -= 1

        async def consumer():
            while True:
                job = await queue.get()
                try:
                    await attempt(job)
                    if job["status"] == "retrying":
                        await asyncio.sleep(.15)
                        queue.put_nowait(job)
                finally:
                    queue.task_done()

        consumers = [asyncio.create_task(consumer()) for _ in range(config["concurrency"])] if lane == "queued" else []
        began = time.monotonic()
        try:
            for index, job in enumerate(jobs):
                target = began + (index / config["rate"] if config["pattern"] == "steady" else 0)
                await asyncio.sleep(max(0, target - time.monotonic()))
                if self.stop_requested:
                    self.update(run, job, "cancelled", finished_at=now_ms())
                    continue
                job.update(submitted_at=now_ms(), dispatch_lag_ms=max(0, round((time.monotonic() - target) * 1000)))
                if lane == "direct":
                    if active >= config["concurrency"]:
                        self.update(run, job, "rejected", finished_at=now_ms(), error="Local capacity limit reached (simulated throttle)")
                    else:
                        active += 1
                        self.update(run, job, "waiting")
                        tasks.append(asyncio.create_task(direct(job)))
                else:
                    self.update(run, job, "waiting", accepted_at=now_ms())
                    queue.put_nowait(job)
            if lane == "queued":
                await asyncio.wait_for(queue.join(), timeout=180)
            else:
                await asyncio.gather(*tasks)
        finally:
            for task in consumers + tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*(consumers + tasks), return_exceptions=True)

    def snapshot(self, run):
        return {**run, "metrics": {lane: summarize(run, lane) for lane in ("direct", "queued")}}

    def get(self, run_id):
        run = self.active if self.active and self.active["id"] == run_id else self.store.get(run_id)
        return self.snapshot(run) if run else None

    def history(self):
        return [{k: self.snapshot(r)[k] for k in ("id", "name", "mode", "status", "created_at", "config", "metrics")} for r in self.store.list()]

    def stop(self):
        if self.active and self.task and not self.task.done():
            self.stop_requested = True
            self.active["status"] = "stopping"
            self.emit(self.active, "stop_requested")
        return {"message": "New arrivals stopped; accepted jobs will drain."}
