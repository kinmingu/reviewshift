from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "ReviewShift API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str
    # pytest 전용 DB입니다. 개발 DB와 분리하지 않으면 테스트가 실제 평가 입력을 덮어씁니다.
    test_database_url: str | None = None
    source_mode: str = "fixture"
    analysis_min_review_count: int = 30
    analysis_min_negative_count: int = 5
    analysis_min_increase_pp: float = 10.0
    # 재시도 후에도 실패한 리뷰가 이 비율 이하이면 해당 월을 분석 완료로 보고 분모에서 제외합니다.
    analysis_max_failure_rate: float = 0.05
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:latest"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
