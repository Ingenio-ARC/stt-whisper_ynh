# STT Whisper

App de YunoHost que expone un endpoint de **Speech-to-Text (STT)** usando [whisper.cpp](https://github.com/ggerganov/whisper.cpp).

Ideal para integrar con flujos de N8N: recibe un archivo de audio (MP3, OGG, WAV, etc.), lo convierte a WAV 16 kHz mono, transcribe el audio y devuelve el texto.

## Características

- Motor: `whisper.cpp` (rendimiento nativo en CPU).
- Modelo por defecto: `ggml-base.bin`.
- Seguridad por **whitelist de IPs** + **API key**.
- Límite de archivo: 25 MB (configurable).
- Endpoints JSON y texto plano para facilitar N8N.
- Tests automatizados con métrica WER.
- Reducción de ruido opcional (`?denoise=true`) — Fase 2.

## Endpoints

- `GET /health` — estado del servicio.
- `POST /transcribe` — transcribe audio y devuelve JSON.
- `POST /transcribe/plain` — transcribe audio y devuelve texto plano.

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
