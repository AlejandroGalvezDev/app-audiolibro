# Audiolibro — EPUB/PDF → MP3

Aplicación web local (FastAPI) que convierte documentos EPUB o PDF en audiolibros
MP3 por capítulos, con un explorador de archivos del servidor, subida de archivos,
registro de API keys de proveedores cloud y prioridad a motores gratuitos.

- **Extracción:** EPUB por *spine* (`ebooklib` + BeautifulSoup) y PDF por páginas
  (`PyMuPDF`), con limpieza de texto y división en fragmentos de ~3000 caracteres.
- **TTS gratuito por defecto:** Piper si está instalado → Edge TTS (sin clave,
  requiere Internet) → gTTS.
- **TTS cloud opcional:** Azure Speech, AWS Polly, Google Cloud TTS, ElevenLabs
  y OpenAI TTS. Sin clave se muestran como no disponibles.
- **Audio:** MP3 por capítulo + audiolibro completo, metadatos ID3 (`mutagen`).
- **UI responsive** sin frameworks JS: generar, explorar, trabajos y servicios.

---

## Requisitos

- Python 3.11+ (probado con 3.13).
- Dependencias Python: ver `requirements.txt` (ya instaladas en `.venv`).
- **Internet** para Edge TTS / gTTS y proveedores cloud.
- **ffmpeg (opcional):** necesario para exportar WAV, para Piper y para
  conversiones entre formatos. La generación MP3 con Edge/gTTS/cloud **no** lo
  necesita.
- **Piper (opcional):** binario `piper` + un modelo `.onnx` en `data/models/`
  o ruta en `AUDIOLIBRO_PIPER_MODEL`.

> **Nota sobre pydub:** Python 3.13 eliminó `audioop`, por lo que pydub no se
> puede importar. La app no lo necesita: concatena MP3 de forma nativa y WAV con
> el módulo `wave`. ffmpeg se usa solo cuando está disponible.

---

## Instalación

```bash
cd /home/alejandro/prueba/app-audiolibro

# Dependencias (si hace falta recrear el entorno)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ffmpeg opcional (Debian/Ubuntu)
sudo apt install ffmpeg
```

## Arranque

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre <http://127.0.0.1:8000>.

Variables de entorno útiles:

| Variable | Defecto | Descripción |
|---|---|---|
| `AUDIOLIBRO_BASE_PATH` | `$HOME` | Raíz navegable por el explorador de archivos |
| `AUDIOLIBRO_DATA_DIR` | `./data` | Uploads, outputs, caché y credenciales |
| `AUDIOLIBRO_MAX_UPLOAD_MB` | `100` | Tamaño máximo de subida |
| `AUDIOLIBRO_MAX_TOTAL_CHARS` | `1500000` | Caracteres máximos por documento |
| `AUDIOLIBRO_CHUNK_SIZE` | `3000` | Caracteres por petición TTS |
| `AUDIOLIBRO_MAX_CHAPTERS` | `80` | Capítulos/páginas máximos por trabajo |
| `AUDIOLIBRO_MAX_CONCURRENT_JOBS` | `1` | Trabajos simultáneos |
| `AUDIOLIBRO_PIPER_BINARY` | `piper` | Ruta/nombre del binario Piper |
| `AUDIOLIBRO_PIPER_MODEL` | — | Ruta a un modelo `.onnx` de Piper |

---

## Uso

1. **Generar:** elige *Subir archivo* o *Archivo del servidor* (botón
   **Explorar…**), selecciona proveedor, idioma, acento, voz, velocidad y formato.
2. Pulsa **Generar audiolibro**. El progreso aparece en vivo con el capítulo y
   fragmento actuales.
3. Al terminar puedes descargar el **MP3 completo** o cada **capítulo**.
4. **Servicios:** guarda API keys y prueba la conexión de cada proveedor.
5. **Trabajos:** historial de la sesión (en memoria; se pierde al reiniciar).

### Proveedores y credenciales

| Proveedor | Clave | Campos |
|---|---|---|
| Piper | No | binario + modelo `.onnx` (+ ffmpeg) |
| Edge TTS | No | — |
| gTTS | No | — |
| Azure Speech | Sí | `key`, `region` |
| AWS Polly | Sí | `access_key_id`, `secret_access_key`, `region`, `session_token` opcional |
| Google Cloud TTS | Sí | `api_key` |
| ElevenLabs | Sí | `api_key`, `model_id` opcional |
| OpenAI TTS | Sí | `api_key`, `model` opcional |

Las claves se guardan en `data/credentials.json` con permisos `600` (directorio
`700`) y se muestran enmascaradas. También se aceptan variables de entorno:

