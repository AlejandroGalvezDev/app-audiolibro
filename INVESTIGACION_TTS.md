# INVESTIGACIÓN TTS — Generación de audiolibros en español

**Entorno objetivo:** Linux / Raspberry Pi (ARM, CPU, sin GPU garantizada), Python 3.13, sin GUI de escritorio garantizada.  
**Idioma principal:** español (Castellano y variantes LATAM).  
**Objetivo:** app que extrae texto de EPUB/PDF y genera audiolibros, prefiriendo servicios gratuitos.

---

## 1. Resumen ejecutivo

- **Motor offline principal recomendado:** **Piper** (Apache-2.0, C++/ONNX, tiempo real en Pi 4, voces es_ES y es_MX; alta calidad para narración).  
- **Mejor calidad offline open-source (si hay RAM/CPU):** **Kokoro** (Apache-2.0, 82M params, español incluido, muy rápido) o **MeloTTS** (MIT, español, CPU real-time). **Chatterbox** (MIT, 23 idiomas incl. español, calidad cercana a ElevenLabs) pero pesado para Pi.  
- **Mejor fallback cloud gratuito sin API key:** **Edge TTS** (Microsoft, no oficial, sin cuota documentada, 400+ voces/100+ idiomas, español con voces neurales). Riesgo: inestabilidad/bloqueos; no recomendado para uso comercial crítico.  
- **Mejor cloud freemium con API key y uso comercial claro:** **Azure Speech (F0)** 0.5M chars/mes neural (o 2M en cuentas PAYG dentro de cuota) o **AWS Polly** 5M chars/mes Standard (12 meses).  
- **NO recomendado para audiolibros serios:** espeak-ng/pyttsx3 (calidad robótica), gTTS (límites no documentados, licencia ambigua), XTTS v2 (CPML no comercial).  
- **Framework de app:** **FastAPI (o Flask) + HTML/JS** servido en `0.0.0.0`, accesible desde navegador de cualquier dispositivo de la LAN. Evitar tkinter (requiere X11) y Streamlit/Gradio como núcleo (útiles para prototipo, no para app de producción).

---

## 2. Técnicas locales (offline)

### 2.1 pyttsx3 (+ espeak-ng)
- **Tipo:** wrapper Python sobre motor del SO (SAPI5/macOS NSSpeechSynthesizer/espeak-ng en Linux).  
- **Calidad ES:** baja (voz robótica, MOS <3.0).  
- **Idiomas:** los que tenga instalado espeak-ng (español incluido).  
- **Licencia:** MIT (pyttsx3); espeak-ng GPL-3.  
- **HW:** muy bajo; corre en Pi Zero.  
- **Caveats:** en Linux headless falla si no hay dispositivo de audio (ALSA/PulseAudio); `pyttsx3.init()` lanza `RuntimeError`. No ideal para servidor.  
- **Uso:** prototipos, accesibilidad básica.

### 2.2 espeak-ng (directo)
- **Tipo:** sintetizador clásico por formantes.  
- **Calidad ES:** baja-media, voz metálica.  
- **Idiomas:** 100+ (incl. es).  
- **Licencia:** GPL-3.  
- **HW:** mínimo (CPU, <10 MB).  
- **Uso:** fallback de emergencia, dispositivos muy limitados.

### 2.3 Piper
- **Tipo:** VITS neural, ONNX, C++.  
- **Calidad ES:** buena (MOS ~3.5+), voces es_ES (davefx, carlfm, etc.), es_MX (claude), es_AR (daniela). Tiers x_low/low/medium/high (16/22.05 kHz, 10–100 MB).  
- **Idiomas:** 35+ (es, fr, de, it, pt, en, etc.).  
- **Licencia:** MIT (código) + voces: la mayoría MIT/Apache; algunas "personal/non-commercial" (verificar voices.json).  
- **HW:** tiempo real en Pi 4 (ARM64/ARMv7), sin GPU, ~30–60 MB por voz.  
- **Caveats:** calidad depende del corpus de la voz; sin clonación.  
- **Uso:** **motor offline por defecto para la app.**

### 2.4 Kokoro
- **Tipo:** StyleTTS2 + ISTFTNet, 82M params.  
- **Calidad ES:** alta (1º en HuggingFace TTS Arena single-speaker), bien ritmado; variantes calidad según voz.  
- **Idiomas:** en, ja, zh, fr, it, pt, es, hi (8–9).  
- **Licencia:** Apache-2.0 (comercial OK).  
- **HW:** muy rápido en GPU (~100x real-time, ~1.5 GB VRAM); en CPU Pi es viable pero más lento que Piper; ~300 MB modelo.  
- **Caveats:** calidad variable en no-inglés; mejor con textos largos.  
- **Uso:** calidad alta en máquinas con algo de RAM/CPU o GPU.

