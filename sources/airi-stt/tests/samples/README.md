# Audios de referencia para tests

Coloca aquí audios cortos en español junto a un archivo `.txt` con la transcripción exacta esperada.

Ejemplo:

```text
sample_es_01.mp3
sample_es_01.txt
sample_es_02.ogg
sample_es_02.txt
```

El test `test_quality.py` calculará el **WER** (Word Error Rate) y el **CER** (Character Error Rate) de cada par.

## Generar audios de prueba

Puedes grabarlos directamente o generarlos con herramientas TTS. Ejemplo con `edge-tts`:

```bash
edge-tts --voice es-ES-AlvaroNeural --text "Hola, quiero pedir una cita para mañana." --write-media sample_es_01.mp3
```

Luego escribe la transcripción exacta en `sample_es_01.txt`.
