import asyncio
import tempfile
import unittest
from pathlib import Path
from backend.engine import Engine
from backend.models import RunConfig


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(Path(self.temp.name))

    async def asyncTearDown(self):
        if self.engine.task and not self.engine.task.done():
            self.engine.task.cancel()
            await asyncio.gather(self.engine.task, return_exceptions=True)
        self.engine.store.db.close()
        self.temp.cleanup()

    async def test_burst_recovery_and_report_reconciliation(self):
        run = await self.engine.start(
            RunConfig(count=8, pattern="burst", delay_ms=10, failure_percent=50)
        )
        await self.engine.task
        result = self.engine.get(run["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["metrics"]["queued"]["completed"], 8)
        self.assertEqual(result["metrics"]["queued"]["retries"], 4)
        self.assertGreater(result["metrics"]["direct"]["counts"]["rejected"], 0)
        for lane in ("direct", "queued"):
            self.assertEqual(sum(result["metrics"][lane]["counts"].values()), 8)
        self.assertEqual(
            len(list(Path(self.temp.name).rglob("*.png"))),
            sum(m["completed"] for m in result["metrics"].values()),
        )

    async def test_single_active_experiment_and_stop(self):
        run = await self.engine.start(RunConfig(count=8, rate=30, delay_ms=0))
        with self.assertRaises(ValueError):
            await self.engine.start(RunConfig())
        self.engine.stop()
        await self.engine.task
        result = self.engine.get(run["id"])
        self.assertEqual(result["status"], "stopped")
        self.assertTrue(all(j["status"] == "cancelled" for j in result["jobs"]))

    async def test_exhausted_retry_is_not_success(self):
        run = await self.engine.start(
            RunConfig(
                count=4, pattern="burst", delay_ms=0, failure_percent=50, max_attempts=1
            )
        )
        await self.engine.task
        result = self.engine.get(run["id"])
        self.assertEqual(result["metrics"]["queued"]["counts"]["dead_letter"], 2)
        self.assertEqual(result["metrics"]["queued"]["completed"], 2)
