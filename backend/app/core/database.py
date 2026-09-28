"""DB 연결: SQLAlchemy 엔진·세션을 만들고, API 요청마다 세션을 열고 닫습니다."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings


# 모든 DB 테이블 모델이 상속하는 기본 클래스.
class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# FastAPI 의존성: 요청 하나 동안 쓸 DB 세션을 열고, 끝나면 닫습니다.
def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

