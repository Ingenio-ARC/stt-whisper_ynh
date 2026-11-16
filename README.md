# STT Whisper

App de YunoHost que expone un endpoint de **Speech-to-Text (STT)** usando [whisper.cpp](https://github.com/ggerganov/whisper.cpp).

Ideal para integrar con flujos de N8N: recibe un archivo de audio (MP3, OGG, WAV, etc.), lo convierte a WAV 16 kHz mono, transcribe el audio y devuelve el texto.

## Características

- Motor: `whisper.cpp` (rendimiento nativo en CPU).
- Modelo por defecto: `ggml-base.bin`.
- Seguridad por **whitelist de IPs** + **API key**.
- Límite de archivo: 25 MB (configurable).
- Endpoints JSON y texto plano para facilitar N8N.
- **Métricas de confianza por segmento** (`confidence`, `low_confidence`) para que el flujo de IA sepa cuándo confirmar datos.
- **Prompt inicial configurable** (`initial_prompt`) que sesga vocabulario/formato (p. ej. horarios hablados en español).
- Tests automatizados con métrica WER.
- Reducción de ruido opcional (`?denoise=true`) — Fase 2.

## Endpoints

- `GET /health` — estado del servicio.
- `POST /transcribe` — transcribe audio y devuelve JSON (con métricas de confianza).
- `POST /transcribe/plain` — transcribe audio y devuelve texto plano (sin métricas).

## Respuesta de /transcribe

```json
{
  "text": "Si, decías si puedes eliminar ambas citas del 16, la de las 8 y media y la de las 9.",
  "language": "es",
  "model": "ggml-base.bin",
  "processing_time_ms": 1234,
  "n_segments": 1,
  "duration_s": 6.2,
  "confidence": 0.9262,
  "min_segment_confidence": 0.9262,
  "low_confidence": false,
  "confidence_threshold": 0.6,
  "confidence_available": true,
  "segments": [
    {
      "start_s": 0.0,
      "end_s": 6.2,
      "text": "Si, decías si puedes eliminar ambas citas del 16, ...",
      "confidence": 0.9262,
      "low_confidence": false
    }
  ]
}
```

- `confidence` (0–1): `exp(media(plog))` de los tokens — equivalente al `avg_logprob` de la API de OpenAI, pero como probabilidad. `>= 0.85` buena; `< 0.6` sospechosa (umbral configurable: `confidence_threshold`).
- `low_confidence`: `true` si el confidence global o algún segmento cae bajo el umbral. Es la señal para que el flujo (N8N) le pida al usuario confirmar datos clave.
- `confidence_available` / `confidence` = `null`: el JSON de whisper.cpp no llegó (fallo raro); el texto viene del `.txt` de respaldo.
- Form fields extra: `prompt` (string opcional) sobreescribe el `initial_prompt` del config para esa petición.

## Calidad de la transcripción

Parámetros en `config.yml` (claves nuevas, v1.0~ynh6):

| Clave | Default | Para qué |
|---|---|---|
| `whisper.language` | `auto` | Para audios siempre en un idioma fijo, usa `es`: en clips breves la autodetección falla a veces. |
| `whisper.max_context` | `0` | Sin contexto entre segmentos: evita bucles de repetición/alucinación en audios breves e independientes. |
| `whisper.initial_prompt` | (horarios) | Sesga el formato/vocabulario al inicio de la decodificación: `Horarios de citas: ocho y media, 8:30, nueve y cuarto, 9:15...` |
| `whisper.confidence_threshold` | `0.60` | Debajo de este confidence (global o por segmento) se marca `low_confidence`. |
| `whisper.beam_size` | `5` | Beam search: mejor calidad que greedy (0), a costa de algo más de CPU. |

Calidad del modelo: `base` es rápido pero limitado para español y números hablados. Si el hardware lo permite, `small` (~142 MB) mejora mucho los horarios y nombres: descarga `ggml-small.bin` en `models/`, apunta `whisper.model_path` y reinicia el servicio.

## Instalación en YunoHost

1. Clona o copia este repositorio en `/var/cache/yunohost/from_file/STT-WHISPER_ynh`.
2. Desde la webadmin: **Applications > Installer > Instalar una aplicación personalizada**.
3. Selecciona la carpeta del paquete.
4. Completa los campos:
   - **Dominio**: el mismo dominio donde está Airi.
   - **Path**: `/stt`.
   - **IPs permitidas**: lista separada por comas. Por defecto incluye `127.0.0.1`, `::1` y la IP de debug.
   - **API key**: se genera automáticamente.
   - **Modelo**: `base` por defecto.
   - **Idioma**: `auto` por defecto.
5. Al finalizar la instalación se mostrará la **URL** y la **API key**.

## Configuración

El archivo de configuración editable tras la instalación es:

```bash
/var/www/stt-whisper/config.yml
```

Puedes modificar la whitelist de IPs, la API key, el modelo, los threads, etc.

## Tests

Dentro del servidor YunoHost:

```bash
sudo /var/www/stt-whisper/venv/bin/pytest /var/www/stt-whisper/tests -v
```

O usar el helper:

```bash
sudo bash /var/www/stt-whisper/tests/run_tests.sh
```

## Integración con N8N

Envía el audio desde N8N al endpoint de texto plano:

```http
POST https://<tu-dominio>/stt/transcribe/plain
X-API-KEY: <api-key>
Content-Type: multipart/form-data

file=@audio.ogg
```

La respuesta es el texto transcrito, lista para inyectar en el prompt de la IA.

## Licencia

MIT

## Simulación local (sin YunoHost)

`tests/local_sim/` incluye un harness para probar la app sin Yunohost ni root:

```bash
bash tests/local_sim/sim_install.sh   # instala en ~/../stt-whisper.sim con helpers ynh_* simulados
bash tests/local_sim/sim_e2e.sh       # levanta el microservicio real y prueba /health, /transcribe, /transcribe/plain, 403
```

Los binarios pesados se simulan con stubs (ffmpeg copia el audio, `whisper-cli` falso produce transcript conocido, cmake genera el binario, curl finge el modelo, git finge el clone, venv/pip se simulan). Valida: flujo del script install, render de plantillas (`ynh_add_config`), endpoints, seguridad IP/API key y ciclo de archivos temporales. No valida: compilación real de whisper.cpp (usa build CMake real en el server), inferencia real, systemd/nginx ni resources de Yunohost — esos se prueban con el upgrade real o con package_check/VM de YunoHost.
