from __future__ import annotations

import base64

from app.tts.base import (
    CREDENTIAL_SCHEMAS,
    SynthesisResult,
    TTSProvider,
    TTSUnavailable,
    Voice,
    http_error,
)

_VOICES = [
    Voice("es-ES-Neural2-A", "Neural2 A · España (femenina)", "es-ES", "Female"),
    Voice("es-ES-Neural2-B", "Neural2 B · España (masculina)", "es-ES", "Male"),
    Voice("es-ES-Wavenet-C", "Wavenet C · España (femenina)", "es-ES", "Female"),
    Voice("es-US-Neural2-A", "Neural2 A · EE. UU. (femenina)", "es-US", "Female"),
    Voice("es-US-Neural2-B", "Neural2 B · EE. UU. (masculina)", "es-US", "Male"),
    Voice("es-US-Neural2-C", "Neural2 C · EE. UU. (femenina)", "es-US", "Female"),
    Voice("en-US-Neural2-C", "Neural2 C · English US (female)", "en-US", "Female"),
    Voice("en-US-Neural2-D", "Neural2 D · English US (male)", "en-US", "Male"),
]


class GoogleTTSProvider(TTSProvider):
    id = "google"
    label = "Google Cloud TTS"
    description = (
        "Voces Neural2/Wavenet de Google Cloud. Incluye 1 M caracteres "
        "gratuitos al mes en voces estándar. Requiere API key."
    )
    requires_key = True
    credential_fields = CREDENTIAL_SCHEMAS["google"]

    def static_voices(self) -> list[Voice]:
        return list(_VOICES)

    def availability(self) -> tuple[bool, str]:
        if not self.values().get("api_key"):
            return False, "Configura la API key de Google Cloud"
        return True, "Credenciales configuradas"

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import httpx

        values = self._require_configured()
        voice = voice or self.default_voice() or "es-ES-Neural2-A"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": lang, "name": voice},
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": max(0.25, min(4.0, speed)),
            },
        }
        url = "https://texttospeech.googleapis.com/v1/text:synthesize"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    url, params={"key": values["api_key"]}, json=payload
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Google Cloud TTS: error de red: {exc}") from exc
        if response.status_code != 200:
            raise http_error("Google Cloud TTS", response.status_code, response.content)
        try:
            audio = base64.b64decode(response.json()["audioContent"])
        except Exception as exc:
            raise RuntimeError("Google Cloud TTS devolvió una respuesta inesperada") from exc
        if not audio:
            raise RuntimeError("Google Cloud TTS no devolvió audio")
        return SynthesisResult(data=audio, format="mp3")

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason
        import httpx

        values = self._require_configured()
        url = "https://texttospeech.googleapis.com/v1/voices"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, params={"key": values["api_key"]})
        except httpx.HTTPError as exc:
            return False, f"Error de red: {exc}"
        if response.status_code == 200:
            return True, "Conexión con Google Cloud TTS correcta"
        return False, f"Google respondió HTTP {response.status_code}"
