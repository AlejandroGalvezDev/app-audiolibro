from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.services.credentials import CredentialError, CredentialStore
from app.tts.base import SynthesisResult, TTSProvider, TTSUnavailable, Voice
from app.tts.edge_tts_provider import EdgeTTSProvider
from app.tts.router import TTSRouter


class FakeProvider(TTSProvider):
    id = "fake"
    label = "Proveedor de prueba"
    description = "Proveedor simulado para tests"
    requires_key = False

    def __init__(self, settings, credentials, available=True):
        super().__init__(settings, credentials)
        self.available = available
        self.calls: list[str] = []

    def availability(self):
        return self.available, "" if self.available else "simulado no disponible"

    def static_voices(self):
        return [Voice("fake-voz", "Voz falsa", "es-ES", "Female")]

    async def synthesize(self, text, voice, lang, speed=1.0):
        self.calls.append(text)
        return SynthesisResult(data=b"FAKE-MP3-" + text.encode("utf-8"), format="mp3")


@pytest.fixture()
def settings(tmp_path):
    settings = Settings(base_path=tmp_path, data_dir=tmp_path / "data")
    settings.ensure_dirs()
    return settings


def test_credentials_save_mask_and_permissions(settings):
    store = CredentialStore(settings)
    assert store.is_configured("openai") is False
    store.save("openai", {"api_key": "sk-proj-1234567890", "model": "tts-1"})
    assert store.is_configured("openai") is True
    assert store.get("openai")["api_key"] == "sk-proj-1234567890"
    masked = store.masked("openai")["api_key"]
    assert masked.endswith("7890")
    assert "123456" not in masked
    assert os.stat(store.path).st_mode & 0o777 == 0o600


def test_credentials_reject_unknown_provider_and_fields(settings):
    store = CredentialStore(settings)
    with pytest.raises(CredentialError):
        store.save("edge", {"api_key": "x"})
    with pytest.raises(CredentialError):
        store.save("openai", {"inventado": "x"})


def test_credentials_env_fallback(settings, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key-abcdef")
    store = CredentialStore(settings)
    assert store.get("openai")["api_key"] == "env-key-abcdef"
    assert store.is_configured("openai") is True


def test_router_auto_selects_first_available(settings):
    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    router.register(FakeProvider(settings, credentials, available=True))
    settings.provider_order = ("fake",)
    provider = router.resolve("auto")
    assert provider.id == "fake"


def test_router_auto_skips_unavailable(settings):
    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    unavailable = FakeProvider(settings, credentials, available=False)
    unavailable.id = "off"
    available = FakeProvider(settings, credentials, available=True)
    router.register(unavailable)
    router.register(available)
    settings.provider_order = ("off", "fake")
    assert router.resolve("auto").id == "fake"


def test_router_respects_unavailable_provider(settings):
    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    fake = FakeProvider(settings, credentials, available=False)
    router.register(fake)
    with pytest.raises(TTSUnavailable, match="no está disponible"):
        router.resolve("fake")


def test_router_unknown_provider(settings):
    router = TTSRouter(settings, CredentialStore(settings))
    with pytest.raises(TTSUnavailable, match="desconocido"):
        router.resolve("no-existe")


def test_router_synthesizes_with_provider(settings):
    import asyncio

    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    fake = FakeProvider(settings, credentials)
    router.register(fake)
    result, provider_id = asyncio.run(
        router.synthesize("fake", "texto corto", None, "es-ES", 1.0)
    )
    assert provider_id == "fake"
    assert result.format == "mp3"
    assert b"texto corto" in result.data
    assert fake.calls == ["texto corto"]


def test_router_rejects_empty_text(settings):
    import asyncio

    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    router.register(FakeProvider(settings, credentials))
    with pytest.raises(ValueError, match="vacío"):
        asyncio.run(router.synthesize("fake", "   ", None, "es-ES"))


def test_edge_provider_availability_and_voices(settings):
    provider = EdgeTTSProvider(settings, CredentialStore(settings))
    available, reason = provider.availability()
    assert available is True, reason
    voices = provider.static_voices()
    assert any(voice.lang.startswith("es-") for voice in voices)
    assert len(voices) >= 5


def test_cloud_providers_have_static_voices(settings):
    from app.tts.azure_provider import AzureTTSProvider
    from app.tts.aws_provider import AWSPollyProvider
    from app.tts.google_provider import GoogleTTSProvider
    from app.tts.openai_provider import OpenAITTSProvider

    credentials = CredentialStore(settings)
    for provider_class in (
        AzureTTSProvider,
        AWSPollyProvider,
        GoogleTTSProvider,
        OpenAITTSProvider,
    ):
        provider = provider_class(settings, credentials)
        voices = provider.static_voices()
        assert voices, provider.id
        assert provider.status()["default_voice"]


def test_provider_enable_disable(settings):
    credentials = CredentialStore(settings)
    router = TTSRouter(settings, credentials)
    fake = FakeProvider(settings, credentials)
    router.register(fake)
    assert credentials.is_enabled("fake") is True
    credentials.set_enabled("fake", False)
    assert credentials.is_enabled("fake") is False
    assert fake.status()["enabled"] is False
    assert fake.status()["available"] is False
    with pytest.raises(TTSUnavailable, match="desactivado"):
        router.resolve("fake")
    credentials.set_enabled("fake", True)
    assert router.resolve("fake").id == "fake"


def test_set_enabled_rejects_invalid_provider(settings):
    credentials = CredentialStore(settings)
    with pytest.raises(CredentialError):
        credentials.set_enabled("../../etc", False)
