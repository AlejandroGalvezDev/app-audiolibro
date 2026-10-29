from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


class TTSUnavailable(RuntimeError):
    """El proveedor no está disponible o no está configurado."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    lang: str
    gender: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "lang": self.lang,
            "gender": self.gender,
        }


@dataclass
class SynthesisResult:
    data: bytes
    format: str = "mp3"


# Esquema de credenciales mostrado en la UI y validado por el backend.
CREDENTIAL_SCHEMAS: dict[str, tuple[dict, ...]] = {
    "azure": (
        {
            "name": "key",
            "label": "Subscription key",
            "secret": True,
            "required": True,
            "help": "Clave del recurso Azure Speech.",
        },
        {
            "name": "region",
            "label": "Región",
            "secret": False,
            "required": True,
            "default": "westeurope",
            "help": "Ej.: westeurope, eastus.",
        },
    ),
    "aws": (
        {
            "name": "access_key_id",
            "label": "Access Key ID",
            "secret": True,
            "required": True,
        },
        {
            "name": "secret_access_key",
            "label": "Secret Access Key",
            "secret": True,
            "required": True,
        },
        {
            "name": "region",
            "label": "Región",
            "secret": False,
            "required": True,
            "default": "us-east-1",
        },
        {
            "name": "session_token",
            "label": "Session token (opcional)",
            "secret": True,
            "required": False,
        },
    ),
    "google": (
        {
            "name": "api_key",
            "label": "API key",
            "secret": True,
            "required": True,
        },
    ),
    "elevenlabs": (
        {
            "name": "api_key",
            "label": "API key",
            "secret": True,
            "required": True,
        },
        {
            "name": "model_id",
            "label": "Modelo",
            "secret": False,
            "required": False,
            "default": "eleven_multilingual_v2",
        },
    ),
    "openai": (
        {
            "name": "api_key",
            "label": "API key",
            "secret": True,
            "required": True,
        },
        {
            "name": "model",
            "label": "Modelo",
            "secret": False,
            "required": False,
            "default": "gpt-4o-mini-tts",
        },
    ),
}


class TTSProvider(ABC):
    id: str = ""
    label: str = ""
    description: str = ""
    requires_key: bool = False

    def __init__(self, settings: Settings, credentials) -> None:
        self.settings = settings
        self.credentials = credentials

    # -- configuración -------------------------------------------------
    def values(self) -> dict[str, str]:
        return self.credentials.get(self.id)

    def masked_credentials(self) -> dict[str, str]:
        return self.credentials.masked(self.id)

    def is_configured(self) -> bool:
        fields = CREDENTIAL_SCHEMAS.get(self.id, ())
        values = self.values()
        return all(values.get(item["name"]) for item in fields if item.get("required"))

    def is_enabled(self) -> bool:
        return self.credentials.is_enabled(self.id)

    def availability(self) -> tuple[bool, str]:
        return True, ""

    def effective_availability(self) -> tuple[bool, str]:
        if not self.is_enabled():
            return False, "Proveedor desactivado en el registro de servicios"
        return self.availability()

    def status(self) -> dict:
        intrinsic_available, intrinsic_reason = self.availability()
        available, reason = self.effective_availability()
        voices = self.static_voices()
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "requires_key": self.requires_key,
            "enabled": self.is_enabled(),
            "available": available,
            "intrinsic_available": intrinsic_available,
            "reason": reason if not available else intrinsic_reason,
            "configured": self.is_configured() if self.requires_key else True,
            "credentials": self.masked_credentials(),
            "voices": [voice.to_dict() for voice in voices],
            "default_voice": voices[0].id if voices else None,
        }

    # -- voces y síntesis ----------------------------------------------
    def static_voices(self) -> list[Voice]:
        return []

    async def list_voices(self) -> list[Voice]:
        return self.static_voices()

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason or "Proveedor no disponible"
        return True, "Disponible"

    @abstractmethod
    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        raise NotImplementedError

    # -- utilidades ----------------------------------------------------
    def default_voice(self) -> str | None:
        voices = self.static_voices()
        return voices[0].id if voices else None

    def _require_configured(self) -> dict[str, str]:
        values = self.values()
        missing = [
            item["label"]
            for item in CREDENTIAL_SCHEMAS.get(self.id, ())
            if item.get("required") and not values.get(item["name"])
        ]
        if missing:
            raise TTSUnavailable(
                f"Faltan credenciales de {self.label}: {', '.join(missing)}. "
                "Configúralas en «Registro de servicios»."
            )
        return values


def http_error(provider: str, status_code: int, body: bytes | str) -> RuntimeError:
    """Mensaje de error sin exponer credenciales."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    text = " ".join(text.split())[:300]
    return RuntimeError(f"{provider} respondió HTTP {status_code}: {text or 'sin detalle'}")
