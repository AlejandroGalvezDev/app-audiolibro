from __future__ import annotations

from app.tts.base import (
    CREDENTIAL_SCHEMAS,
    SynthesisResult,
    TTSProvider,
    TTSUnavailable,
    Voice,
    http_error,
)

_VOICES = [
    Voice("alloy", "Alloy (neutra)", "es-ES"),
    Voice("echo", "Echo (masculina)", "es-ES"),
    Voice("fable", "Fable (británica)", "es-ES"),
    Voice("onyx", "Onyx (masculina grave)", "es-ES"),
    Voice("nova", "Nova (femenina)", "es-ES"),
    Voice("shimmer", "Shimmer (femenina)", "es-ES"),
    Voice("coral", "Coral (femenina)", "es-ES"),
    Voice("sage", "Sage (femenina)", "es-ES"),
]


class OpenAITTSProvider(TTSProvider):
    id = "openai"
    label = "OpenAI TTS"
    description = (
        "Modelo TTS de OpenAI (gpt-4o-mini-tts o tts-1). Requiere API key "
        "y tiene coste por uso."
    )
    requires_key = True
    credential_fields = CREDENTIAL_SCHEMAS["openai"]

    def static_voices(self) -> list[Voice]:
        return list(_VOICES)

    def availability(self) -> tuple[bool, str]:
        if not self.values().get("api_key"):
            return False, "Configura la API key de OpenAI"
        return True, "Credenciales configuradas"

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import httpx

        values = self._require_configured()
        voice = voice or "alloy"
        model = values.get("model") or "gpt-4o-mini-tts"
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": max(0.25, min(4.0, speed)),
        }
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={
                        "Authorization": f"Bearer {values['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"OpenAI TTS: error de red: {exc}") from exc
        if response.status_code != 200:
            raise http_error("OpenAI TTS", response.status_code, response.content)
        if not response.content:
            raise RuntimeError("OpenAI TTS no devolvió audio")
        return SynthesisResult(data=response.content, format="mp3")

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason
        import httpx

        values = self._require_configured()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {values['api_key']}"},
                )
        except httpx.HTTPError as exc:
            return False, f"Error de red: {exc}"
        if response.status_code == 200:
            return True, "Conexión con OpenAI correcta"
        return False, f"OpenAI respondió HTTP {response.status_code}"
