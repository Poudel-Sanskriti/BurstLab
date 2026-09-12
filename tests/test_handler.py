import unittest
from unittest.mock import patch, Mock
from botocore.exceptions import ClientError
from backend.worker.handler import queue_handler, validate_job, process


class HandlerTests(unittest.TestCase):
    def test_completed_duplicate_does_not_rewrite_artifact(self):
        table, s3 = Mock(), Mock()
        table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
        )
        table.get_item.return_value = {
            "Item": {"status": "succeeded", "object_key": "existing.png"}
        }
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        self.assertEqual(process(job, table, s3)["object_key"], "existing.png")
        s3.put_object.assert_not_called()

    def test_cloud_worker_writes_real_png(self):
        table, s3 = Mock(), Mock()
        table.update_item.return_value = {
            "Attributes": {"attempts": 1, "started_at": 1000}
        }
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        with patch.dict("os.environ", {"BUCKET_NAME": "test-bucket"}):
            result = process(job, table, s3)
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(s3.put_object.call_args.kwargs["Body"].startswith(b"\x89PNG"))

    def test_only_failed_queue_messages_retry(self):
        records = [{"messageId": str(i), "body": '{"lane":"queued"}'} for i in range(3)]
        with patch(
            "backend.worker.handler.process",
            side_effect=[{}, RuntimeError("failed"), {}],
        ):
            result = queue_handler({"Records": records}, None)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "1"}]})

    def test_worker_rejects_unbounded_input(self):
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        self.assertEqual(validate_job(job), job)
        for update in (
            {"delay_ms": 1001},
            {"run_id": "../x"},
            {"max_attempts": 99},
            {"lane": "other"},
        ):
            with self.assertRaises(ValueError):
                validate_job(job | update)
