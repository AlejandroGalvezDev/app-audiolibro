"""Utilidades de audio sin dependencia obligatoria de ffmpeg.

En Python 3.13 `pydub` deja de importarse porque `audioop` fue eliminado.
Por eso la concatenación de MP3 se hace de forma nativa (los MP3 de los
proveedores TTS son tramas contiguas) y la de WAV con el módulo `wave`.
Si `ffmpeg` está disponible se usa para conversiones/remux y para Piper.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from pathlib import Path


class AudioError(RuntimeError):
    pass


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


def _strip_id3(data: bytes) -> bytes:
    """Elimina una etiqueta ID3v2 inicial (se reescribe al final del proceso)."""
    if len(data) < 10 or data[:3] != b"ID3":
        return data
    size_bytes = data[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        return data
    size = (
        (size_bytes[0] << 21)
        | (size_bytes[1] << 14)
        | (size_bytes[2] << 7)
        | size_bytes[3]
    )
    footer = 10 if data[5] & 0x10 else 0
    end = 10 + size + footer
    return data[end:] if 0 < end <= len(data) else data


def _concat_mp3(parts: list[bytes]) -> bytes:
    return b"".join(_strip_id3(part) for part in parts)


def _concat_wav(parts: list[bytes]) -> bytes:
    if not parts:
        return b""
    params = None
    frames: list[bytes] = []
    for part in parts:
        with wave.open(io.BytesIO(part), "rb") as wav:
            current = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
            if params is None:
                params = current
            elif current != params:
                raise AudioError(
                    "No se pueden concatenar WAV con parámetros distintos "
                    f"({current} != {params})"
                )
            frames.append(wav.readframes(wav.getnframes()))
    if params is None:
        return b""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(params[0])
        out.setsampwidth(params[1])
        out.setframerate(params[2])
        out.writeframes(b"".join(frames))
    return buffer.getvalue()


def concat_audio(parts: list[bytes], fmt: str) -> bytes:
    if not parts:
        raise AudioError("No hay fragmentos de audio para concatenar")
    if fmt == "mp3":
        return _concat_mp3(parts)
    if fmt == "wav":
        return _concat_wav(parts)
    raise AudioError(f"Formato de audio no soportado: {fmt}")


def convert_audio(data: bytes, src_format: str, dst_format: str) -> bytes:
    if src_format == dst_format:
        return data
    binary = ffmpeg_path()
    if not binary:
        raise AudioError(
            f"Se necesita ffmpeg para convertir {src_format} a {dst_format}. "
            "Instala ffmpeg en el sistema o genera en formato "
            f"{src_format}."
        )
    if src_format == "mp3":
        input_args = ["-f", "mp3", "-i", "pipe:0"]
    elif src_format == "wav":
        input_args = ["-f", "wav", "-i", "pipe:0"]
    else:
        raise AudioError(f"Formato de origen no soportado: {src_format}")

    if dst_format == "mp3":
        output_args = ["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"]
    elif dst_format == "wav":
        output_args = ["-c:a", "pcm_s16le", "-f", "wav", "pipe:1"]
    else:
        raise AudioError(f"Formato de destino no soportado: {dst_format}")

    command = [binary, "-hide_banner", "-loglevel", "error", "-y", *input_args, *output_args]
    try:
        completed = subprocess.run(command, input=data, capture_output=True, check=False)
    except OSError as exc:
        raise AudioError(f"No se pudo ejecutar ffmpeg: {exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:400]
        raise AudioError(f"ffmpeg falló al convertir audio: {detail or 'error desconocido'}")
    return completed.stdout


def _tag_mp3(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    track: int | None = None,
    comment: str | None = None,
) -> None:
    try:
        from mutagen.id3 import COMM, TALB, TCON, TIT2, TPE1, TRCK, ID3
    except ImportError:  # pragma: no cover
        return
    try:
        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        tags.add(TALB(encoding=3, text=album))
        tags.add(TCON(encoding=3, text="Audiobook"))
        if track is not None:
            tags.add(TRCK(encoding=3, text=str(track)))
        if comment:
            tags.add(COMM(encoding=3, lang="spa", desc="", text=comment))
        tags.save(str(path))
    except Exception:
        # Los metadatos son best-effort; el audio ya está escrito.
        pass


def write_audio(
    path: Path,
    data: bytes,
    fmt: str,
    *,
    title: str,
    artist: str = "Audiolibro",
    album: str = "Generado con Audiolibro",
    track: int | None = None,
    comment: str | None = None,
) -> None:
    if not data:
        raise AudioError("El audio generado está vacío")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    if fmt == "mp3":
        _tag_mp3(
            path,
            title=title,
            artist=artist,
            album=album,
            track=track,
            comment=comment,
        )


def audio_duration(path: Path) -> float | None:
    """Duración aproximada en segundos (best-effort, sin ffprobe)."""
    try:
        from mutagen.mp3 import MP3

        return round(float(MP3(str(path)).info.length), 2)
    except Exception:
        return None
