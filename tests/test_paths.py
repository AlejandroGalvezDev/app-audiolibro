from __future__ import annotations

import pytest

from app.config import Settings
from app.services.files import FileAccessError, FileService


@pytest.fixture()
def file_service(tmp_path):
    base = tmp_path / "library"
    base.mkdir()
    settings = Settings(base_path=base, data_dir=tmp_path / "data")
    settings.ensure_dirs()
    return FileService(settings)


def test_resolve_relative_path_inside_base(file_service, tmp_path):
    book = file_service.base_path / "sub" / "libro.epub"
    book.parent.mkdir()
    book.write_bytes(b"x")
    resolved = file_service.resolve_server_path("sub/libro.epub")
    assert resolved == book.resolve()


def test_resolve_base_root(file_service):
    assert file_service.resolve_server_path(None) == file_service.base_path.resolve()


def test_path_traversal_is_rejected(file_service):
    with pytest.raises(FileAccessError, match="Acceso denegado"):
        file_service.resolve_server_path("../../etc/passwd")


def test_absolute_path_outside_base_is_rejected(file_service):
    with pytest.raises(FileAccessError, match="Acceso denegado"):
        file_service.resolve_server_path("/etc/passwd")


def test_symlink_escape_is_rejected(file_service, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secreto.epub").write_bytes(b"x")
    link = file_service.base_path / "atajo"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks")
    with pytest.raises(FileAccessError, match="Acceso denegado"):
        file_service.resolve_server_path("atajo/secreto.epub")


def test_list_directory_hides_outside_symlinks(file_service, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "externo.pdf").write_bytes(b"x")
    inside = file_service.base_path / "libro.epub"
    inside.write_bytes(b"contenido")
    try:
        (file_service.base_path / "fuera").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks")
    listing = file_service.list_directory(None)
    names = {entry["name"] for entry in listing["entries"]}
    assert "fuera" not in names
    assert "libro.epub" in names
    book = next(entry for entry in listing["entries"] if entry["name"] == "libro.epub")
    assert book["selectable"] is True


def test_upload_id_validation(file_service):
    with pytest.raises(FileAccessError, match="inválido"):
        file_service.resolve_upload("../../etc/passwd")
    with pytest.raises(FileAccessError, match="inválido"):
        file_service.resolve_upload("no-es-un-id")
