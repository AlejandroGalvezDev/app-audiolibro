#!/usr/bin/env python
"""Prueba de humo de extremo a extremo: PDF → subida → Edge TTS → MP3.

Uso:
    .venv/bin/python scripts/smoke_test.py
    .venv/bin/python scripts/smoke_test.py --provider edge --output /tmp/demo.mp3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
from fastapi.testclient import TestClient

from app.audio import audio_duration
from app.config import Settings
from app.main import create_app


def build_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "El pequeño libro de prueba")
    page.insert_text(
        (72, 125),
        "Este audiolibro se ha generado automaticamente para comprobar\n"
        "que la extraccion de texto, la sintesis de voz y el ensamblado\n"
        "de audio funcionan de principio a fin.",
    )
    document.save(str(path))
    document.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="edge", help="ID del proveedor TTS")
    parser.add_argument("--voice", default="es-ES-AlvaroNeural")
    parser.add_argument("--lang", default="es-ES")
    parser.add_argument("--output", default="/tmp/audiolibro-smoke.mp3")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    settings = Settings()
    settings.ensure_dirs()
    application = create_app(settings)
    output = Path(args.output).expanduser().resolve()

    with TestClient(application) as client:
        providers = client.get("/api/providers").json()["providers"]
        selected = next((p for p in providers if p["id"] == args.provider), None)
        if selected is None:
            print(f"Proveedor desconocido: {args.provider}", file=sys.stderr)
            return 2
        if not selected["available"]:
            print(
                f"Proveedor {args.provider} no disponible: {selected['reason']}",
                file=sys.stderr,
            )
            return 2

        pdf_path = settings.uploads_dir / "smoke_input.pdf"
        build_pdf(pdf_path)
        print(f"PDF de prueba: {pdf_path}")

        with pdf_path.open("rb") as handle:
            upload = client.post(
                "/api/upload",
                files={"file": ("smoke_input.pdf", handle, "application/pdf")},
            )
        if upload.status_code != 200:
            print(f"Fallo al subir: {upload.status_code} {upload.text}", file=sys.stderr)
            return 1
        uploaded = upload.json()
        print(f"Subido: {uploaded['filename']} ({uploaded['size']} bytes)")

        response = client.post(
            "/api/generate",
            json={
                "upload_id": uploaded["upload_id"],
                "provider": args.provider,
                "voice": args.voice,
                "lang": args.lang,
                "speed": 1.0,
                "format": "mp3",
            },
        )
        if response.status_code != 202:
            print(f"Fallo al generar: {response.status_code} {response.text}", file=sys.stderr)
            return 1
        job_id = response.json()["job_id"]
        print(f"Trabajo: {job_id}")

        deadline = time.time() + args.timeout
        job = None
        last_message = None
        while time.time() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["message"] != last_message:
                print(f"  [{job['progress']:5.1f}%] {job['message']}")
                last_message = job["message"]
            if job["status"] in {"done", "error"}:
                break
            time.sleep(1)
        else:
            print("Tiempo de espera agotado", file=sys.stderr)
            return 1

        if job["status"] != "done":
            print(f"Error: {job['error']}", file=sys.stderr)
            return 1

        audio = client.get(f"/api/download/{job_id}")
        if audio.status_code != 200:
            print(f"Fallo al descargar: {audio.status_code} {audio.text}", file=sys.stderr)
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(audio.content)
        duration = audio_duration(output)
        print(f"OK · {job['chapters'][0]['title']!r}")
        print(f"MP3: {output} ({len(audio.content)} bytes, {duration or '?'} s)")
        print(f"Capítulos: {len(job['chapters'])} · URL: /api/download/{job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
