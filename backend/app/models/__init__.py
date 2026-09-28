"""DB 테이블 모델을 한곳에서 가져다 쓸 수 있게 모아 둡니다."""

from backend.app.models.domain import (
    AgentAnswer,
    AnalysisRun,
    HumanReviewEvaluation,
    Product,
    Review,
    ReviewAnalysisResult,
    ReviewEmbedding,
    ReviewLabel,
)

__all__ = [
    "AgentAnswer",
    "AnalysisRun",
    "HumanReviewEvaluation",
    "Product",
    "Review",
    "ReviewAnalysisResult",
    "ReviewEmbedding",
    "ReviewLabel",
]
