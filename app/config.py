from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PROVIDER_ORDER = (
    "piper",
    "edge",
    "gtts",
    "azure",
    "aws",
    "google",
    "elevenlabs",
    "openai",
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_base_path() -> Path:
    raw = os.getenv("AUDIOLIBRO_BASE_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.home()


def _default_data_dir() -> Path:
    raw = os.getenv("AUDIOLIBRO_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return PROJECT_ROOT / "data"


@dataclass
class Settings:
    """Configuración de la aplicación (sobrescribible por variables de entorno)."""

    base_path: Path = field(default_factory=_default_base_path)
    data_dir: Path = field(default_factory=_default_data_dir)
    chunk_size: int = field(default_factory=lambda: _env_int("AUDIOLIBRO_CHUNK_SIZE", 3000))
    max_chapters: int = field(default_factory=lambda: _env_int("AUDIOLIBRO_MAX_CHAPTERS", 80))
    max_upload_mb: int = field(default_factory=lambda: _env_int("AUDIOLIBRO_MAX_UPLOAD_MB", 100))
    max_total_chars: int = field(
        default_factory=lambda: _env_int("AUDIOLIBRO_MAX_TOTAL_CHARS", 1_500_000)
    )
    max_concurrent_jobs: int = field(
        default_factory=lambda: _env_int("AUDIOLIBRO_MAX_CONCURRENT_JOBS", 1)
    )
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    piper_binary: str = field(default_factory=lambda: os.getenv("AUDIOLIBRO_PIPER_BINARY", "piper"))
    piper_model: str | None = field(
        default_factory=lambda: os.getenv("AUDIOLIBRO_PIPER_MODEL") or None
    )
    credentials_file: Path | None = None

    def __post_init__(self) -> None:
        self.base_path = Path(self.base_path).expanduser().resolve()
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        if self.credentials_file is None:
            self.credentials_file = self.data_dir / "credentials.json"
        else:
            self.credentials_file = Path(self.credentials_file).expanduser().resolve()

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.uploads_dir, self.outputs_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.data_dir,
            self.uploads_dir,
            self.outputs_dir,
            self.cache_dir,
        ):
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass

    def public_dict(self) -> dict:
        return {
            "base_path": str(self.base_path),
            "max_upload_mb": self.max_upload_mb,
            "max_total_chars": self.max_total_chars,
            "max_chapters": self.max_chapters,
            "chunk_size": self.chunk_size,
            "provider_order": list(self.provider_order),
        }


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
