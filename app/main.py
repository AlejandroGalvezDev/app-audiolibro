from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.audio import ffmpeg_available
from app.config import Settings, load_settings
from app.schemas import (
    CredentialsPayload,
    CredentialsUpdate,
    GenerateRequest,
    ProviderToggle,
)
from app.services.credentials import CredentialError, CredentialStore
from app.services.files import FileAccessError, FileService, safe_filename
from app.services.jobs import JobManager
from app.tts.base import CREDENTIAL_SCHEMAS, TTSUnavailable
from app.tts.router import TTSRouter

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
START_TIME = time.time()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()

    credentials = CredentialStore(settings)
    tts_router = TTSRouter(settings, credentials)
    file_service = FileService(settings)
    job_manager = JobManager(settings, tts_router)

    app = FastAPI(
        title="Audiolibro — EPUB/PDF a MP3",
        description="Generador de audiolibros con TTS local y cloud",
        version=__version__,
    )
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.tts_router = tts_router
    app.state.file_service = file_service
    app.state.job_manager = job_manager

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    def render(request: Request, template: str, active: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "request": request,
                "active": active,
                "app_name": "Audiolibro",
                "version": __version__,
                "settings": settings.public_dict(),
                "ffmpeg": ffmpeg_available(),
                **context,
            },
        )

    # -- páginas -------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return render(request, "index.html", "index")

    @app.get("/browser", response_class=HTMLResponse)
    async def browser_page(request: Request):
        return render(request, "browser.html", "browser")

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        return render(request, "register.html", "register")

    @app.get("/jobs", response_class=HTMLResponse)
    async def jobs_page(request: Request):
        return render(request, "jobs.html", "jobs")

    # -- salud / proveedores -------------------------------------------
    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": round(time.time() - START_TIME, 1),
            "ffmpeg": ffmpeg_available(),
        }

    @app.get("/api/providers")
    async def providers():
        statuses = tts_router.statuses()
        default_provider = next(
            (item["id"] for item in statuses if item["available"]), None
        )
        return {
            "providers": statuses,
            "order": [provider.id for provider in tts_router.ordered_providers()],
            "default_provider": default_provider,
            "ffmpeg": ffmpeg_available(),
            "settings": settings.public_dict(),
        }

    @app.get("/api/providers/{provider_id}/voices")
    async def provider_voices(provider_id: str):
        try:
            voices = await tts_router.voices(provider_id)
        except TTSUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"No se pudieron obtener las voces: {exc}"
            ) from exc
        return {"provider": provider_id, "voices": [voice.to_dict() for voice in voices]}

    # -- archivos ------------------------------------------------------
    @app.get("/api/files")
    async def list_files(path: str | None = Query(default=None)):
        try:
            return file_service.list_directory(path)
        except FileAccessError as exc:
            status = 403 if "Acceso denegado" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)):
        try:
            result = await file_service.save_upload(file)
        except FileAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result.to_dict()

    # -- generación ----------------------------------------------------
    @app.post("/api/generate", status_code=202)
    async def generate(payload: GenerateRequest):
        try:
            source = file_service.resolve_source(payload.file_path, payload.upload_id)
        except FileAccessError as exc:
            status = 403 if "Acceso denegado" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

        try:
            tts_router.resolve(payload.provider)
        except TTSUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        display_name = source.name
        if payload.upload_id and "__" in display_name:
            display_name = display_name.split("__", 1)[1]
        display_name = safe_filename(display_name)
        job = job_manager.create(
            filename=display_name,
            provider=payload.provider,
            voice=payload.voice,
            lang=payload.lang,
            speed=payload.speed,
            audio_format=payload.format,
            path=source,
            title=payload.title,
            chapter_limit=payload.chapter_limit,
        )
        return {"job_id": job.id, "job": job.to_public()}

    @app.get("/api/jobs")
    async def list_jobs():
        return {"jobs": [job.to_public() for job in job_manager.list()]}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        return job.to_public()

    @app.get("/api/download/{job_id}")
    async def download_job(job_id: str):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        path = job_manager.output_path(job)
        if path is None:
            raise HTTPException(
                status_code=409,
                detail=f"El trabajo aún no está listo (estado: {job.status})",
            )
        media_type = "audio/mpeg" if job.format == "mp3" else "audio/wav"
        filename = f"{safe_filename(job.title or 'audiolibro')}.{job.format}"
        return FileResponse(path, media_type=media_type, filename=filename)

    @app.get("/api/download/{job_id}/{chapter_index}")
    async def download_chapter(job_id: str, chapter_index: int):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado")
        path = job_manager.chapter_path(job, chapter_index)
        if path is None:
            raise HTTPException(status_code=404, detail="Capítulo no disponible")
        media_type = "audio/mpeg" if job.format == "mp3" else "audio/wav"
        return FileResponse(
            path,
            media_type=media_type,
            filename=f"capitulo_{chapter_index:03d}.{job.format}",
        )

    # -- credenciales --------------------------------------------------
    def provider_labels() -> dict[str, dict]:
        return {
            pid: {
                "label": provider.label,
                "description": provider.description,
                "requires_key": provider.requires_key,
            }
            for pid, provider in tts_router.providers.items()
        }

    def credentials_overview() -> list[dict]:
        labels = provider_labels()
        overview = credentials.overview()
        for item in overview:
            info = labels.get(item["provider"], {})
            item["label"] = info.get("label", item["provider"])
            item["description"] = info.get("description", "")
            item["requires_key"] = info.get("requires_key", True)
            item["enabled"] = credentials.is_enabled(item["provider"])
        return overview

    @app.post("/api/providers/{provider_id}/enabled")
    async def toggle_provider(provider_id: str, payload: ProviderToggle):
        try:
            provider = tts_router.get(provider_id)
            credentials.set_enabled(provider_id, payload.enabled)
        except CredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TTSUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return provider.status()

    @app.get("/api/credentials")
    async def get_credentials():
        return {
            "providers": credentials_overview(),
            "file": str(credentials.path),
            "env_fallback": True,
        }

    def save_credentials(
        provider: str, values: dict[str, str], enabled: bool | None = None
    ) -> dict:
        try:
            credentials.save(provider, values)
            if enabled is not None:
                credentials.set_enabled(provider, enabled)
        except CredentialError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "provider": provider,
            "configured": credentials.is_configured(provider),
            "enabled": credentials.is_enabled(provider),
            "masked": credentials.masked(provider),
        }

    @app.post("/api/credentials")
    async def post_credentials(payload: CredentialsPayload):
        if not payload.provider:
            raise HTTPException(status_code=422, detail="Falta el proveedor")
        return save_credentials(payload.provider, payload.values, payload.enabled)

    @app.post("/api/credentials/{provider_id}")
    async def post_provider_credentials(provider_id: str, payload: CredentialsUpdate):
        return save_credentials(provider_id, payload.values, payload.enabled)

    @app.delete("/api/credentials/{provider_id}")
    async def delete_credentials(provider_id: str):
        if provider_id not in CREDENTIAL_SCHEMAS:
            raise HTTPException(status_code=404, detail="Proveedor desconocido")
        credentials.clear(provider_id)
        return {"ok": True, "provider": provider_id, "configured": False}

    @app.post("/api/credentials/{provider_id}/test")
    async def test_credentials(provider_id: str):
        try:
            ok, message = await tts_router.test_connection(provider_id)
        except TTSUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"provider": provider_id, "ok": ok, "message": message}

    @app.exception_handler(404)
    async def not_found(_request: Request, exc):
        if _request.url.path.startswith("/api/"):
            detail = getattr(exc, "detail", "No encontrado")
            return JSONResponse(status_code=404, content={"detail": detail})
        return templates.TemplateResponse(
            request=_request,
            name="error.html",
            context={
                "request": _request,
                "active": "",
                "app_name": "Audiolibro",
                "version": __version__,
                "settings": settings.public_dict(),
                "ffmpeg": ffmpeg_available(),
                "code": 404,
                "message": "Página no encontrada",
            },
            status_code=404,
        )

    return app


app = create_app()
