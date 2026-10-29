from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.services.generator import GenerationError, generate_audiobook
from app.tts.base import TTSUnavailable
from app.tts.router import TTSRouter


@dataclass
class Job:
    id: str
    filename: str
    provider: str
    voice: str | None
    lang: str
    speed: float
    format: str
    chapter_limit: int | None = None
    title: str | None = None
    status: str = "queued"
    progress: float = 0.0
    message: str = "En cola"
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    chapters: list[dict] = field(default_factory=list)
    output: str | None = None
    total_chars: int = 0

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "title": self.title or Path(self.filename).stem,
            "provider": self.provider,
            "voice": self.voice,
            "lang": self.lang,
            "speed": self.speed,
            "format": self.format,
            "status": self.status,
            "progress": round(self.progress, 1),
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_chars": self.total_chars,
            "chapters": [
                {
                    **chapter,
                    "download_url": f"/api/download/{self.id}/{chapter['index']}",
                }
                for chapter in self.chapters
            ],
            "download_url": (
                f"/api/download/{self.id}" if self.status == "done" and self.output else None
            ),
        }


class JobManager:
    def __init__(self, settings: Settings, router: TTSRouter) -> None:
        self.settings = settings
        self.router = router
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))

    def create(
        self,
        *,
        filename: str,
        provider: str,
        voice: str | None,
        lang: str,
        speed: float,
        audio_format: str,
        path: Path,
        title: str | None = None,
        chapter_limit: int | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            filename=filename,
            provider=provider,
            voice=voice,
            lang=lang,
            speed=speed,
            format=audio_format,
            title=title,
            chapter_limit=chapter_limit,
        )
        self.jobs[job.id] = job
        self.start(job, path)
        return job

    def start(self, job: Job, path: Path) -> None:
        task = asyncio.create_task(self._run(job, path))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(job.id, None))

    async def _run(self, job: Job, path: Path) -> None:
        async with self.semaphore:
            job.status = "running"
            job.message = "Iniciando generación…"
            job.touch()
            try:
                await generate_audiobook(job, path, self.settings, self.router)
                job.status = "done"
                job.progress = 100.0
            except (GenerationError, TTSUnavailable) as exc:
                job.status = "error"
                job.error = str(exc)
                job.message = str(exc)
            except Exception as exc:  # pragma: no cover - salvaguarda
                job.status = "error"
                job.error = f"Error inesperado: {exc}"
                job.message = job.error
            finally:
                job.touch()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def chapter_path(self, job: Job, index: int) -> Path | None:
        if job.status != "done":
            return None
        chapter = next(
            (item for item in job.chapters if int(item["index"]) == int(index)), None
        )
        if chapter is None:
            return None
        path = (self.settings.outputs_dir / job.id / chapter["filename"]).resolve()
        try:
            path.relative_to(self.settings.outputs_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def output_path(self, job: Job) -> Path | None:
        if job.status != "done" or not job.output:
            return None
        path = Path(job.output).resolve()
        try:
            path.relative_to(self.settings.outputs_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None
