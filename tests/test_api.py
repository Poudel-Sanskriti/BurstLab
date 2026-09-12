import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app


def test_local_session_and_input_limits():
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory), "local")) as client:
            assert client.get("/api/runs").status_code == 401
            assert client.get("/api/session").json()["mode"] == "local"
            assert client.get("/api/runs").status_code == 200
            assert client.post("/api/runs", json={"count": 10000}).status_code == 422
            assert client.post("/api/runs", json={}, headers={"origin": "https://untrusted.example"}).status_code == 403
            assert client.get("/api/runs/missing").status_code == 404