```bash
AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_SESSION_TOKEN
GOOGLE_TTS_API_KEY
ELEVENLABS_API_KEY
OPENAI_API_KEY
```

El orden por defecto es **Piper → Edge → gTTS → Azure → AWS → Google →
ElevenLabs → OpenAI**. El selector `auto` usa el primero disponible. Si un
proveedor no tiene clave o binario, la API devuelve un error claro.

---

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado y ffmpeg |
| GET | `/api/providers` | Estado, voces y orden de proveedores |
| GET | `/api/providers/{id}/voices` | Voces dinámicas (Edge/ElevenLabs) |
| GET | `/api/files?path=...` | Lista directorios/archivos dentro del base path |
| POST | `/api/upload` | Multipart `file` (.epub/.pdf) → `upload_id` |
| POST | `/api/generate` | Crea trabajo (`file_path` o `upload_id`) |
| GET | `/api/jobs` | Lista de trabajos |
| GET | `/api/jobs/{id}` | Estado/progreso/capítulos |
| GET | `/api/download/{id}` | MP3 completo |
| GET | `/api/download/{id}/{n}` | Capítulo `n` |
| GET/POST | `/api/credentials` | Consulta/guarda claves |
| POST/DELETE | `/api/credentials/{provider}` | Guarda/borra claves |
| POST | `/api/credentials/{provider}/test` | Test de conexión best-effort |

Ejemplo:

```bash
curl -F "file=@libro.pdf" http://127.0.0.1:8000/api/upload
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"upload_id":"<id>","provider":"edge","voice":"es-ES-AlvaroNeural","lang":"es-ES","speed":1.0,"format":"mp3"}'
curl http://127.0.0.1:8000/api/jobs/<job_id>
curl -OJ http://127.0.0.1:8000/api/download/<job_id>
```

---

## Tests

```bash
.venv/bin/python -m pytest
```

Incluye extracción real de EPUB/PDF, *chunking*, protección path traversal
(incluidos symlinks), credenciales/permisos, router TTS con proveedor simulado y
un test de API completo (subida → generación → descarga).

Test de red real con Edge TTS (opcional):

```bash
RUN_NETWORK_TESTS=1 .venv/bin/python -m pytest tests/test_network_edge.py
```

Smoke test de extremo a extremo con un PDF de ejemplo (requiere Internet para
Edge TTS):

```bash
.venv/bin/python scripts/smoke_test.py --output /tmp/audiolibro-smoke.mp3
```

---

## Estructura

```
app/
  main.py            FastAPI: páginas, API, montaje de estáticos
  config.py          Settings por entorno y directorios
  schemas.py         Modelos Pydantic
  extractors.py      EPUB/PDF, limpieza y chunking
  audio.py           concatenación MP3/WAV, ffmpeg opcional, ID3
  tts/
    base.py          interfaz, voces, esquema de credenciales
    router.py        registro, prioridad y resolución auto
    edge_tts_provider.py, gtts_provider.py, piper_provider.py
    azure_provider.py, aws_provider.py (SigV4), google_provider.py
    elevenlabs_provider.py, openai_provider.py
  services/
    credentials.py   JSON 600 + fallback a variables de entorno
    files.py         navegador restringido + subidas
    jobs.py          gestor de trabajos en memoria
    generator.py     pipeline extracción → TTS → ensamblado
  templates/         index, browser, register, jobs, error
  static/            style.css, app.js
tests/               extractores, rutas, router, audio, API, red
data/                uploads/, outputs/, models/, credentials.json
```

---

## Seguridad

- Todas las rutas del explorador se resuelven con `Path.resolve()` y deben
  quedar dentro de `AUDIOLIBRO_BASE_PATH`; se rechazan `..`, rutas absolutas
  externas y symlinks que escapen de la raíz.
- Solo se aceptan extensiones `.epub` y `.pdf`; los uploads se renombran con un
  UUID y nombre saneado.
- Las claves nunca se devuelven completas ni se escriben en logs; el archivo de
  credenciales se crea con permisos `600`.
- Descargas limitadas a `data/outputs` y a trabajos completados.

---

## Limitaciones conocidas

- Los trabajos viven en memoria y no se reanudan tras reiniciar.
- PDFs escaneados sin capa de texto requieren OCR externo (no incluido).
- Edge TTS es un endpoint no oficial de Microsoft: sin SLA y puede fallar o
  cambiar; la app reintenta y muestra el error.
- Piper requiere ffmpeg y un modelo compatible; si falta, se deshabilita con
  mensaje.
- El formato WAV requiere ffmpeg. Con Edge/gTTS/cloud se genera MP3 directamente.
- El límite de caracteres por petición (3000) respeta los límites habituales de
  los proveedores; los textos largos se dividen por párrafos/frases.