### 2.5 MeloTTS
- **Tipo:** VITS multilingüe.  
- **Calidad ES:** buena, natural.  
- **Idiomas:** en (US/UK/IN/AU), es, fr, zh, ja, ko.  
- **Licencia:** MIT (comercial OK).  
- **HW:** CPU real-time, ~0.5 GB RAM opcional GPU; modelo ~250 MB.  
- **Uso:** alternativa ligera a Kokoro con licencia MIT clara.

### 2.6 Chatterbox (Resemble AI)
- **Tipo:** TTS neural multilingüe (23 idiomas), zero-shot voice cloning.  
- **Calidad ES:** muy alta, cercana a ElevenLabs; soporta control de emoción.  
- **Idiomas:** 23 incl. es.  
- **Licencia:** MIT (comercial OK).  
- **HW:** requiere GPU para tiempo real razonable; probado en Python 3.11/Debian; en Pi CPU será lento.  
- **Uso:** servidores con GPU o generación batch no urgente; no ideal para Pi.

### 2.7 Coqui TTS / XTTS v2
- **Tipo:** clonación de voz con 6 s de audio de referencia.  
- **Calidad ES:** alta.  
- **Idiomas:** 17 incl. es.  
- **Licencia:** **Coqui Public Model License (CPML) — solo no comercial** (personal, investigación, evaluación).  
- **HW:** GPU recomendada (mid-range).  
- **Uso:** solo proyectos personales/no comerciales; **no apto para app comercial.**

### 2.8 Otros locales (referencia)
- **Pico TTS (svox):** español, calidad media-baja, muy ligero.  
- **Festival:** español, calidad media, antiguo.  
- **Kitten TTS / Pocket TTS:** emerging, ligeros, inglés principalmente.

---

## 3. Servicios cloud gratuitos / freemium

### 3.1 Edge TTS (Microsoft, no oficial)
- **Librería:** `edge-tts` (Python).  
- **Calidad ES:** alta (voces neurales Microsoft: es-ES-AlvaroNeural, es-MX-DaliaNeural, etc.).  
- **Límites:** sin cuota documentada ("ilimitado"), 400+ voces / 100+ idiomas.  
- **API key/registro:** **No**.  
- **Comercial:** **No recomendado** — endpoint interno de Edge reverse-engineered; MS puede bloquear; sin SSML avanzado; sin SLA.  
- **Uso:** fallback gratuito excelente para uso personal/no crítico.

### 3.2 gTTS (Google Translate TTS)
- **Librería:** `gTTS`.  
- **Calidad ES:** media (una voz por idioma).  
- **Límites:** no documentados; ~decenas de miles de chars/hora por IP antes de HTTP 429.  
- **API key/registro:** No.  
- **Comercial:** **ambiguo** (endpoint no documentado de Google Translate; licencia de audio no clara).  
- **Uso:** prototipos rápidos; no producción.

### 3.3 Google Cloud Text-to-Speech
- **Calidad ES:** alta (WaveNet/Neural2/Chirp3).  
- **Free tier:** 4M chars/mes Standard; 1M chars/mes WaveNet/Neural2/Studio; 1000 req/min.  
- **API key/registro:** **Sí** (cuenta GCP + API key / service account).  
- **Comercial:** sí (licencia explícita).  
- **Caveats:** requiere tarjeta para activar (aunque no se cobra dentro de cuota); facturación pay-as-you-go.

### 3.4 Azure AI Speech (F0)
- **Calidad ES:** alta (neural, voces es-ES/latam).  
- **Free tier:** 0.5M chars/mes neural en F0; en PAYG se mantienen 2M chars/mes gratis permanentes.  
- **API key/registro:** **Sí** (recurso Azure + key + región).  
- **Comercial:** sí.  
- **Caveats:** sin SLA en free; throttling al exceder.

### 3.5 AWS Polly
- **Calidad ES:** buena-alta (Standard/Neural/Long-Form/Generative).  
- **Free tier:** 5M chars/mes Standard; 1M Neural; 500k Long-Form; 100k Generative — **primeros 12 meses**. Desde jul-2025, nuevos clientes reciben hasta $200 créditos.  
- **API key/registro:** **Sí** (cuenta AWS + IAM).  
- **Comercial:** sí.  
- **Caveats:** expira a los 12 meses; después $4/1M Standard, $16/1M Neural.

### 3.6 ElevenLabs
- **Calidad ES:** muy alta (Multilingual v2, 29 idiomas incl. es_ES/es_MX).  
- **Free tier:** 10k chars/mes (~10 min audio).  
- **API key/registro:** **Sí**.  
- **Comercial:** **No en free** (solo personal con atribución); comercial desde Starter ($6/mes).  
- **Uso:** pruebas/calidad premium; no viable para audiolibros largos en free.

