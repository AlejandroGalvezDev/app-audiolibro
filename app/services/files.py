from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.extractors import SUPPORTED_EXTENSIONS

_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class FileAccessError(ValueError):
    pass


@dataclass
class UploadResult:
    upload_id: str
    filename: str
    path: str
    size: int

    def to_dict(self) -> dict:
        return {
            "upload_id": self.upload_id,
            "filename": self.filename,
            "path": self.path,
            "size": self.size,
        }


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def safe_filename(name: str) -> str:
    name = Path(name or "documento").name
    name = _UNSAFE_NAME_RE.sub("_", name).strip(" ._")
    if not name:
        name = "documento"
    stem = Path(name).stem[:100] or "documento"
    suffix = Path(name).suffix.lower()
    return f"{stem}{suffix}"


class FileService:
    """Navegación de archivos restringida a un directorio base."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_path = settings.base_path
        self.uploads_dir = settings.uploads_dir

    # -- rutas ---------------------------------------------------------
    def resolve_server_path(self, raw_path: str | None) -> Path:
        base = self.base_path.resolve()
        if raw_path is None or not str(raw_path).strip() or str(raw_path).strip() == "/":
            return base

        candidate = Path(os.path.expanduser(str(raw_path).strip()))
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise FileAccessError("Ruta de archivo inválida") from exc
        if not _is_within(resolved, base):
            raise FileAccessError(
                "Acceso denegado: la ruta está fuera del directorio permitido "
                f"({base})"
            )
        return resolved

    def relative_label(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.base_path.resolve())
            return "." if str(relative) == "." else str(relative)
        except ValueError:
            return str(path)

    def list_directory(self, raw_path: str | None) -> dict:
        directory = self.resolve_server_path(raw_path)
        if not directory.exists():
            raise FileAccessError(f"El directorio no existe: {directory}")
        if not directory.is_dir():
            raise FileAccessError("La ruta indicada no es un directorio")

        entries = []
        try:
            children = list(directory.iterdir())
        except PermissionError as exc:
            raise FileAccessError("Sin permisos para leer este directorio") from exc

        for child in children:
            try:
                resolved = child.resolve()
                if not _is_within(resolved, self.base_path.resolve()):
                    continue
                is_dir = resolved.is_dir()
                if is_dir:
                    size = 0
                    selectable = False
                elif resolved.is_file():
                    size = resolved.stat().st_size
                    selectable = resolved.suffix.lower() in SUPPORTED_EXTENSIONS
                else:
                    continue
            except (OSError, RuntimeError):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(resolved),
                    "relative": self.relative_label(resolved),
                    "type": "dir" if is_dir else "file",
                    "size": size,
                    "ext": resolved.suffix.lower(),
                    "selectable": selectable,
                    "hidden": child.name.startswith("."),
                }
            )

        entries.sort(key=lambda item: (item["type"] != "dir", item["name"].lower()))
        parent = None
        if directory != self.base_path.resolve():
            parent = str(directory.parent)
        return {
            "base": str(self.base_path.resolve()),
            "path": str(directory),
            "relative": self.relative_label(directory),
            "parent": parent,
            "entries": entries,
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        }

    # -- uploads -------------------------------------------------------
    async def save_upload(self, upload) -> UploadResult:
        filename = safe_filename(upload.filename or "documento")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise FileAccessError("Solo se permiten archivos .epub o .pdf")
        upload_id = uuid.uuid4().hex
        destination = self.uploads_dir / f"{upload_id}__{filename}"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with destination.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileAccessError(
                            f"El archivo supera el límite de {self.settings.max_upload_mb} MB"
                        )
                    handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            try:
                await upload.close()
            except Exception:
                pass
        if size == 0:
            destination.unlink(missing_ok=True)
            raise FileAccessError("El archivo subido está vacío")
        return UploadResult(
            upload_id=upload_id,
            filename=filename,
            path=str(destination),
            size=size,
        )

    def resolve_upload(self, upload_id: str) -> Path:
        upload_id = (upload_id or "").strip().lower()
        if not _UPLOAD_ID_RE.fullmatch(upload_id):
            raise FileAccessError("Identificador de subida inválido")
        matches = list(self.uploads_dir.glob(f"{upload_id}__*"))
        if not matches:
            raise FileAccessError("No se encontró el archivo subido")
        path = matches[0].resolve()
        if not _is_within(path, self.uploads_dir.resolve()):
            raise FileAccessError("Ruta de subida inválida")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise FileAccessError("Extensión de archivo no permitida")
        return path

    def resolve_source(self, file_path: str | None, upload_id: str | None) -> Path:
        if upload_id:
            return self.resolve_upload(upload_id)
        if not file_path:
            raise FileAccessError("Debes indicar un archivo")
        path = self.resolve_server_path(file_path)
        if not path.exists() or not path.is_file():
            raise FileAccessError(f"El archivo no existe: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise FileAccessError("Solo se permiten archivos .epub o .pdf")
        return path
