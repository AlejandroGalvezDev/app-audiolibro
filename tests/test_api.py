from __future__ import annotations

import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.tts.base import SynthesisResult, TTSProvider, Voice


class FakeProvider(TTSProvider):
    id = "fake"
    label = "Fake TTS"
    description = "Proveedor simulado para el test de API"
    requires_key = False

    def availability(self):
        return True, "simulado"

    def static_voices(self):
        return [Voice("fake-voz", "Voz simulada", "es-ES", "Female")]

    async def synthesize(self, text, voice, lang, speed=1.0):
        return SynthesisResult(data=b"FAKEMP3" + text.encode("utf-8"), format="mp3")


def make_pdf_bytes(text: str = "Contenido de prueba del audiolibro simulado.") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    page.insert_text((72, 110), "Segunda línea con suficiente texto para extraer.")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture()
def client(tmp_path):
    base = tmp_path / "library"
    base.mkdir()
    settings = Settings(
        base_path=base,
        data_dir=tmp_path / "data",
        provider_order=("fake",),
        max_upload_mb=5,
    )
    settings.ensure_dirs()
    application = create_app(settings)
    application.state.tts_router.register(
        FakeProvider(settings, application.state.credentials)
    )
    with TestClient(application) as test_client:
        test_client.settings = settings
        test_client.base = base
        yield test_client


def wait_for_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"done", "error"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"El trabajo no terminó a tiempo: {last}")


def test_health_and_pages(client):
    assert client.get("/api/health").json()["status"] == "ok"
    for path in ("/", "/browser", "/register", "/jobs"):
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_providers_endpoint(client):
    response = client.get("/api/providers")
    assert response.status_code == 200
    data = response.json()
    assert any(provider["id"] == "fake" for provider in data["providers"])
    fake = next(provider for provider in data["providers"] if provider["id"] == "fake")
    assert fake["available"] is True
    assert fake["voices"][0]["id"] == "fake-voz"
    assert data["default_provider"] == "fake"


def test_files_listing_and_traversal(client):
    (client.base / "libro.pdf").write_bytes(make_pdf_bytes())
    listing = client.get("/api/files")
    assert listing.status_code == 200
    names = {entry["name"] for entry in listing.json()["entries"]}
    assert "libro.pdf" in names

    traversal = client.get("/api/files", params={"path": "../../etc"})
    assert traversal.status_code == 403
    assert "Acceso denegado" in traversal.json()["detail"]


def test_upload_and_generate(client):
    upload = client.post(
        "/api/upload",
        files={"file": ("mi libro.pdf", make_pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 200
    uploaded = upload.json()
    assert uploaded["upload_id"]
    assert uploaded["filename"] == "mi_libro.pdf"

    response = client.post(
        "/api/generate",
        json={
            "upload_id": uploaded["upload_id"],
            "provider": "fake",
            "voice": "fake-voz",
            "lang": "es-ES",
            "speed": 1.0,
            "format": "mp3",
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    job = wait_for_job(client, job_id)
    assert job["status"] == "done", job
    assert job["progress"] == 100
    assert job["chapters"]
    assert job["title"] == "mi_libro"
    assert job["download_url"] == f"/api/download/{job_id}"

    audio = client.get(f"/api/download/{job_id}")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/mpeg")
    assert b"FAKEMP3" in audio.content

    chapter = client.get(f"/api/download/{job_id}/1")
    assert chapter.status_code == 200
    assert b"FAKEMP3" in chapter.content

    assert client.get(f"/api/download/{job_id}/99").status_code == 404
    assert client.get("/api/jobs/no-existe").status_code == 404


def test_generate_from_server_path(client):
    book = client.base / "servidor.pdf"
    book.write_bytes(make_pdf_bytes())
    response = client.post(
        "/api/generate",
        json={"file_path": "servidor.pdf", "provider": "fake", "lang": "es-ES"},
    )
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "done", job
    assert job["title"] == "servidor"


def test_generate_rejects_path_traversal(client):
    response = client.post(
        "/api/generate",
        json={"file_path": "../../etc/passwd", "provider": "fake"},
    )
    assert response.status_code == 403


def test_generate_requires_source(client):
    response = client.post("/api/generate", json={"provider": "fake"})
    assert response.status_code == 422


def test_upload_rejects_extension(client):
    response = client.post(
        "/api/upload",
        files={"file": ("nota.txt", b"hola", "text/plain")},
    )
    assert response.status_code == 400
    assert "epub" in response.json()["detail"].lower()


def test_credentials_api(client):
    response = client.post(
        "/api/credentials",
        json={"provider": "openai", "values": {"api_key": "sk-test-987654321"}},
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["enabled"] is True

    overview = client.get("/api/credentials").json()
    item = next(item for item in overview["providers"] if item["provider"] == "openai")
    assert item["configured"] is True
    assert item["enabled"] is True
    key_field = next(field for field in item["fields"] if field["name"] == "api_key")
    assert key_field["secret"] is True
    assert "987654321" not in key_field["masked"]
    assert key_field["masked"].endswith("4321")

    cleared = client.delete("/api/credentials/openai")
    assert cleared.status_code == 200
    overview = client.get("/api/credentials").json()
    item = next(item for item in overview["providers"] if item["provider"] == "openai")
    assert item["configured"] is False


def test_provider_toggle_api(client):
    response = client.post("/api/providers/fake/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    providers = client.get("/api/providers").json()["providers"]
    fake = next(provider for provider in providers if provider["id"] == "fake")
    assert fake["available"] is False
    assert "desactivado" in fake["reason"]

    response = client.post("/api/providers/fake/enabled", json={"enabled": True})
    assert response.json()["available"] is True
    assert client.post("/api/providers/nope/enabled", json={"enabled": False}).status_code in {
        400,
        404,
    }


def test_credentials_validation(client):
    response = client.post(
        "/api/credentials",
        json={"provider": "openai", "values": {"campo": "x"}},
    )
    assert response.status_code == 400
    response = client.post("/api/credentials", json={"values": {}})
    assert response.status_code == 422


def test_job_with_unavailable_provider(client):
    book = client.base / "libro.pdf"
    book.write_bytes(make_pdf_bytes())
    response = client.post(
        "/api/generate",
        json={"file_path": "libro.pdf", "provider": "azure"},
    )
    assert response.status_code == 400
    assert "Azure" in response.json()["detail"]


def test_generate_rejects_too_long_document(client):
    client.settings.max_total_chars = 10
    book = client.base / "largo.pdf"
    book.write_bytes(make_pdf_bytes())
    response = client.post(
        "/api/generate",
        json={"file_path": "largo.pdf", "provider": "fake"},
    )
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "error"
    assert "límite" in job["error"]


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
