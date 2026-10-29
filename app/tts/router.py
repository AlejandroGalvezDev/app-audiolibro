from __future__ import annotations

from app.config import Settings
from app.tts.aws_provider import AWSPollyProvider
from app.tts.azure_provider import AzureTTSProvider
from app.tts.base import SynthesisResult, TTSProvider, TTSUnavailable, Voice
from app.tts.edge_tts_provider import EdgeTTSProvider
from app.tts.elevenlabs_provider import ElevenLabsProvider
from app.tts.google_provider import GoogleTTSProvider
from app.tts.gtts_provider import GTTSProvider
from app.tts.openai_provider import OpenAITTSProvider
from app.tts.piper_provider import PiperProvider


class TTSRouter:
    """Registro y selección de proveedores TTS."""

    def __init__(self, settings: Settings, credentials) -> None:
        self.settings = settings
        self.credentials = credentials
        self.providers: dict[str, TTSProvider] = {}
        for provider_class in (
            PiperProvider,
            EdgeTTSProvider,
            GTTSProvider,
            AzureTTSProvider,
            AWSPollyProvider,
            GoogleTTSProvider,
            ElevenLabsProvider,
            OpenAITTSProvider,
        ):
            provider = provider_class(settings, credentials)
            self.providers[provider.id] = provider

    # -- registro ------------------------------------------------------
    def register(self, provider: TTSProvider) -> None:
        self.providers[provider.id] = provider

    def ordered_providers(self) -> list[TTSProvider]:
        order = list(self.settings.provider_order)
        ordered = [self.providers[pid] for pid in order if pid in self.providers]
        ordered.extend(p for pid, p in self.providers.items() if pid not in order)
        return ordered

    def get(self, provider_id: str) -> TTSProvider:
        provider = self.providers.get(provider_id)
        if provider is None:
            available = ", ".join(self.providers) or "ninguno"
            raise TTSUnavailable(
                f"Proveedor desconocido: {provider_id}. Disponibles: {available}"
            )
        return provider

    def resolve(self, provider_id: str | None) -> TTSProvider:
        if provider_id and provider_id != "auto":
            provider = self.get(provider_id)
            available, reason = provider.effective_availability()
            if not available:
                raise TTSUnavailable(
                    f"El proveedor «{provider.label}» no está disponible: "
                    f"{reason or 'sin detalle'}"
                )
            return provider

        for provider in self.ordered_providers():
            available, _reason = provider.effective_availability()
            if available:
                return provider
        raise TTSUnavailable(
            "No hay ningún proveedor TTS disponible. Configura Edge TTS, "
            "instala Piper o añade credenciales cloud."
        )

    # -- información ---------------------------------------------------
    def statuses(self) -> list[dict]:
        return [provider.status() for provider in self.ordered_providers()]

    async def voices(self, provider_id: str) -> list[Voice]:
        provider = self.get(provider_id)
        return await provider.list_voices()

    async def test_connection(self, provider_id: str) -> tuple[bool, str]:
        provider = self.get(provider_id)
        return await provider.test_connection()

    # -- síntesis ------------------------------------------------------
    async def synthesize(
        self,
        provider_id: str | None,
        text: str,
        voice: str | None,
        lang: str,
        speed: float = 1.0,
    ) -> tuple[SynthesisResult, str]:
        if not text.strip():
            raise ValueError("El texto para sintetizar está vacío")
        provider = self.resolve(provider_id)
        result = await provider.synthesize(text, voice, lang, speed)
        if not result.data:
            raise RuntimeError(f"{provider.label} devolvió audio vacío")
        return result, provider.id