### 3.7 OpenAI TTS
- **Calidad ES:** alta (tts-1, tts-1-hd, gpt-4o-mini-tts), pero voces en español solo en planes pagos según proveedores; sin free tier.  
- **Free tier:** **ninguno** (facturación desde el primer carácter: $15/1M chars tts-1).  
- **API key/registro:** sí (cuenta OpenAI con saldo).  
- **Uso:** no recomendado para "gratis".

### 3.8 ResponsiveVoice
- **Calidad ES:** media (in-page playback).  
- **Free tier:** 1M chars/mes en un sitio; comercial incluido en free según pricing (pero TOS: free no comercial con atribución en algunos productos).  
- **API key/registro:** sí (código del sitio).  
- **Comercial:** confuso (free "feature limited for commercial"); licencia CC-BY-NC-ND para non-commercial.  
- **Uso:** reproducción en página, no generación de archivos de audiolibro.

### 3.9 Otros (referencia)
- **Narakeet, FreeTTS, TTS.ai:** gratuitos en web, sin API clara o con límites; útiles para pruebas manuales.  
- **Fish Audio / Chatterbox cloud:** alta calidad, free tier limitado.

---

## 4. Recomendación final

### 4.1 Mejor combinación gratuita para audiolibros en español
1. **Offline por defecto:** **Piper** (es_ES/es_MX/es_AR según disponibilidad) para generación local ilimitada y privada.  
2. **Calidad superior offline (si hardware permite):** **Kokoro** o **MeloTTS** como segunda opción (Apache-2.0/MIT, comercial OK).  
3. **Fallback cloud sin key (personal/no crítico):** **Edge TTS**.  
4. **Fallback cloud con calidad/SLA (comercial):** **Azure Speech F0** o **AWS Polly** (Standard) dentro de cuota gratuita.  
5. **Premium opcional (pago):** ElevenLabs (Starter) si se requiere máxima naturalidad comercial.

### 4.2 Arquitectura sugerida (offline-first con fallback cloud)
```
[UI Web] -> [API FastAPI]
   -> Extractor (ebooklib/bs4 para EPUB; PyMuPDF para PDF)
   -> Normalizador de texto (limpieza, capítulos, chunks ~2000-4000 chars)
   -> TTS Router:
        1) Piper (offline)  [preferido]
        2) Kokoro/MeloTTS (offline, calidad)
        3) Edge TTS (cloud sin key) [fallback gratuito]
        4) Azure/AWS (cloud con key) [fallback comercial]
   -> Ensamblador de audio (pydub/ffmpeg) -> MP3/M4A por capítulo
   -> Almacenamiento local + descarga
```
- **Chunking:** dividir por párrafos/capítulos para evitar límites por petición (Edge/Azure ~5k–10k chars).  
- **Caché:** guardar audio por hash de texto para no regenerar.  
- **Cola:** procesamiento asíncrono (Celery/RQ o BackgroundTasks) para libros largos.  
- **Configuración de voces:** selector de idioma/acento (es-ES, es-MX, es-AR) y velocidad.  
- **Registro de servicios:** módulo de credenciales (API keys) cifradas localmente; el usuario activa/desactiva proveedores.

### 4.3 Servicios que requieren registro / API key (para sección de registro de la app)
| Servicio | Registro/API key | Notas |
|---|---|---|
| Piper / Kokoro / MeloTTS / Chatterbox | No | Offline; solo descarga de modelos. |
| Edge TTS | No | Sin key; dependencia de red. |
| gTTS | No | Sin key; límites no documentados. |
| Google Cloud TTS | Sí (GCP) | Service account / API key; tarjeta. |
| Azure Speech | Sí (Azure) | Key + región. |
| AWS Polly | Sí (AWS) | IAM access key + secret. |
| ElevenLabs | Sí | API key. |
| OpenAI TTS | Sí | API key con saldo. |
| ResponsiveVoice | Sí (código sitio) | Más playback que generación. |

---

## 5. Extracción de texto

### 5.1 EPUB
- **Librerías:** `ebooklib` + `beautifulsoup4` (lxml).  
- **Patrón:** `epub.read_epub()` → iterar `book.get_items_of_type(ITEM_DOCUMENT)` o `book.spine` en orden de lectura → `BeautifulSoup(content, 'html.parser')` → `get_text()`.  
- **Ventajas:** orden de lectura real (spine), limpieza de scripts/styles/nav, soporte de headings.  
- **Alternativas:** `epub2txt`, `pandoc` (CLI).  
- **Pitfalls:** EPUB con DRM, encodings, imágenes con texto (requiere OCR).

