from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from app.tts.base import (
    CREDENTIAL_SCHEMAS,
    SynthesisResult,
    TTSProvider,
    TTSUnavailable,
    Voice,
    http_error,
)

_VOICES = [
    Voice("Lucia", "Lucia · España (femenina)", "es-ES", "Female"),
    Voice("Sergio", "Sergio · España (masculina)", "es-ES", "Male"),
    Voice("Lupe", "Lupe · EE. UU. (femenina)", "es-US", "Female"),
    Voice("Mia", "Mia · México (femenina)", "es-MX", "Female"),
    Voice("Penelope", "Penélope · EE. UU. (femenina)", "es-US", "Female"),
    Voice("Miguel", "Miguel · EE. UU. (masculino)", "es-US", "Male"),
    Voice("Joanna", "Joanna · English US (female)", "en-US", "Female"),
    Voice("Matthew", "Matthew · English US (male)", "en-US", "Male"),
]

_SERVICE = "polly"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), datestamp.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode(), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _sign_request(
    method: str,
    url: str,
    *,
    region: str,
    access_key: str,
    secret_key: str,
    session_token: str | None,
    body: bytes,
    headers: dict[str, str],
) -> dict[str, str]:
    """AWS Signature Version 4 con la librería estándar."""
    parts = urlsplit(url)
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    canonical_uri = quote(parts.path or "/", safe="/-_.~")
    query_pairs = sorted(parse_qsl(parts.query, keep_blank_values=True))
    canonical_query = urlencode(query_pairs, quote_via=quote, safe="-_.~")

    headers = {key.lower(): value for key, value in headers.items()}
    headers["host"] = parts.netloc
    headers["x-amz-date"] = amz_date
    if session_token:
        headers["x-amz-security-token"] = session_token

    signed_header_names = sorted(headers)
    canonical_headers = "".join(
        f"{name}:{' '.join(headers[name].split())}\n" for name in signed_header_names
    )
    signed_headers = ";".join(signed_header_names)
    payload_hash = _sha256(body)
    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    scope = f"{datestamp}/{region}/{_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical_request.encode())]
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, _SERVICE),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


class AWSPollyProvider(TTSProvider):
    id = "aws"
    label = "AWS Polly"
    description = (
        "Voces neuronales de Amazon Polly con capa gratuita de 5 M "
        "caracteres/mes durante 12 meses. Requiere claves IAM."
    )
    requires_key = True
    credential_fields = CREDENTIAL_SCHEMAS["aws"]

    def static_voices(self) -> list[Voice]:
        return list(_VOICES)

    def availability(self) -> tuple[bool, str]:
        values = self.values()
        if not values.get("access_key_id") or not values.get("secret_access_key"):
            return False, "Configura las claves de acceso de AWS"
        if not values.get("region"):
            return False, "Configura la región de AWS"
        return True, "Credenciales configuradas"

    def _signed_headers(
        self, method: str, url: str, body: bytes, extra: dict[str, str]
    ) -> dict[str, str]:
        values = self._require_configured()
        return _sign_request(
            method,
            url,
            region=values.get("region") or "us-east-1",
            access_key=values["access_key_id"],
            secret_key=values["secret_access_key"],
            session_token=values.get("session_token") or None,
            body=body,
            headers=extra,
        )

    async def synthesize(
        self, text: str, voice: str | None, lang: str, speed: float = 1.0
    ) -> SynthesisResult:
        available, reason = self.availability()
        if not available:
            raise TTSUnavailable(reason)
        import httpx

        values = self.values()
        region = values.get("region") or "us-east-1"
        voice = voice or self.default_voice() or "Lucia"
        percent = int(round((speed - 1.0) * 100))
        ssml = (
            '<speak><prosody rate="'
            f'{percent:+d}%">{escape(text)}</prosody></speak>'
        )
        form = {
            "Text": ssml,
            "TextType": "ssml",
            "OutputFormat": "mp3",
            "VoiceId": voice,
            "Engine": "neural",
        }
        body = urlencode(form).encode()
        url = f"https://polly.{region}.amazonaws.com/v1/speech"
        headers = self._signed_headers(
            "POST",
            url,
            body,
            {
                "content-type": "application/x-www-form-urlencoded",
                "accept": "audio/mpeg",
            },
        )
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"AWS Polly: error de red: {exc}") from exc
        if response.status_code != 200:
            raise http_error("AWS Polly", response.status_code, response.content)
        if not response.content:
            raise RuntimeError("AWS Polly no devolvió audio")
        return SynthesisResult(data=response.content, format="mp3")

    async def test_connection(self) -> tuple[bool, str]:
        available, reason = self.availability()
        if not available:
            return False, reason
        import httpx

        values = self.values()
        region = values.get("region") or "us-east-1"
        url = f"https://polly.{region}.amazonaws.com/v1/voices"
        headers = self._signed_headers("GET", url, b"", {"accept": "application/json"})
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return False, f"Error de red: {exc}"
        if response.status_code == 200:
            return True, "Conexión con AWS Polly correcta"
        if response.status_code == 403:
            return False, "AWS rechazó las credenciales (HTTP 403)"
        return False, f"AWS respondió HTTP {response.status_code}"
