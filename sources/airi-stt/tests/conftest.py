import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient
from main import app, CONFIG


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def api_key():
    return CONFIG["security"]["api_key"]
