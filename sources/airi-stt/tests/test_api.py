import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from main import app, CONFIG


def auth_headers(api_key):
    return {"X-API-KEY": api_key}


def test_health(client, api_key):
    response = client.get("/health", headers=auth_headers(api_key))
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "model" in data


def test_missing_api_key(client):
    response = client.get("/health")
    assert response.status_code == 403


def test_invalid_api_key(client):
    response = client.get("/health", headers={"X-API-KEY": "wrong"})
    assert response.status_code == 403


def test_unauthorized_ip(client, api_key):
    c = TestClient(app, headers={"X-Forwarded-For": "1.2.3.4"})
    response = c.get("/health", headers=auth_headers(api_key))
    assert response.status_code == 403


def test_missing_file(client, api_key):
    response = client.post("/transcribe", headers=auth_headers(api_key))
    assert response.status_code == 422


def test_transcribe_sample(client, api_key):
    model = Path(CONFIG["whisper"]["model_path"])
    if not model.exists():
        pytest.skip("Whisper model not available")

    sample = Path(__file__).parent / "samples" / "sample_es_01.mp3"
    if not sample.exists():
        pytest.skip("No sample audio found")

    with open(sample, "rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": ("sample_es_01.mp3", f, "audio/mpeg")},
            headers=auth_headers(api_key),
        )
    assert response.status_code == 200
    data = response.json()
    assert "text" in data
    assert isinstance(data["text"], str)
    assert len(data["text"]) > 0


def test_transcribe_plain_sample(client, api_key):
    model = Path(CONFIG["whisper"]["model_path"])
    if not model.exists():
        pytest.skip("Whisper model not available")

    sample = Path(__file__).parent / "samples" / "sample_es_01.mp3"
    if not sample.exists():
        pytest.skip("No sample audio found")

    with open(sample, "rb") as f:
        response = client.post(
            "/transcribe/plain",
            files={"file": ("sample_es_01.mp3", f, "audio/mpeg")},
            headers=auth_headers(api_key),
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert len(response.text) > 0
