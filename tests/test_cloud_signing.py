import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
import boto3
from backend.cloud import Cloud


def test_download_signature_uses_regional_bucket_host():
    session = boto3.Session(aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-2")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps({"region": "us-east-2", "outputs": {"TableName": "test-table", "BucketName": "test-bucket"}}))
        with patch("backend.cloud.boto3.Session", return_value=session):
            cloud = Cloud(path)
        url = urlsplit(cloud.result_url("run/direct/job-001.png"))
        assert url.hostname == "test-bucket.s3.us-east-2.amazonaws.com"
        assert "/us-east-2/s3/" in parse_qs(url.query)["X-Amz-Credential"][0]
