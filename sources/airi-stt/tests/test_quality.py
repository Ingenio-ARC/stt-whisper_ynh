import pytest
from pathlib import Path

try:
    import jiwer
    JIWER_AVAILABLE = True
except ImportError:
    JIWER_AVAILABLE = False

from main import app, CONFIG


def auth_headers(api_key):
    return {"X-API-KEY": api_key}


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _samples_dir() -> Path:
    return Path(__file__).parent / "samples"


def _list_samples():
    samples_dir = _samples_dir()
    if not samples_dir.exists():
        return []
    samples = []
    for audio in sorted(samples_dir.glob("*")):
        if audio.suffix.lower() in {".mp3", ".ogg", ".wav", ".m4a", ".webm", ".flac"}:
            transcript = audio.with_suffix(".txt")
            if transcript.exists():
                samples.append((audio, transcript))
    return samples


@pytest.mark.skipif(not JIWER_AVAILABLE, reason="jiwer not installed")
@pytest.mark.parametrize("audio_file, transcript_file", _list_samples())
def test_wer(client, api_key, audio_file, transcript_file):
    model = Path(CONFIG["whisper"]["model_path"])
    if not model.exists():
        pytest.skip("Whisper model not available")

    expected = _normalize(transcript_file.read_text(encoding="utf-8"))
    if not expected:
        pytest.skip("Empty reference transcript")

    with open(audio_file, "rb") as f:
        response = client.post(
            "/transcribe",
            files={"file": (audio_file.name, f, "audio/mpeg")},
            data={"language": "es"},
            headers=auth_headers(api_key),
        )
    assert response.status_code == 200
    predicted = _normalize(response.json()["text"])
    wer = jiwer.wer(expected, predicted)
    cer = jiwer.cer(expected, predicted)
    print(f"[{audio_file.name}] WER={wer:.2%} CER={cer:.2%} REF={expected!r} HYP={predicted!r}")
    assert wer < 0.30, f"WER too high for {audio_file.name}: {wer:.2%}"
