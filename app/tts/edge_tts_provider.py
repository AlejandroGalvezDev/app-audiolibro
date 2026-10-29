from __future__ import annotations

import asyncio
import importlib.util
import time

from app.tts.base import SynthesisResult, TTSProvider, TTSUnavailable, Voice

_STATIC_VOICES = [
    Voice("es-ES-AlvaroNeural", "Álvaro · España (masculina)", "es-ES", "Male"),
    Voice("es-ES-ElviraNeural", "Elvira · España (femenina)", "es-ES", "Female"),
    Voice("es-MX-DaliaNeural", "Dalia · México (femenina)", "es-MX", "Female"),
    Voice("es-MX-JorgeNeural", "Jorge · México (masculina)", "es-MX", "Male"),
    Voice("es-AR-ElenaNeural", "Elena · Argentina (femenina)", "es-AR", "Female"),
    Voice("es-AR-TomasNeural", "Tomás · Argentina (masculina)", "es-AR", "Male"),
    Voice("es-CO-SalomeNeural", "Salomé · Colombia (femenina)", "es-CO", "Female"),
    Voice("es-CO-GonzaloNeural", "Gonzalo · Colombia (masculina)", "es-CO", "Male"),
    Voice("es-US-AlonsoNeural", "Alonso · EE. UU. (masculina)", "es-US", "Male"),
    Voice("es-US-PalomaNeural", "Paloma · EE. UU. (femenina)", "es-US", "Female"),
    Voice("en-US-AriaNeural", "Aria · English US (female)", "en-US", "Female"),
    Voice("en-US-GuyNeural", "Guy · English US (male)", "en-US", "Male"),
    Voice("en-GB-SoniaNeural", "Sonia · English UK (female)", "en-GB", "Female"),
    Voice("fr-FR-DeniseNeural", "Denise · Français (female)", "fr-FR", "Female"),
    Voice("de-DE-KatjaNeural", "Katja · Deutsch (female)", "de-DE", "Female"),
]

_cache: dict = {"timestamp": 0.0, "voices": []}
_CACHE_TTL = 3600


class EdgeTTSProvider(TTSProvider):
    id = "edge"
    label = "Edge TTS (gratis, sin clave)"
    description = (
        "Voces neuronales de Microsoft Edge. Gratuito y sin API key, "
        "pero es un servicio no oficial y requiere conexión a Internet."
    )
    requires_key = False

    def availability(self) -> tuple[bool, str]:
        if importlib.util.find_spec("edge_tts") is None:
            return False, "El paquete edge-tts no está instalado"
        return True, "Gratuito, requiere conexión a Internet"

    def static_voices(self) -> list[Voice]:
        if _cache["voices"]:
            return list(_cache["voices"])
        return list(_STATIC_VOICES)

    async def list_voices(self) -> list[Voice]:
        now = time.monotonic()
        if _cache["voices"] and now - _cache["timestamp"] < _CACHE_TTL:
            return list(_cache["voices"])
        try:
            import edge_tts

            raw = await asyncio.wait_for(edge_tts.list_voices(), timeout=20)
            voices = [
                Voice(
                    id=item["ShortName"],
                    label=(
                        f"{item.get('FriendlyName', item['ShortName']).replace('Microsoft ', '').strip()}"
                        f" · {item.get('Locale', '')}"
                    ),
                    lang=item.get("Locale", ""),
                    gender=item.get("Gender", ""),
                )
                for item in raw
                if item.get("ShortName")
            ]
            voices.sort(key=lambda voice: (voice.lang, voice.id))
            if voices:
                _cache.update(timestamp=now, voices=voices)
                return voices
        except Exception:
            pass
        return list(_STATIC_VOICES)

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason
        try:
            import edge_tts

            await asyncio.wait_for(edge_tts.list_voices(), timeout=20)
            return True, "Conexión con Edge TTS correcta"
        except Exception as exc:
            return False, f"No se pudo conectar con Edge TTS: {exc}"

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import edge_tts

        voice = voice or self.default_voice()
        if not voice:
            raise TTSUnavailable("No hay voz configurada para Edge TTS")
        percent = int(round((speed - 1.0) * 100))
        rate = f"{percent:+d}%"
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        buffer = bytearray()
        try:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buffer.extend(chunk["data"])
        except Exception as exc:
            raise RuntimeError(f"Edge TTS falló: {exc}") from exc
        if not buffer:
            raise RuntimeError("Edge TTS no devolvió audio")
        return SynthesisResult(data=bytes(buffer), format="mp3")
