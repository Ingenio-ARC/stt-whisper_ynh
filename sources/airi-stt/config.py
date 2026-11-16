import os
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "app": {
        "port": 9800,
        "host": "127.0.0.1",
        "max_file_size_mb": 25,
        "log_level": "info",
        "temp_dir": "/tmp/stt-whisper-test",
        "workers": 1,
    },
    "security": {
        "api_key": "test-key",
        "allowed_ips": ["127.0.0.1", "::1", "testclient"],
    },
    "whisper": {
        "binary_path": "whisper/main",
        "model_path": "models/ggml-base.bin",
        "language": "auto",
        "threads": 2,
        "beam_size": 5,
    },
    "preprocessing": {
        "denoise": False,
    },
}


def load_config(path: str = None) -> dict:
    """Load config from YAML, falling back to defaults for missing sections."""
    if path is None:
        path = os.environ.get("CONFIG_PATH", Path(__file__).with_name("config.yml"))
    path = Path(path)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    merged = {}
    for section, defaults in DEFAULT_CONFIG.items():
        user_values = cfg.get(section, {})
        if user_values is None:
            user_values = {}
        merged[section] = {**defaults, **user_values}
    return merged


CONFIG = load_config()
