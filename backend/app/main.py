"""FastAPI 앱 시작점: 앱을 만들고 CORS와 API 라우트를 연결합니다.

실행: uvicorn backend.app.main:app
"""

from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.config import get_settings


# 설정을 읽어 FastAPI 앱을 만들고 라우트를 등록합니다.
def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="ReviewShift 단계 1 fixture API",
    )
    app.include_router(router)
    return app


app = create_app()

