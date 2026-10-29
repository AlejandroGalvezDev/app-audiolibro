from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.config import Settings
from app.tts.base import CREDENTIAL_SCHEMAS


class CredentialError(ValueError):
    pass


# Variables de entorno aceptadas como alternativa al registro en la UI.
ENV_FALLBACK: dict[str, dict[str, tuple[str, ...]]] = {
    "azure": {
        "key": ("AZURE_SPEECH_KEY", "AZURE_TTS_KEY"),
        "region": ("AZURE_SPEECH_REGION",),
    },
    "aws": {
        "access_key_id": ("AWS_ACCESS_KEY_ID",),
        "secret_access_key": ("AWS_SECRET_ACCESS_KEY",),
        "region": ("AWS_REGION", "AWS_DEFAULT_REGION"),
        "session_token": ("AWS_SESSION_TOKEN",),
    },
    "google": {"api_key": ("GOOGLE_TTS_API_KEY", "GOOGLE_API_KEY")},
    "elevenlabs": {
        "api_key": ("ELEVENLABS_API_KEY",),
        "model_id": ("ELEVENLABS_MODEL_ID",),
    },
    "openai": {
        "api_key": ("OPENAI_API_KEY",),
        "model": ("OPENAI_TTS_MODEL",),
    },
}


class CredentialStore:
    """Guarda credenciales en data/credentials.json con permisos 600.

    Los valores nunca se registran en logs ni se devuelven completos por la API.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings.credentials_file or settings.data_dir / "credentials.json")

    # -- persistencia --------------------------------------------------
    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialError(
                "No se pudo leer data/credentials.json. Revisa su formato JSON."
            ) from exc
        providers = data.get("providers") if isinstance(data, dict) else None
        return providers if isinstance(providers, dict) else {}

    def _write(self, providers: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "providers": providers}
        fd, temporary = tempfile.mkstemp(
            prefix=".credentials-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- lectura -------------------------------------------------------
    def get(self, provider: str) -> dict[str, str]:
        stored = self._read().get(provider, {})
        stored = stored if isinstance(stored, dict) else {}
        values: dict[str, str] = {}
        for field in CREDENTIAL_SCHEMAS.get(provider, ()):
            name = field["name"]
            value = stored.get(name)
            if not value:
                for env_name in ENV_FALLBACK.get(provider, {}).get(name, ()):
                    value = os.getenv(env_name)
                    if value:
                        break
            if value:
                values[name] = str(value)
            elif field.get("default"):
                values[name] = str(field["default"])
        return values

    def is_configured(self, provider: str) -> bool:
        fields = CREDENTIAL_SCHEMAS.get(provider, ())
        if not fields:
            return False
        values = self.get(provider)
        return all(values.get(field["name"]) for field in fields if field.get("required"))

    def is_enabled(self, provider: str) -> bool:
        entry = self._read().get(provider)
        if isinstance(entry, dict) and "enabled" in entry:
            return bool(entry["enabled"])
        return True

    def set_enabled(self, provider: str, enabled: bool) -> None:
        if not provider or not re.fullmatch(r"[a-z0-9_-]{2,32}", provider):
            raise CredentialError(f"Proveedor desconocido: {provider}")
        providers = self._read()
        current = providers.get(provider, {})
        current = current if isinstance(current, dict) else {}
        current["enabled"] = bool(enabled)
        providers[provider] = current
        self._write(providers)

    def masked(self, provider: str) -> dict[str, str]:
        values = self.get(provider)
        masked: dict[str, str] = {}
        for field in CREDENTIAL_SCHEMAS.get(provider, ()):
            value = values.get(field["name"], "")
            if not value:
                masked[field["name"]] = ""
            elif field.get("secret"):
                masked[field["name"]] = "••••••••" + value[-4:]
            else:
                masked[field["name"]] = value
        return masked

    def overview(self) -> list[dict]:
        result = []
        for provider, fields in CREDENTIAL_SCHEMAS.items():
            result.append(
                {
                    "provider": provider,
                    "configured": self.is_configured(provider),
                    "fields": [
                        {
                            "name": field["name"],
                            "label": field["label"],
                            "secret": bool(field.get("secret")),
                            "required": bool(field.get("required")),
                            "default": field.get("default", ""),
                            "help": field.get("help", ""),
                            "masked": self.masked(provider).get(field["name"], ""),
                        }
                        for field in fields
                    ],
                }
            )
        return result

    # -- escritura -----------------------------------------------------
    def save(self, provider: str, values: dict[str, str]) -> None:
        if provider not in CREDENTIAL_SCHEMAS:
            raise CredentialError(f"El proveedor «{provider}» no admite credenciales")
        allowed = {field["name"] for field in CREDENTIAL_SCHEMAS[provider]}
        unknown = set(values) - allowed
        if unknown:
            raise CredentialError(
                f"Campos desconocidos para {provider}: {', '.join(sorted(unknown))}"
            )

        providers = self._read()
        current = providers.get(provider, {})
        current = current if isinstance(current, dict) else {}
        for name, raw in values.items():
            value = (raw or "").strip()
            if not value:
                continue
            if value.startswith("••"):
                continue
            current[name] = value
        providers[provider] = current
        self._write(providers)

    def clear(self, provider: str) -> None:
        providers = self._read()
        providers.pop(provider, None)
        self._write(providers)
