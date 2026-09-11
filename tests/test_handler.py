import unittest
from unittest.mock import patch
from backend.worker.handler import queue_handler, validate_job


class HandlerTests(unittest.TestCase):
    def test_only_failed_queue_messages_retry(self):
        records = [{"messageId": str(i), "body": '{"lane":"queued"}'} for i in range(3)]
        with patch("backend.worker.handler.process", side_effect=[{}, RuntimeError("failed"), {}]):
            result = queue_handler({"Records": records}, None)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "1"}]})

    def test_worker_rejects_unbounded_input(self):
        job = {"run_id": "r1", "id": "j1", "lane": "direct", "payload": "hello"}
        self.assertEqual(validate_job(job), job)
        for update in ({"delay_ms": 1001}, {"run_id": "../x"}, {"max_attempts": 99}, {"lane": "other"}):
            with self.assertRaises(ValueError):
                validate_job(job | update)
