import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app


def test_aws_setup_gate_and_input_limits():
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory))) as client:
            assert client.get("/api/runs").status_code == 401
            session = client.get("/api/session").json()
            assert session["mode"] == "aws"
            assert session["configured"] is False
            assert client.post("/api/runs", json={"count": 1}).status_code == 503
            assert client.get("/api/runs").status_code == 200
            assert client.post("/api/runs", json={"count": 10000}).status_code == 422
            assert (
                client.post(
                    "/api/runs",
                    json={},
                    headers={"origin": "https://untrusted.example"},
                ).status_code
                == 403
            )
            assert client.get("/api/runs/missing").status_code == 404


def test_old_mode_environment_cannot_enable_simulation(monkeypatch):
    monkeypatch.setenv("BURSTLAB_MODE", "local")
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(Path(directory))) as client:
            assert client.get("/api/session").json()["mode"] == "aws"
            assert client.post("/api/runs", json={"count": 1}).status_code == 503


def test_environment_selection_is_explicit_persisted_and_locked_while_running():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory))
        with TestClient(app) as client:
            client.get("/api/session")
            response = client.post("/api/environment", json={"mode": "local"})
            assert response.status_code == 200
            assert response.json()["mode"] == "local"
            assert client.post("/api/environment", json={"mode": "invalid"}).status_code == 422
            app.state.engine.starting = True
            assert client.post("/api/environment", json={"mode": "aws"}).status_code == 409
            app.state.engine.starting = False
        with TestClient(create_app(Path(directory))) as client:
            assert client.get("/api/session").json()["mode"] == "local"
            assert client.post("/api/environment", json={"mode": "aws"}).json()["mode"] == "aws"
            assert client.post("/api/runs", json={"count": 1}).status_code == 503
