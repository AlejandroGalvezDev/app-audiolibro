from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GenerateRequest(BaseModel):
    file_path: str | None = Field(
        default=None, description="Ruta absoluta o relativa al base path del servidor"
    )
    upload_id: str | None = Field(default=None, description="ID devuelto por /api/upload")
    provider: str = Field(default="auto", description="ID de proveedor TTS o 'auto'")
    voice: str | None = Field(default=None, description="ID de voz del proveedor")
    lang: str = Field(default="es-ES", min_length=2, max_length=20)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    format: Literal["mp3", "wav"] = "mp3"
    chapter_limit: int | None = Field(default=None, ge=1, le=500)
    title: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_source(self) -> "GenerateRequest":
        if not self.file_path and not self.upload_id:
            raise ValueError("Debes indicar file_path o upload_id")
        if self.file_path and self.upload_id:
            raise ValueError("Indica solo file_path o upload_id, no ambos")
        return self


class CredentialsPayload(BaseModel):
    provider: str | None = None
    values: dict[str, str] = Field(default_factory=dict)
    enabled: bool | None = None


class CredentialsUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    enabled: bool | None = None


class ProviderToggle(BaseModel):
    enabled: bool
