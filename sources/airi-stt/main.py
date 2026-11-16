#!/usr/bin/env python3
import os
import sys
import time
import shutil
import logging
import tempfile
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse, JSONResponse

from config import CONFIG

LOG_LEVEL = CONFIG["app"].get("log_level", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("stt-whisper")


def _parse_ip_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_security(request: Request):
    ip = get_client_ip(request)
    allowed = _parse_ip_list(CONFIG["security"].get("allowed_ips"))
    if ip not in allowed:
        logger.warning("Rejected request from IP %s", ip)
        raise HTTPException(status_code=403, detail=f"IP not allowed: {ip}")

    key = request.headers.get("x-api-key") or request.headers.get("airi_stt_api_key")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        key = auth.split(" ", 1)[1].strip()

    expected = CONFIG["security"].get("api_key")
    if not key or key != expected:
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(status_code=403, detail="Invalid API key")


def run_ffmpeg(input_path: Path, output_path: Path, denoise: bool = False):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
    ]
    if denoise:
        cmd += ["-af", "afftdn=nf=-25"]
    cmd += [str(output_path)]

    logger.info("Converting audio with ffmpeg: %s", input_path.name)
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg failed: %s", exc.stderr)
        raise HTTPException(
            status_code=422,
            detail=f"Audio conversion failed: {exc.stderr[:500]}",
        )


def run_whisper(wav_path: Path, language: Optional[str] = None, translate: bool = False) -> str:
    binary = Path(CONFIG["whisper"]["binary_path"])
    model = Path(CONFIG["whisper"]["model_path"])
    threads = int(CONFIG["whisper"].get("threads", 4))
    beam_size = int(CONFIG["whisper"].get("beam_size", 5))

    if not binary.exists():
        logger.error("Whisper binary not found: %s", binary)
        raise HTTPException(status_code=500, detail="Whisper binary not found")
    if not model.exists():
        logger.error("Whisper model not found: %s", model)
        raise HTTPException(status_code=500, detail="Whisper model not found")

    cmd = [
        str(binary),
        "-m", str(model),
        "-f", str(wav_path),
        "-t", str(threads),
        "-bs", str(beam_size),
        "--no-timestamps",
        "--output-txt",
    ]
    if language and language != "auto":
        cmd += ["-l", language]
    if translate:
        cmd += ["-tr"]

    logger.info("Transcribing with whisper.cpp: %s", wav_path.name)
    try:
        env = os.environ.copy()
        libdir = str(binary.parent)
        existing_ld = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = libdir + (":" + existing_ld if existing_ld else "")
        subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        logger.error("whisper.cpp failed: %s", exc.stderr)
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {exc.stderr[:500]}",
        )

    output_file = wav_path.with_suffix(wav_path.suffix + ".txt")
    if not output_file.exists():
        output_file = wav_path.parent / (wav_path.name + ".txt")
    if not output_file.exists():
        logger.error("Whisper output file not found")
        raise HTTPException(status_code=500, detail="Transcription output missing")

    text = output_file.read_text(encoding="utf-8").strip()
    try:
        output_file.unlink()
    except OSError:
        pass
    return text


@asynccontextmanager
async def lifespan(app: FastAPI):
    binary = Path(CONFIG["whisper"]["binary_path"])
    model = Path(CONFIG["whisper"]["model_path"])
    logger.info(
        "STT Whisper starting. binary=%s exists=%s, model=%s exists=%s",
        binary, binary.exists(), model, model.exists(),
    )
    temp_dir = Path(CONFIG["app"]["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("STT Whisper shutting down")


app = FastAPI(
    title="STT Whisper",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(check_security)],
)


@app.middleware("http")
async def size_limit(request: Request, call_next):
    content_length = request.headers.get("content-length")
    max_mb = int(CONFIG["app"].get("max_file_size_mb", 25))
    max_bytes = max_mb * 1024 * 1024
    if content_length and int(content_length) > max_bytes:
        return JSONResponse(
            status_code=413,
            content={"detail": f"File too large. Max {max_mb} MB"},
        )
    return await call_next(request)


@app.get("/health")
async def health(request: Request):
    binary = Path(CONFIG["whisper"]["binary_path"])
    model = Path(CONFIG["whisper"]["model_path"])
    return {
        "status": "ok",
        "model": model.name,
        "model_exists": model.exists(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "whisper_binary": binary.exists(),
        "binary_path": str(binary),
        "model_path": str(model),
        "allowed_ips": _parse_ip_list(CONFIG["security"].get("allowed_ips")),
    }


@app.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    denoise: bool = Form(False),
    translate: bool = Form(False),
):
    start = time.time()
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    model = Path(CONFIG["whisper"]["model_path"])

    temp_dir = Path(tempfile.mkdtemp(prefix="stt-", dir=CONFIG["app"]["temp_dir"]))
    try:
        input_path = temp_dir / file.filename
        with open(input_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        wav_path = temp_dir / "audio.wav"
        run_ffmpeg(input_path, wav_path, denoise=denoise)
        text = run_whisper(wav_path, language=language, translate=translate)

        processing_time_ms = int((time.time() - start) * 1000)
        return {
            "text": text,
            "language": language or "auto",
            "model": model.name,
            "processing_time_ms": processing_time_ms,
            "denoise": denoise,
            "translate": translate,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/transcribe/plain", response_class=PlainTextResponse)
async def transcribe_plain(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    denoise: bool = Form(False),
    translate: bool = Form(False),
):
    result = await transcribe(request, file, language, denoise, translate)
    return result["text"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=CONFIG["app"]["host"],
        port=int(CONFIG["app"]["port"]),
        proxy_headers=True,
    )
