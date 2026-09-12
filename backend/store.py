"""Local run history. All writes occur on the controller's event-loop thread."""

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.db = sqlite3.connect(directory / "runs.sqlite3", check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created INTEGER, document TEXT)"
        )
        self.db.commit()

    def save(self, run):
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?)",
            (run["id"], run["created_at"], json.dumps(run)),
        )
        self.db.commit()

    def get(self, run_id):
        row = self.db.execute(
            "SELECT document FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self):
        rows = self.db.execute(
            "SELECT document FROM runs ORDER BY created DESC LIMIT 50"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover(self):
        for run in self.list():
            if run["status"] in ("running", "stopping"):
                run["status"] = "interrupted"
                run["finished_at"] = int(time.time() * 1000)
                for phase in run.get("phases", {}).values():
                    phase.setdefault("ended_at", run["finished_at"])
                run["error"] = (
                    "Controller restarted. AWS jobs may have continued; reconcile before starting another cloud run."
                )
                for job in run["jobs"]:
                    if job["status"] not in {
                        "succeeded",
                        "failed",
                        "rejected",
                        "dead_letter",
                        "cancelled",
                    }:
                        job["status"] = "unresolved"
                self.save(run)
