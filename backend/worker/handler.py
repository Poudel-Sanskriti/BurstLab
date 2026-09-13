"""AWS adapters for the shared QR worker. Imports are also usable in local tests."""

import json
import os
import re
import time
import uuid
import logging
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError

try:
    from .core import render_qr
except ImportError:  # SAM packages this directory as the Lambda code root.
    from core import render_qr

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def validate_job(job):
    for key in ("run_id", "id"):
        if not isinstance(job.get(key), str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,80}", job[key]
        ):
            raise ValueError("Invalid job identity")
    if job.get("lane") not in ("direct", "queued"):
        raise ValueError("Invalid lane")
    if (
        not isinstance(job.get("payload"), str)
        or not 0 < len(job["payload"].encode()) <= 512
    ):
        raise ValueError("Invalid payload")
    if (
        not isinstance(job.get("delay_ms", 0), int)
        or not 0 <= job.get("delay_ms", 0) <= 1000
    ):
        raise ValueError("Invalid delay")
    if (
        not isinstance(job.get("max_attempts", 3), int)
        or not 1 <= job.get("max_attempts", 3) <= 5
    ):
        raise ValueError("Invalid attempt limit")
    return job


def native(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [native(v) for v in value]
    return value


def process(job, table=None, s3=None):
    validate_job(job)
    table = (
        table
        if table is not None
        else boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    )
    s3 = s3 if s3 is not None else boto3.client("s3")
    now = lambda: int(time.time() * 1000)
    key = {"PK": job["run_id"], "SK": "JOB#" + job["lane"] + "#" + job["id"]}
    owner = uuid.uuid4().hex
    start = now()
    try:
        claimed = table.update_item(
            Key=key,
            UpdateExpression="SET #s=:running, #owner=:owner, lease_until=:lease, started_at=if_not_exists(started_at,:now), last_started_at=:now, expires_at=:ttl ADD attempts :one",
            ConditionExpression="(attribute_not_exists(#s) OR (#s <> :done AND #s <> :dead)) AND (attribute_not_exists(lease_until) OR lease_until < :now)",
            ExpressionAttributeNames={"#s": "status", "#owner": "owner"},
            ExpressionAttributeValues={
                ":running": "running",
                ":owner": owner,
                ":lease": start + 30000,
                ":now": start,
                ":ttl": int(time.time()) + 86400,
                ":one": 1,
                ":done": "succeeded",
                ":dead": "dead_letter",
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        current = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
        if current.get("status") in ("succeeded", "dead_letter"):
            return native(current)
        raise RuntimeError("Job is leased by another attempt") from exc

    attempt = int(claimed["attempts"])

    def event(status, **fields):
        timestamp = now()
        table.put_item(
            Item={
                "PK": job["run_id"],
                "SK": f"EVENT#{timestamp:016d}#{uuid.uuid4().hex}",
                "type": "event",
                "job_id": job["id"],
                "lane": job["lane"],
                "at": timestamp,
                "status": status,
                "attempt": attempt,
                "expires_at": int(time.time()) + 86400,
                **fields,
            }
        )

    def finish(status, **fields):
        values = {":owner": owner, ":status": status, ":zero": 0, ":done": "succeeded"}
        updates = ["#s=:status", "lease_until=:zero"]
        names = {"#s": "status", "#owner": "owner"}
        for i, (name, value) in enumerate(fields.items()):
            names[f"#f{i}"] = name
            updates.append(f"#f{i}=:v{i}")
            values[f":v{i}"] = value
        table.update_item(
            Key=key,
            UpdateExpression="SET " + ", ".join(updates),
            ConditionExpression="#owner=:owner AND #s <> :done",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        event(status, **fields)

    event("running", started_at=int(claimed["started_at"]))
    if attempt > job.get("max_attempts", 3):
        finish(
            "dead_letter", finished_at=now(), error="Application attempt limit reached"
        )
        return {"status": "dead_letter"}
    began = time.monotonic()
    try:
        time.sleep(job.get("delay_ms", 0) / 1000)
        if job.get("fail_first") and attempt == 1:
            raise RuntimeError("Injected first-attempt failure")
        artifact = render_qr(job["payload"])
        object_key = f"{job['run_id']}/{job['lane']}/{job['id']}.png"
        s3.put_object(
            Bucket=os.environ["BUCKET_NAME"],
            Key=object_key,
            Body=artifact.content,
            ContentType=artifact.media_type,
            Metadata={"sha256": artifact.checksum},
        )
        elapsed = round((time.monotonic() - began) * 1000)
        finish(
            "succeeded",
            finished_at=now(),
            duration_ms=elapsed,
            object_key=object_key,
            checksum=artifact.checksum,
            size_bytes=len(artifact.content),
            error="",
        )
        return {"status": "succeeded", "object_key": object_key, "duration_ms": elapsed}
    except Exception as exc:
        exhausted = attempt >= job.get("max_attempts", 3)
        status = (
            "failed"
            if job["lane"] == "direct"
            else ("dead_letter" if exhausted else "retrying")
        )
        finish(
            status,
            finished_at=now() if status != "retrying" else 0,
            error=str(exc)[:300],
            duration_ms=round((time.monotonic() - began) * 1000),
        )
        raise


def direct_handler(event, context):
    if event.get("lane") != "direct":
        raise ValueError("Direct adapter requires direct lane")
    return process(event)


def queue_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            job = json.loads(record["body"])
            if job.get("lane") != "queued":
                raise ValueError("Queue adapter requires queued lane")
            process(job)
        except Exception:
            log.exception("Queue attempt unsuccessful")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
