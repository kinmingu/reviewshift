"""pytest 공통 설정.

테스트는 개발 DB가 아니라 TEST_DATABASE_URL이 가리키는 별도 DB에서만 실행합니다.
개발 DB는 실제 Amazon 데이터를 복사해 오는 읽기 전용 원천으로만 사용합니다.
"""

import os
import re
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from backend.app.core.config import Settings, get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# === [테스트 DB 강제] 앱 모듈이 엔진을 만들기 전에 DATABASE_URL을 테스트 DB로 바꿉니다 ===
def _resolve_database_urls() -> tuple[URL, URL]:
    base = Settings()  # type: ignore[call-arg]
    raw_test_url = os.environ.get("TEST_DATABASE_URL") or base.test_database_url
    if not raw_test_url:
        pytest.exit(
            "TEST_DATABASE_URL이 없습니다. .env에 테스트 전용 DB 주소를 추가하세요.",
            returncode=4,
        )
    test_url = make_url(raw_test_url)
    source_url = make_url(base.database_url)
    test_name = test_url.database or ""
    if not re.fullmatch(r"[a-z0-9_]*test[a-z0-9_]*", test_name):
        pytest.exit(f"테스트 DB 이름에 test가 없거나 허용되지 않는 문자가 있습니다: {test_name}", 4)
    same_server = (test_url.host, test_url.port) == (source_url.host, source_url.port)
    if same_server and test_name == source_url.database:
        pytest.exit("테스트 DB가 개발 DB와 같습니다. 서로 다른 DB를 지정하세요.", 4)
    return test_url, source_url


TEST_URL, SOURCE_URL = _resolve_database_urls()
os.environ["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)
get_settings.cache_clear()

# 아래 import는 반드시 DATABASE_URL 교체 뒤에 와야 엔진이 테스트 DB를 가리킵니다.
import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from backend.app.core.database import SessionLocal, engine  # noqa: E402
from backend.app.fixtures import seed_fixtures  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Product, Review  # noqa: E402

assert engine.url.database == TEST_URL.database, "앱 엔진이 테스트 DB를 가리키지 않습니다."


# === [테스트 DB 준비] DB 생성 → 마이그레이션 → 합성 fixture 적재 ===
def _ensure_test_database() -> None:
    admin = create_engine(TEST_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_URL.database},
            )
            if not exists:
                # 이름은 위에서 [a-z0-9_]로 검증했으므로 식별자로 안전하게 사용할 수 있습니다.
                connection.execute(text(f'CREATE DATABASE "{TEST_URL.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def prepared_database() -> Generator[None, None, None]:
    _ensure_test_database()
    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    command.upgrade(config, "head")
    with SessionLocal() as session:
        seed_fixtures(session)
    yield


# === [실제 데이터 복사] real_data 표식 테스트만 개발 DB의 실제 상품·리뷰를 복사해 사용합니다 ===
EVALUATION_FILES = (
    PROJECT_ROOT / "data" / "evaluation" / "trial_70.json",
    PROJECT_ROOT / "data" / "evaluation" / "human_review_blind_140.csv",
)


def _copy_real_catalog() -> str | None:
    """복사에 실패하면 건너뛸 이유를, 성공하면 None을 반환합니다. 개발 DB에는 쓰지 않습니다."""
    missing = [path.name for path in EVALUATION_FILES if not path.exists()]
    if missing:
        return f"로컬 평가 파일이 없습니다: {', '.join(missing)}"
    source = create_engine(SOURCE_URL)
    try:
        with source.connect() as connection:
            products = [
                dict(row)
                for row in connection.execute(
                    Product.__table__.select().where(Product.source_mode == "real")
                ).mappings()
            ]
            reviews = [
                dict(row)
                for row in connection.execute(
                    Review.__table__.select().where(Review.source_mode == "real")
                ).mappings()
            ]
    except Exception as exc:  # 개발 DB가 없거나 스키마가 다르면 실제 데이터 테스트만 건너뜁니다.
        return f"개발 DB에서 실제 데이터를 읽을 수 없습니다: {type(exc).__name__}"
    finally:
        source.dispose()
    if not products or not reviews:
        return "개발 DB에 실제 Amazon 데이터가 적재되어 있지 않습니다."

    with SessionLocal() as session:
        session.execute(insert(Product).values(products).on_conflict_do_nothing())
        for start in range(0, len(reviews), 1_000):
            session.execute(
                insert(Review).values(reviews[start : start + 1_000]).on_conflict_do_nothing()
            )
        session.commit()

    from scripts.seed_human_evaluation import seed as seed_human_evaluation

    seed_human_evaluation()
    return None


@pytest.fixture(scope="session")
def real_data(prepared_database: None) -> None:
    reason = _copy_real_catalog()
    if reason:
        pytest.skip(reason)


@pytest.fixture(autouse=True)
def _require_real_data(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_data"):
        request.getfixturevalue("real_data")


# === [API 클라이언트] TestClient와 Streamlit 테스트용 실제 HTTP 서버 ===
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
