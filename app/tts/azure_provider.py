from __future__ import annotations

import html

from app.tts.base import (
    CREDENTIAL_SCHEMAS,
    SynthesisResult,
    TTSProvider,
    TTSUnavailable,
    Voice,
    http_error,
)

_VOICES = [
    Voice("es-ES-ElviraNeural", "Elvira · España (femenina)", "es-ES", "Female"),
    Voice("es-ES-AlvaroNeural", "Álvaro · España (masculina)", "es-ES", "Male"),
    Voice("es-MX-DaliaNeural", "Dalia · México (femenina)", "es-MX", "Female"),
    Voice("es-MX-JorgeNeural", "Jorge · México (masculina)", "es-MX", "Male"),
    Voice("es-AR-ElenaNeural", "Elena · Argentina (femenina)", "es-AR", "Female"),
    Voice("es-AR-TomasNeural", "Tomás · Argentina (masculina)", "es-AR", "Male"),
    Voice("es-US-PalomaNeural", "Paloma · EE. UU. (femenina)", "es-US", "Female"),
    Voice("en-US-JennyNeural", "Jenny · English US (female)", "en-US", "Female"),
    Voice("en-US-GuyNeural", "Guy · English US (male)", "en-US", "Male"),
]


class AzureTTSProvider(TTSProvider):
    id = "azure"
    label = "Azure Speech"
    description = (
        "Voces neuronales de Azure con capa gratuita F0 (0,5 M caracteres/mes). "
        "Requiere clave y región del recurso Speech."
    )
    requires_key = True
    credential_fields = CREDENTIAL_SCHEMAS["azure"]

    def static_voices(self) -> list[Voice]:
        return list(_VOICES)

    def availability(self) -> tuple[bool, str]:
        values = self.values()
        if not values.get("key") or not values.get("region"):
            return False, "Configura la Subscription key y la región de Azure"
        return True, "Credenciales configuradas"

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import httpx

        values = self._require_configured()
        region = values["region"]
        voice = voice or self.default_voice() or "es-ES-ElviraNeural"
        percent = int(round((speed - 1.0) * 100))
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="{html.escape(lang)}">'
            f'<voice name="{html.escape(voice)}">'
            f'<prosody rate="{percent:+d}%">{html.escape(text)}</prosody>'
            f"</voice></speak>"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": values["key"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "audiolibro-app",
        }
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Azure Speech: error de red: {exc}") from exc
        if response.status_code != 200:
            raise http_error("Azure Speech", response.status_code, response.content)
        if not response.content:
            raise RuntimeError("Azure Speech no devolvió audio")
        return SynthesisResult(data=response.content, format="mp3")

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason
        import httpx

        values = self._require_configured()
        url = f"https://{values['region']}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    url, headers={"Ocp-Apim-Subscription-Key": values["key"]}
                )
        except httpx.HTTPError as exc:
            return False, f"Error de red: {exc}"
        if response.status_code == 200:
            return True, "Conexión con Azure Speech correcta"
        return False, f"Azure respondió HTTP {response.status_code}"
