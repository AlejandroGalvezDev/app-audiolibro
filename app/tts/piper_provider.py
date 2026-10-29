from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from app.audio import AudioError, convert_audio
from app.tts.base import SynthesisResult, TTSProvider, TTSUnavailable, Voice


class PiperProvider(TTSProvider):
    id = "piper"
    label = "Piper (offline)"
    description = (
        "TTS neuronal local. Requiere el binario `piper`, un modelo .onnx "
        "y ffmpeg para exportar MP3. Sin coste ni Internet."
    )
    requires_key = False

    def _binary(self) -> str | None:
        configured = self.settings.piper_binary
        if configured and Path(configured).exists():
            return configured
        return shutil.which(configured or "piper")

    def _models(self) -> list[Path]:
        models: list[Path] = []
        if self.settings.piper_model:
            path = Path(self.settings.piper_model).expanduser()
            if path.is_file():
                models.append(path)
        models_dir = self.settings.data_dir / "models"
        if models_dir.is_dir():
            models.extend(sorted(models_dir.glob("*.onnx")))
        unique: list[Path] = []
        for model in models:
            if model not in unique:
                unique.append(model)
        return unique

    def availability(self) -> tuple[bool, str]:
        if not self._binary():
            return False, (
                "Binario `piper` no encontrado. Instálalo o define "
                "AUDIOLIBRO_PIPER_BINARY."
            )
        if not self._models():
            return False, (
                "No hay modelos Piper. Coloca un .onnx en data/models o define "
                "AUDIOLIBRO_PIPER_MODEL."
            )
        if not shutil.which("ffmpeg"):
            return False, "Piper requiere ffmpeg para convertir WAV a MP3"
        return True, "Motor local disponible"

    def static_voices(self) -> list[Voice]:
        voices = []
        for model in self._models():
            voices.append(
                Voice(
                    id=str(model),
                    label=f"Piper · {model.stem}",
                    lang="es-ES" if "es" in model.stem.lower() else "",
                )
            )
        return voices

    def default_voice(self) -> str | None:
        models = self._models()
        return str(models[0]) if models else None

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        return available, reason or "Motor local disponible"

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        binary = self._binary()
        model = Path(voice).expanduser() if voice else None
        if model is None or not model.is_file():
            model = self._models()[0]
        if not binary:
            raise TTSUnavailable("Binario piper no disponible")

        length_scale = max(0.5, min(2.0, 1.0 / max(speed, 0.1)))
        with tempfile.TemporaryDirectory(prefix="piper-") as tmp:
            wav_path = Path(tmp) / "out.wav"
            command = [
                binary,
                "--model",
                str(model),
                "--output_file",
                str(wav_path),
                "--length_scale",
                f"{length_scale:.2f}",
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(text.encode("utf-8")), timeout=600
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError("Piper agotó el tiempo de espera") from exc
            except OSError as exc:
                raise RuntimeError(f"No se pudo ejecutar piper: {exc}") from exc
            if process.returncode != 0 or not wav_path.exists():
                detail = stderr.decode("utf-8", errors="replace").strip()[:300]
                raise RuntimeError(f"Piper falló: {detail or 'sin detalle'}")
            wav_data = wav_path.read_bytes()
        try:
            mp3_data = await asyncio.to_thread(convert_audio, wav_data, "wav", "mp3")
        except AudioError as exc:
            raise RuntimeError(str(exc)) from exc
        return SynthesisResult(data=mp3_data, format="mp3")
