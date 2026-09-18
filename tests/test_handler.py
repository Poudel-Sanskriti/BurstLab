import unittest
from unittest.mock import patch, Mock
from botocore.exceptions import ClientError
from backend.worker.handler import queue_handler, validate_job, process


class HandlerTests(unittest.TestCase):
    def test_admission_rejects_without_generating_when_all_slots_are_busy(self):
        table, s3 = Mock(), Mock()
        busy = ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        table.update_item.side_effect = [busy, busy, {}]
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        with patch.dict("os.environ", {"MAX_ACTIVE_JOBS": "2"}):
            self.assertEqual(process(job, table, s3)["status"], "rejected")
        s3.put_object.assert_not_called()

    def test_admission_releases_slot_after_success(self):
        table, s3 = Mock(), Mock()
        table.update_item.return_value = {"Attributes": {"attempts": 1, "started_at": 1000}}
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        with patch.dict("os.environ", {"MAX_ACTIVE_JOBS": "2", "BUCKET_NAME": "test"}):
            self.assertEqual(process(job, table, s3)["status"], "succeeded")
        table.delete_item.assert_called_once()

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
        for call in table.update_item.call_args_list:
            names = call.kwargs["ExpressionAttributeNames"]
            self.assertEqual(names["#owner"], "owner")
            self.assertNotIn(" owner=", call.kwargs["UpdateExpression"])
            self.assertNotIn("error=", call.kwargs["UpdateExpression"])
        self.assertIn("error", table.update_item.call_args.kwargs["ExpressionAttributeNames"].values())

    def test_failure_update_aliases_error_field(self):
        table, s3 = Mock(), Mock()
        table.update_item.return_value = {"Attributes": {"attempts": 1, "started_at": 1000}}
        job = {"run_id": "r1", "id": "j1", "lane": "queued", "payload": "hello", "fail_first": True}
        with self.assertRaisesRegex(RuntimeError, "Injected"):
            process(job, table, s3)
        update = table.update_item.call_args.kwargs
        self.assertIn("error", update["ExpressionAttributeNames"].values())
        self.assertNotIn("error=", update["UpdateExpression"])
        self.assertIn("#owner", update["ConditionExpression"])

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
