# Especificación de aplicación: Generador de audiolibros desde EPUB/PDF

Directorio de trabajo: /home/alejandro/prueba/app-audiolibro
Python del proyecto: .venv/bin/python (ya instalado con dependencias del requirements.txt)
Modelo a usar en opencode: opencode/deepseek-v4.1-flash-free

## Objetivo
Crear una aplicación web (FastAPI) que:
1. Permita seleccionar un archivo EPUB o PDF mediante un navegador de archivos (file browser) del servidor y/o subida de archivo.
2. Extraiga texto del documento (capítulos/páginas).
3. Genere un audiolibro (audio MP3 por capítulo + descarga) usando TTS.
4. Ofrezca una sección de "Registro de servicios" para guardar API keys de proveedores cloud (Azure, AWS, Google, ElevenLabs, OpenAI) y activar/desactivar proveedores.
5. Priorice servicios gratuitos: offline (Piper si está disponible, else gTTS/edge-tts) y cloud sin key (Edge TTS). Proveedores con key opcionales.

## Stack
- Backend: FastAPI (async) + Jinja2 templates o HTML estático servido.
- Frontend: HTML/CSS/JS simple (sin frameworks pesados), responsive.
- Extracción: ebooklib + BeautifulSoup (EPUB); PyMuPDF (PDF).
- TTS proveedores:
  - Edge TTS (edge-tts) sin key (fallback gratuito principal cloud).
  - gTTS (opcional).
  - Piper (offline) opcional: detectar binario `piper` o paquete; si no está, deshabilitar con mensaje.
  - Proveedores con key: Azure Speech, AWS Polly, Google Cloud TTS, ElevenLabs, OpenAI TTS. Implementar adaptadores que usen credenciales de config; si no hay key, marcar no disponible. No es necesario probar con keys reales, pero el código debe estar completo y validar credenciales.
- Audio: pydub + ffmpeg para concatenar/convertir; mutagen para metadatos ID3.
- Almacenamiento: data/ (uploads, outputs, config, cache). No commitear secretos (gitignore).

## Estructura sugerida
app/
  main.py (FastAPI app)
  config.py
  models.py / schemas
  extractors.py (epub, pdf)
  tts/
    base.py
    edge_tts_provider.py
    gtts_provider.py
    piper_provider.py
    azure_provider.py
    aws_provider.py
    google_provider.py
    elevenlabs_provider.py
    openai_provider.py
    router.py
  services/
    credentials.py (cifrado simple o JSON con permisos 600)
    jobs.py (background tasks)
  templates/
    index.html
    browser.html
    register.html
    jobs.html
  static/
    style.css, app.js
tests/
  test_extractors.py
  test_tts_router.py (mock)
README.md

## Funcionalidades UI
- Página principal: estado de proveedores (disponibles/no), formulario para seleccionar archivo (upload o ruta del servidor), selector de voz/idioma/acento, velocidad, formato.
- Navegador de archivos: endpoint GET /api/files?path=... que lista directorios/archivos (restringido a un base path configurable, default home o /home/alejandro), con protección path traversal. UI para navegar y seleccionar.
- Subida de archivo: POST /api/upload (multipart) guarda en data/uploads.
- Generación: POST /api/generate {file_path or upload_id, provider, voice, lang, speed} -> job id; GET /api/jobs/{id} estado; descarga /api/download/{id}.
- Registro: GET/POST /api/credentials para guardar keys por proveedor; mostrar enmascarado; test de conexión opcional (best-effort).
- Proveedores: GET /api/providers.

## Seguridad
- Path traversal protection: normalizar y asegurar dentro de base path.
- No exponer secrets en logs.
- Credenciales en data/credentials.json con permisos 600 (o cifrado con Fernet si cryptography disponible; usar JSON simple acceptable para MVP).
- Validar extensiones (.epub, .pdf).

## Procesamiento
- Extraer texto por capítulos (EPUB spine) o páginas (PDF), limpiar.
- Chunking ~3000 chars por request respetando límites.
- Generar audio por chunk y concatenar con pydub.
- Guardar MP3 final en data/outputs/{job_id}.mp3.
- Metadatos ID3 básicos.

## TTS Router
- Orden por defecto: Piper (si disponible) -> Edge TTS -> (si key) Azure/AWS/etc. Usuario puede elegir.
- Si proveedor no disponible, error claro.

## Tests
- Unit tests para extractores con archivos de ejemplo (crear pequeños EPUB/PDF de prueba).
- Test de path traversal.
- Smoke test de generación con Edge TTS (requiere red) marcado opcional/skip si no hay red.

## Entregables
- Código completo y ejecutable.
- README con instrucciones de instalación/ejecución.
- .gitignore.
- requirements.txt ya existe; actualizar si falta algo (ffmpeg system dep note).

## Notas
- No usar tkinter.
- Mantener simple y robusto.
- Evitar dependencias que no estén instaladas; si falta piper, degradar gracefully.
- Usar .venv/bin/python para ejecutar.

Implementa ahora. Prioriza que la app arranque y genere un audiolibro de prueba con Edge TTS.
