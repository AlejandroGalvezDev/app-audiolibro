from __future__ import annotations

import asyncio
import os

import pytest

from app.config import Settings
from app.services.credentials import CredentialStore
from app.tts.edge_tts_provider import EdgeTTSProvider


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS") != "1",
    reason="Requiere red; ejecuta con RUN_NETWORK_TESTS=1",
)
def test_edge_tts_generates_real_audio(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    provider = EdgeTTSProvider(settings, CredentialStore(settings))
    result = asyncio.run(
        provider.synthesize(
            "Hola, esto es una prueba de audio.",
            "es-ES-AlvaroNeural",
            "es-ES",
            speed=1.0,
        )
    )
    assert result.format == "mp3"
    assert len(result.data) > 2000
    # Un MP3 válido empieza por ID3 o por una trama de sincronización.
    assert result.data[:3] == b"ID3" or result.data[0] == 0xFF
