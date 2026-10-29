from __future__ import annotations

import asyncio
import importlib.util
import io

from app.tts.base import SynthesisResult, TTSProvider, TTSUnavailable, Voice

_VOICES = [
    Voice("es|com.es", "Español · España", "es-ES"),
    Voice("es|com.mx", "Español · México", "es-MX"),
    Voice("es|com.ar", "Español · Argentina", "es-AR"),
    Voice("es|com.co", "Español · Colombia", "es-CO"),
    Voice("es|com", "Español · EE. UU.", "es-US"),
    Voice("en|com", "English · US", "en-US"),
    Voice("en|co.uk", "English · UK", "en-GB"),
    Voice("fr|fr", "Français", "fr-FR"),
    Voice("de|de", "Deutsch", "de-DE"),
    Voice("pt|com.br", "Português · Brasil", "pt-BR"),
]


class GTTSProvider(TTSProvider):
    id = "gtts"
    label = "gTTS (gratis, sin clave)"
    description = (
        "Google Translate TTS. Una sola voz por idioma y límites no "
        "documentados; útil como alternativa de respaldo."
    )
    requires_key = False

    def availability(self) -> tuple[bool, str]:
        if importlib.util.find_spec("gtts") is None:
            return False, "El paquete gTTS no está instalado"
        return True, "Gratuito, requiere conexión a Internet"

    def static_voices(self) -> list[Voice]:
        return list(_VOICES)

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        from gtts import gTTS

        voice_id = voice or "es|com.es"
        language = voice_id.split("|", 1)[0] if "|" in voice_id else (lang[:2] or "es")
        tld = voice_id.split("|", 1)[1] if "|" in voice_id else "com"
        buffer = io.BytesIO()

        def _synthesize() -> None:
            tts = gTTS(text=text, lang=language, tld=tld, slow=speed < 0.85)
            tts.write_to_fp(buffer)

        try:
            await asyncio.wait_for(asyncio.to_thread(_synthesize), timeout=120)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("gTTS agotó el tiempo de espera") from exc
        except Exception as exc:
            raise RuntimeError(f"gTTS falló: {exc}") from exc
        data = buffer.getvalue()
        if not data:
            raise RuntimeError("gTTS no devolvió audio")
        return SynthesisResult(data=data, format="mp3")
