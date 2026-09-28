"""상품·기간을 명시한 리뷰 의미 검색(RAG 검색 단계).

검색 결과는 실제 저장 리뷰와 그 리뷰 ID만 반환합니다. 리뷰 원문은 신뢰하지 않는 데이터이며
Agent가 이를 지시로 해석하지 않도록 상위 계층에서 분리해 전달합니다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.repositories.catalog import ProductRepository, ReviewSearchRepository
from backend.app.schemas.catalog import ReviewSearchHit, ReviewSearchResponse
from backend.app.services.catalog import CatalogService, ProductNotFoundError
from backend.app.services.embeddings import EMBEDDING_MODEL, OllamaEmbedder
from backend.app.services.months import month_bounds

MAX_QUERY_CHARS = 300


# [의미 검색] 검색어를 벡터로 바꿔 상품·기간 안에서 뜻이 비슷한 리뷰를 찾습니다.
class ReviewSearchService:
    def __init__(self, session: Session, embedder: OllamaEmbedder | None = None) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.search_repository = ReviewSearchRepository(session)
        self.catalog = CatalogService(session)
        self.embedder = embedder or OllamaEmbedder(
            model=EMBEDDING_MODEL, base_url=get_settings().ollama_base_url, timeout_seconds=60
        )

    # === [의미 검색] 1) 입력 검증 → 2) 질의 임베딩 → 3) 상품·기간 필터 + 코사인 정렬 ===
    def search(
        self, *, product_id: str, query: str, months: list[str], limit: int = 8
    ) -> ReviewSearchResponse:
        product = self.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        cleaned = " ".join(query.split())
        if not cleaned:
            raise ValueError("검색어가 비어 있습니다.")
        if len(cleaned) > MAX_QUERY_CHARS:
            raise ValueError(f"검색어는 {MAX_QUERY_CHARS}자 이하여야 합니다.")
        if not months:
            raise ValueError("검색할 월(month)을 하나 이상 지정해야 합니다.")
        ranges = [month_bounds(month) for month in sorted(set(months))]

        vector = self.embedder.embed([cleaned])[0]
        hits = self.search_repository.search(
            product_id=product_id,
            ranges=ranges,
            query_embedding=vector,
            model=self.embedder.model,
            limit=limit,
        )
        embedded = sum(
            self.search_repository.embedded_count(product_id, start, end, self.embedder.model)
            for start, end in ranges
        )
        total = sum(
            self.catalog.reviews.count_eligible(product_id, start, end) for start, end in ranges
        )
        run = self.catalog._active_run(product)
        return ReviewSearchResponse(
            product_id=product_id,
            query=cleaned,
            months=sorted(set(months)),
            embedding_model=self.embedder.model,
            embedded_reviews=embedded,
            total_reviews=total,
            items=[
                ReviewSearchHit(
                    # 거리(0~2)를 사람이 읽기 쉬운 유사도(1 - 거리)로 바꿉니다.
                    similarity=round(1 - hit.distance, 4),
                    review=CatalogService._review_response(
                        hit.review,
                        category=product.category,
                        active_run_id=run.id if run is not None else None,
                    ),
                )
                for hit in hits
            ],
        )
