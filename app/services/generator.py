from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from app.audio import (
    AudioError,
    audio_duration,
    concat_audio,
    convert_audio,
    ffmpeg_available,
    write_audio,
)
from app.config import Settings
from app.extractors import ExtractionError, chunk_text, extract_document
from app.tts.base import TTSUnavailable
from app.tts.router import TTSRouter

if TYPE_CHECKING:
    from app.services.jobs import Job


class GenerationError(RuntimeError):
    pass


def _update(job: "Job", progress: float | None = None, message: str | None = None) -> None:
    if progress is not None:
        job.progress = max(job.progress, min(99.0, progress))
    if message is not None:
        job.message = message
    job.touch()


async def _synthesize_with_retry(
    router: TTSRouter,
    job: "Job",
    text: str,
    voice: str | None,
    attempts: int = 3,
):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await router.synthesize(
                job.provider, text, voice, job.lang, job.speed
            )
        except TTSUnavailable:
            raise
        except Exception as exc:  # errores de red / límites de cuota
            last_error = exc
            if attempt >= attempts:
                break
            job.message = (
                f"Reintentando ({attempt}/{attempts - 1}) tras error: {str(exc)[:160]}"
            )
            job.touch()
            await asyncio.sleep(1.5 * attempt)
    raise GenerationError(f"La síntesis falló tras {attempts} intentos: {last_error}")


async def generate_audiobook(
    job: "Job",
    source_path: Path,
    settings: Settings,
    router: TTSRouter,
) -> None:
    """Extrae, sintetiza y ensambla el audiolibro, actualizando el job."""
    if job.format == "wav" and not ffmpeg_available():
        raise GenerationError(
            "El formato WAV requiere ffmpeg instalado en el sistema. "
            "Genera en MP3 o instala ffmpeg."
        )

    provider = router.resolve(job.provider)
    job.provider = provider.id
    voice = job.voice or provider.default_voice()

    _update(job, progress=2, message="Extrayendo texto del documento…")
    try:
        chapters = await asyncio.to_thread(
            extract_document, source_path, settings.max_chapters
        )
    except ExtractionError as exc:
        raise GenerationError(str(exc)) from exc

    if job.chapter_limit:
        chapters = chapters[: job.chapter_limit]
    if not chapters:
        raise GenerationError("El documento no contiene capítulos con texto")

    total_chars = sum(len(chapter.text) for chapter in chapters)
    if total_chars > settings.max_total_chars:
        raise GenerationError(
            f"El documento contiene {total_chars} caracteres y el límite es "
            f"{settings.max_total_chars}. Reduce el número de capítulos "
            "(chapter_limit) o aumenta AUDIOLIBRO_MAX_TOTAL_CHARS."
        )
    job.total_chars = total_chars
    title = job.title
    if not title:
        title = Path(job.filename).stem[:200]
        job.title = title

    job_dir = settings.outputs_dir / job.id
    job_dir.mkdir(parents=True, exist_ok=True)

    total = len(chapters)
    chapter_files: list[Path] = []
    _update(job, progress=3, message=f"{total} capítulo(s), {total_chars} caracteres")

    for position, chapter in enumerate(chapters):
        chunks = chunk_text(chapter.text, settings.chunk_size)
        if not chunks:
            continue
        parts: list[bytes] = []
        chunk_format = "mp3"
        for chunk_index, chunk in enumerate(chunks):
            fraction = (position + (chunk_index / len(chunks))) / total
            _update(
                job,
                progress=3 + 82 * fraction,
                message=(
                    f"Capítulo {position + 1}/{total}: fragmento "
                    f"{chunk_index + 1}/{len(chunks)}"
                ),
            )
            result, _provider_id = await _synthesize_with_retry(
                router, job, chunk, voice
            )
            parts.append(result.data)
            chunk_format = result.format

        data = concat_audio(parts, chunk_format)
        if chunk_format != job.format:
            data = await asyncio.to_thread(
                convert_audio, data, chunk_format, job.format
            )
        filename = f"chapter_{position + 1:03d}.{job.format}"
        destination = job_dir / filename
        write_audio(
            destination,
            data,
            job.format,
            title=f"{title} — {chapter.title}",
            album=title,
            track=position + 1,
            comment=f"Generado con {provider.label}",
        )
        chapter_files.append(destination)
        job.chapters.append(
            {
                "index": position + 1,
                "title": chapter.title,
                "filename": filename,
                "chars": len(chapter.text),
                "duration": audio_duration(destination),
            }
        )
        _update(
            job,
            progress=3 + 85 * ((position + 1) / total),
            message=f"Capítulo {position + 1}/{total} completado",
        )

    if not chapter_files:
        raise GenerationError("No se generó ningún capítulo de audio")

    _update(job, progress=92, message="Ensamblando audiolibro completo…")
    combined_parts = [path.read_bytes() for path in chapter_files]
    combined = concat_audio(combined_parts, job.format)
    output_path = settings.outputs_dir / f"{job.id}.{job.format}"
    write_audio(
        output_path,
        combined,
        job.format,
        title=title,
        album=title,
        comment=f"Audiolibro generado con {provider.label}",
    )
    job.output = str(output_path)
    job.progress = 100.0
    job.touch()
    job.message = (
        f"Audiolibro listo: {len(chapter_files)} capítulo(s), "
        f"{total_chars} caracteres"
    )
