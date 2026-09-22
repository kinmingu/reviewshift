from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.core.config import get_settings


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