### 5.2 PDF
| Librería | Velocidad | Precisión | Tablas | Deps | Uso recomendado |
|---|---|---|---|---|---|
| **PyMuPDF (fitz/pymupdf)** | Más rápida (~0.003–0.01 s/pág) | Alta (67.8%) | 100/100 | C (MuPDF) | **Principal** |
| **pdfplumber** | Media (~0.10 s/pág) | Media | 100/100 | pdfminer.six | Tablas/posicionamiento |
| **pypdf** | Rápida (~0.024 s/pág) | Alta (67.8%) | 0/100 | Pure Python | Sin deps C, manipulación PDF |
| **pdfminer.six** | Lenta (~0.05 s/pág) | Baja-media (20.4%) | 0/100 | Pure Python | Más estable, layout detallado |

- **Recomendación:** PyMuPDF como principal; pdfplumber para PDFs con tablas; pypdf como fallback sin compilación; OCR (pytesseract/easyocr) para PDFs escaneados.

---

## 6. Framework de app

| Opción | Pros | Contras | Recomendación |
|---|---|---|---|
| **FastAPI/Flask + HTML/JS** | Sin GUI local; accesible por red; estándar; fácil integrar TTS; lightweight en Pi | Requiere escribir frontend | **Recomendado** como núcleo |
| **tkinter** | Nativo Python | Requiere X11/display; no apto headless; UX pobre | No (solo si hay desktop) |
| **Gradio** | Rápido para prototipo ML; UI automática | Pesado; menos control; no ideal producción | Prototipado |
| **Streamlit** | Muy rápido para dashboards | Requiere `streamlit run`; reruns; no ideal para app con estado/cola | Prototipado/análisis |

**Decisión:** app web con **FastAPI** (async, ideal para TTS I/O) + frontend HTML/JS simple (o Jinja2), servida en `0.0.0.0:8000`, accesible desde navegador de cualquier dispositivo en la LAN del Pi. Gradio/Streamlit pueden usarse para prototipos rápidos pero no como base final.

---

## 7. Tabla comparativa general de TTS

| Solución | Tipo | Calidad ES | Offline | Licencia / Comercial | HW / Coste | Límite gratuito | API key |
|---|---|---|---|---|---|---|---|
| espeak-ng/pyttsx3 | Local | Baja | Sí | GPL-3 / MIT | Mínimo | Ilimitado | No |
| Piper | Local | Buena | Sí | MIT (verificar voz) | Pi 4 real-time | Ilimitado | No |
| Kokoro | Local | Alta | Sí | Apache-2.0 | CPU/GPU | Ilimitado | No |
| MeloTTS | Local | Buena | Sí | MIT | CPU real-time | Ilimitado | No |
| Chatterbox | Local | Muy alta | Sí | MIT | GPU recomendado | Ilimitado | No |
| XTTS v2 | Local | Alta | Sí | CPML (no comercial) | GPU | Ilimitado (no comercial) | No |
| Edge TTS | Cloud | Alta | No | No oficial (no comercial) | Red | Sin cuota doc. | No |
| gTTS | Cloud | Media | No | Ambiguo | Red | No documentado | No |
| Google Cloud TTS | Cloud | Alta | No | Comercial | Red | 4M/1M chars/mes | Sí |
| Azure Speech | Cloud | Alta | No | Comercial | Red | 0.5M chars/mes (F0) | Sí |
| AWS Polly | Cloud | Buena-Alta | No | Comercial | Red | 5M/1M chars/mes (12 m) | Sí |
| ElevenLabs | Cloud | Muy alta | No | Comercial (pago) | Red | 10k chars/mes | Sí |
| OpenAI TTS | Cloud | Alta | No | Comercial (pago) | Red | Sin free tier | Sí |
| ResponsiveVoice | Cloud | Media | No | Confuso | Red | 1M chars/mes (1 sitio) | Sí |

---

## 8. Notas de implementación

- **Normalización de texto:** expandir abreviaturas, números, siglas; manejar saltos de línea y guiones de separación de sílabas.  
- **Puntuación:** insertar pausas (SSML `<break>`) donde el motor lo soporte (Piper soporta SSML básico; Edge/Azure/AWS completos).  
- **Formato de salida:** WAV intermedio → MP3 (128–192 kbps) con `ffmpeg`/`pydub`; capítulos separados + concatenación opcional.  
- **Metadatos:** añadir ID3 (título, autor, capítulo) con `mutagen`.  
- **Pruebas:** validar en Pi real (ARM64) antes de elegir modelo final; medir RAM/tiempo por 10k chars.  
- **Legal:** respetar licencias (CPML no comercial); para distribución comercial usar Piper/Kokoro/MeloTTS/Chatterbox o servicios con licencia comercial.

---

*Fuentes: documentación oficial y comparativas públicas (2025–2026). Verificar precios/cuotas vigentes antes de despliegue.*
</home/alejandro/prueba/app-audiolibro/INVESTIGACION_TTS.md