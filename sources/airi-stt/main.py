#!/usr/bin/env python3
import os
import sys
import time
import math
import json
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


def _segment_span_ms(offsets) -> tuple:
    """offsets de whisper.cpp: en versiones recientes es un dict {from, to};
    en otras es una lista [from, to] en ms."""
    if isinstance(offsets, dict):
        try:
            return float(offsets.get("from") or 0), float(offsets.get("to") or 0)
        except (TypeError, ValueError):
            return 0.0, 0.0
    try:
        if isinstance(offsets, (list, tuple)) and len(offsets) >= 2:
            return float(offsets[0] or 0), float(offsets[1] or 0)
    except (TypeError, ValueError):
        pass
    return 0.0, 0.0


def _token_plogs(tokens) -> list:
    """Log-probabilidades por token.

    whisper.cpp >=1.7.x expone 'p' (probabilidad); 'plog' solo en algunas
    versiones/modos. Derivamos: plog = log(p), confianza = exp(mean(plog))
    = media geometrica de las probabilidades de token.
    """
    out = []
    for t in tokens:
        if not isinstance(t, dict):
            continue
        pl = t.get("plog")
        if isinstance(pl, (int, float)):
            out.append(pl)
            continue
        p = t.get("p")
        if isinstance(p, (int, float)) and p > 0:
            out.append(math.log(p))
    return out


def _exp_mean_plog(plogs: list) -> Optional[float]:
    """Probabilidad media geometrica (0-1) de una lista de log-probabilidades."""
    vals = [p for p in plogs if isinstance(p, (int, float))]
    if not vals:
        return None
    try:
        return math.exp(sum(vals) / len(vals))
    except (ValueError, OverflowError):
        return None


def _parse_whisper_json(json_path: Path, threshold: float) -> dict:
    """Lee el JSON completo de whisper.cpp (-ojf) y calcula metricas de confianza.

    whisper.cpp expone por token: p (probabilidad) y plog (log-probabilidad).
    confidence = exp(mean(plog))  [equivalente al avg_logprob de la API OpenAI].
    """
    result = {
        "text": "",
        "segments": [],
        "confidence": None,
        "min_segment_confidence": None,
        "low_confidence": None,
        "n_segments": None,
        "duration_s": None,
        "confidence_available": False,
    }
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return result

    segments = data.get("transcription") or []
    all_plogs = []
    seg_rows = []
    end_ms = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            seg_text = str(seg.get("text", "")).strip()
            seg_start_ms, seg_end_ms = _segment_span_ms(seg.get("offsets"))
            end_ms = max(end_ms, seg_end_ms)
            plogs = _token_plogs(seg.get("tokens") or [])
            all_plogs.extend(plogs)
            conf = _exp_mean_plog(plogs)
            seg_rows.append({
                "start_s": round(seg_start_ms / 1000.0, 3),
                "end_s": round(seg_end_ms / 1000.0, 3),
                "text": seg_text,
                "confidence": round(conf, 4) if conf is not None else None,
                "low_confidence": (conf < threshold) if conf is not None else None,
            })
        except Exception:
            logger.warning(
                "Segmento STT no parseable, se omite: %s", type(seg).__name__,
                exc_info=True,
            )

    result["confidence_available"] = True
    result["segments"] = seg_rows
    result["n_segments"] = len(seg_rows)
    result["text"] = " ".join(s["text"] for s in seg_rows).strip()
    result["confidence"] = round(_exp_mean_plog(all_plogs), 4) if all_plogs else None
    seg_confs = [s["confidence"] for s in seg_rows if s["confidence"] is not None]
    result["min_segment_confidence"] = round(min(seg_confs), 4) if seg_confs else None
    result["duration_s"] = round(end_ms / 1000.0, 3)
    seg_lows = [s["low_confidence"] for s in seg_rows if s["low_confidence"] is not None]
    overall = result["confidence"]
    if seg_lows or overall is not None:
        result["low_confidence"] = bool(
            any(seg_lows) or (overall is not None and overall < threshold)
        )
    return result


