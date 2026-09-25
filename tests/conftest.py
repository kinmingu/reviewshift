import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.app.core.database import SessionLocal
from backend.app.fixtures import seed_fixtures
from backend.app.main import app
from scripts.seed_human_evaluation import seed as seed_human_evaluation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def prepared_database() -> Generator[None, None, None]:
    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    with SessionLocal() as session:
        seed_fixtures(session)
    seed_human_evaluation()
    yield


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def live_api_url(prepared_database: None) -> Generator[str, None, None]:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    host, port = server_socket.getsockname()
    config = uvicorn.Config(app, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [server_socket]}, daemon=True
    )
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("test API server did not start")
    yield f"http://{host}:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    server_socket.close()
