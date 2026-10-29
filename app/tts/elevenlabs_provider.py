from __future__ import annotations

from app.tts.base import (
    CREDENTIAL_SCHEMAS,
    SynthesisResult,
    TTSProvider,
    TTSUnavailable,
    Voice,
    http_error,
)

_STATIC_VOICES = [
    Voice("21m00Tcm4TlvDq8ikWAM", "Rachel · multilingüe (femenina)", "es-ES", "Female"),
    Voice("pNInz6obpgDQGcFmaJgB", "Adam · multilingüe (masculina)", "es-ES", "Male"),
    Voice("EXAVITQu4vr4xnSDxMaL", "Sarah · multilingüe (femenina)", "es-ES", "Female"),
    Voice("onwK4e9ZLuTAKqWW03F9", "Daniel · multilingüe (masculina)", "es-ES", "Male"),
]


class ElevenLabsProvider(TTSProvider):
    id = "elevenlabs"
    label = "ElevenLabs"
    description = (
        "Voces de alta calidad con clonación opcional. Requiere API key; "
        "la cuota gratuita es limitada."
    )
    requires_key = True
    credential_fields = CREDENTIAL_SCHEMAS["elevenlabs"]

    def availability(self) -> tuple[bool, str]:
        if not self.values().get("api_key"):
            return False, "Configura la API key de ElevenLabs"
        return True, "Credenciales configuradas"

    def static_voices(self) -> list[Voice]:
        return list(_STATIC_VOICES)

    async def list_voices(self) -> list[Voice]:
        values = self.values()
        if not values.get("api_key"):
            return self.static_voices()
        import httpx

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": values["api_key"]},
                )
            if response.status_code == 200:
                voices = [
                    Voice(
                        id=item["voice_id"],
                        label=item.get("name", item["voice_id"]),
                        lang=(item.get("labels", {}) or {}).get("language", "es-ES"),
                        gender=(item.get("labels", {}) or {}).get("gender", ""),
                    )
                    for item in response.json().get("voices", [])
                ]
                if voices:
                    return voices
        except Exception:
            pass
        return self.static_voices()

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import httpx

        values = self._require_configured()
        voice = voice or self.default_voice() or "21m00Tcm4TlvDq8ikWAM"
        model = values.get("model_id") or "eleven_multilingual_v2"
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "speed": max(0.7, min(1.2, speed)),
            },
        }
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    url,
                    params={"output_format": "mp3_44100_128"},
                    headers={
                        "xi-api-key": values["api_key"],
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs: error de red: {exc}") from exc
        if response.status_code != 200:
            raise http_error("ElevenLabs", response.status_code, response.content)
        if not response.content:
            raise RuntimeError("ElevenLabs no devolvió audio")
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
                    "https://api.elevenlabs.io/v1/user",
                    headers={"xi-api-key": values["api_key"]},
                )
        except httpx.HTTPError as exc:
            return False, f"Error de red: {exc}"
        if response.status_code == 200:
            return True, "Conexión con ElevenLabs correcta"
        return False, f"ElevenLabs respondió HTTP {response.status_code}"