def run_whisper(
    wav_path: Path,
    language: Optional[str] = None,
    translate: bool = False,
    prompt: Optional[str] = None,
) -> dict:
    binary = Path(CONFIG["whisper"]["binary_path"])
    model = Path(CONFIG["whisper"]["model_path"])
    threads = int(CONFIG["whisper"].get("threads", 4))
    beam_size = int(CONFIG["whisper"].get("beam_size", 5))
    threshold = float(CONFIG["whisper"].get("confidence_threshold", 0.60))
    initial_prompt = str(CONFIG["whisper"].get("initial_prompt", "") or "")

    if not binary.exists():
        logger.error("Whisper binary not found: %s", binary)
        raise HTTPException(status_code=500, detail="Whisper binary not found")
    if not model.exists():
        logger.error("Whisper model not found: %s", model)
        raise HTTPException(status_code=500, detail="Whisper model not found")

    out_base = wav_path.parent / wav_path.stem
    cmd = [
        str(binary),
        "-m", str(model),
        "-f", str(wav_path),
        "-t", str(threads),
        "-bs", str(beam_size),
        "--no-timestamps",
        "--output-txt",
        "--output-json-full",
        "-of", str(out_base),
    ]
    # max_context=0 desactiva el condicionado en texto previo (msgs breves e
    # independientes: evita repeticiones/alucinaciones en bucle)
    max_context = CONFIG["whisper"].get("max_context")
    if max_context is not None:
        cmd += ["--max-context", str(int(max_context))]

    # Form markers no son strings cuando la funcion se llama directamente
    # desde otro endpoint (sin inyeccion de FastAPI)
    if not isinstance(prompt, str):
        prompt = ""
    effective_prompt = (prompt or initial_prompt).strip()
    if effective_prompt:
        cmd += ["--prompt", effective_prompt]

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

    json_path = Path(str(out_base) + ".json")
    txt_path = Path(str(out_base) + ".txt")

    metrics = _parse_whisper_json(json_path, threshold)
    metrics["confidence_threshold"] = threshold
    if not metrics["confidence_available"]:
        # Sin JSON usable: texto desde .txt, sin metricas de confianza
        logger.warning("Whisper JSON output missing or invalid, falling back to txt")
        if txt_path.exists():
            metrics["text"] = txt_path.read_text(encoding="utf-8").strip()

    logger.info(
        "STT metrics: conf=%s low=%s n_seg=%s dur=%ss",
        metrics["confidence"], metrics["low_confidence"],
        metrics["n_segments"], metrics["duration_s"],
    )

    for p in (json_path, txt_path):
        try:
            p.unlink()
        except OSError:
            pass
    return metrics


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
    prompt: Optional[str] = Form(None),
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
        lang = language or str(CONFIG["whisper"].get("language", "auto") or "auto")
        result = run_whisper(
            wav_path, language=lang, translate=translate, prompt=prompt,
        )

        processing_time_ms = int((time.time() - start) * 1000)
        return {
            "text": result["text"],
            "language": lang,
            "model": model.name,
            "processing_time_ms": processing_time_ms,
            "denoise": denoise,
            "translate": translate,
            # --- metricas de confianza (whisper.cpp -ojf) ---
            "n_segments": result["n_segments"],
            "duration_s": result["duration_s"],
            "confidence": result["confidence"],
            "min_segment_confidence": result["min_segment_confidence"],
            "low_confidence": result["low_confidence"],
            "confidence_threshold": result["confidence_threshold"],
            "confidence_available": result["confidence_available"],
            "segments": result["segments"],
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
    prompt: Optional[str] = Form(None),
):
    result = await transcribe(request, file, language, denoise, translate, prompt)
    return result["text"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=CONFIG["app"]["host"],
        port=int(CONFIG["app"]["port"]),
        proxy_headers=True,
    )
