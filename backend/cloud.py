"""AWS data plane. Never instantiated in local mode."""
import asyncio
import json
import time
from pathlib import Path
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from .engine import now_ms
from .models import TERMINAL
from .worker.handler import native


class Cloud:
    def __init__(self, config_path: Path):
        config = json.loads(config_path.read_text())
        self.region = config["region"]
        self.outputs = config["outputs"]
        session = boto3.Session(region_name=self.region, profile_name=config.get("profile"))
        self.lambda_client = session.client("lambda", config=Config(retries={"total_max_attempts": 1}, connect_timeout=3, read_timeout=25, max_pool_connections=32))
        self.sqs = session.client("sqs", config=Config(retries={"total_max_attempts": 1}))
        self.s3 = session.client("s3")
        self.table = session.resource("dynamodb").Table(self.outputs["TableName"])
        self.seen = set()

    def preflight(self, config):
        for name in ("DirectFunction", "QueuedFunction"):
            function = self.lambda_client.get_function_configuration(FunctionName=self.outputs[name])
            cap = self.lambda_client.get_function_concurrency(FunctionName=self.outputs[name]).get("ReservedConcurrentExecutions")
            if cap != config.concurrency or function["MemorySize"] != 256 or function["Timeout"] != 15:
                raise ValueError("AWS worker settings do not match this experiment. Deploy both workers with the selected concurrency, 256 MB, and a 15-second timeout.")
        mappings = self.lambda_client.list_event_source_mappings(FunctionName=self.outputs["QueuedFunction"], EventSourceArn=self.outputs["QueueArn"])["EventSourceMappings"]
        if not mappings or mappings[0]["State"] != "Enabled":
            raise ValueError("Queue trigger is disabled. Enable it with the AWS helper before running a cloud experiment.")
        for queue in ("QueueUrl", "DeadLetterUrl"):
            attributes = self.sqs.get_queue_attributes(QueueUrl=self.outputs[queue], AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible", "ApproximateNumberOfMessagesDelayed"])["Attributes"]
            if any(int(v) for v in attributes.values()):
                raise ValueError("A lab queue still contains work. Drain or clear it before starting a new trial.")

    def _items(self, run_id):
        kwargs = {"KeyConditionExpression": Key("PK").eq(run_id), "ConsistentRead": True}
        items = []
        while True:
            response = self.table.query(**kwargs)
            items.extend(native(response["Items"]))
            if "LastEvaluatedKey" not in response:
                return items
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    async def reconcile(self, engine, run):
        items = await asyncio.to_thread(self._items, run["id"])
        lookup = {(j["lane"], j["id"]): j for j in run["jobs"]}
        for item in sorted((x for x in items if x.get("type") == "event"), key=lambda x: (x["at"], x["SK"])):
            if item["SK"] in self.seen:
                continue
            self.seen.add(item["SK"])
            job = lookup.get((item["lane"], item["job_id"]))
            if job is None:
                continue
            attempt = int(item["attempt"])
            if item["status"] != "running":
                job["attempt_log"].append({"attempt": attempt, "ended_at": item["at"], "duration_ms": item.get("duration_ms", 0), "outcome": item["status"]})
            engine.emit(run, "aws_observation", job_id=job["id"], lane=job["lane"], observed_at=item["at"], status=item["status"], attempt=attempt)
        for item in (x for x in items if x["SK"].startswith("JOB#")):
            _, lane, identifier = item["SK"].split("#")
            job = lookup.get((lane, identifier))
            if job is None:
                continue
            fields = {k: item[k] for k in ("status", "attempts", "started_at", "last_started_at", "finished_at", "duration_ms", "object_key", "checksum", "size_bytes", "error") if k in item}
            if fields.get("status") == "succeeded":
                fields["result_url"] = f"/api/runs/{run['id']}/artifacts/{lane}/{identifier}"
            if any(job.get(k) != v for k, v in fields.items()):
                job.update(fields)
                engine.emit(run, "job", job)

    async def run_lane(self, engine, run, lane):
        jobs = [j for j in run["jobs"] if j["lane"] == lane]
        config = run["config"]
        tasks = []
        slots = asyncio.Semaphore(30)

        async def submit(job):
            async with slots:
                if engine.stop_requested:
                    engine.update(run, job, "cancelled", finished_at=now_ms())
                    return
                job["submitted_at"] = now_ms()
                engine.update(run, job, "waiting")
                payload = {k: job[k] for k in ("id", "run_id", "lane", "payload", "fail_first", "delay_ms", "max_attempts")}
                try:
                    if lane == "queued":
                        await asyncio.to_thread(self.sqs.send_message, QueueUrl=self.outputs["QueueUrl"], MessageBody=json.dumps(payload))
                        job["accepted_at"] = now_ms()
                        engine.emit(run, "job", job)
                    else:
                        response = await asyncio.to_thread(self.lambda_client.invoke, FunctionName=self.outputs["DirectFunction"], InvocationType="RequestResponse", Payload=json.dumps(payload).encode())
                        response["Payload"].read()
                        if response.get("FunctionError"):
                            engine.update(run, job, "failed", error="Lambda reported a function error; see attempt details", finished_at=now_ms())
                except ClientError as exc:
                    code = exc.response["Error"]["Code"]
                    status = "rejected" if code in ("TooManyRequestsException", "AccessDeniedException", "InvalidParameterValueException") else "unresolved"
                    engine.update(run, job, status, error=code, finished_at=now_ms())
                except Exception as exc:
                    engine.update(run, job, "unresolved", error="Caller outcome unknown: " + str(exc)[:200], finished_at=now_ms())

        async def generate():
            start = time.monotonic()
            for i, job in enumerate(jobs):
                target = start + (i / config["rate"] if config["pattern"] == "steady" else 0)
                await asyncio.sleep(max(0, target - time.monotonic()))
                job["dispatch_lag_ms"] = max(0, round((time.monotonic() - target) * 1000))
                tasks.append(asyncio.create_task(submit(job)))
            await asyncio.gather(*tasks)

        producer = asyncio.create_task(generate())
        deadline = time.monotonic() + 600
        try:
            while time.monotonic() < deadline:
                await self.reconcile(engine, run)
                if producer.done():
                    await producer
                    if all(j["status"] in TERMINAL for j in jobs):
                        break
                await asyncio.sleep(2)
            if not producer.done():
                producer.cancel()
            await self.reconcile(engine, run)
            for job in jobs:
                if job["status"] not in TERMINAL:
                    engine.update(run, job, "unresolved", error="Observation window ended; check AWS queues before another run")
        finally:
            if not producer.done():
                producer.cancel()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer, *tasks, return_exceptions=True)

    def result_url(self, object_key):
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.outputs["BucketName"], "Key": object_key}, ExpiresIn=300)
