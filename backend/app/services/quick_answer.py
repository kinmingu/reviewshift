"""리뷰 챗봇 즉시 답변: LLM 없이 DB에 정리된 분석 결과로 1초 안에 답합니다.

흐름(질문 임베딩 1회를 세 곳에 재사용)
1) 미리 만든 FAQ 질문과 의미가 가까우면 저장된 FAQ 답을 그대로 사용
2) 질문을 분석 항목(배송·포장, 마감·소재, 신뢰성·고장 …)의 설명과 비교해 가까운 항목 2개 선택
3) 선택 항목의 SQL 집계(언급·좋아요·아쉬워요 리뷰 수)와 대표 근거, pgvector 관련 리뷰 검색 결과로 답 구성
숫자와 인용은 모두 DB 값 그대로이며, 자연스러운 설명이 필요하면 'AI에게 자세히 묻기'를 씁니다.
"""

from __future__ import annotations

import math
import time
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.analysis_taxonomy import category_labels
from backend.app.core.config import get_settings
from backend.app.repositories.catalog import ReviewSearchRepository
from backend.app.services.answer_store import FAQ_QUESTIONS, AnswerStore
from backend.app.services.catalog import CatalogService, ProductNotFoundError
from backend.app.services.embeddings import EMBEDDING_MODEL, OllamaEmbedder
from backend.app.services.months import month_bounds

QUICK_VERSION = "quick-answer-v1"
FAQ_MATCH_SIMILARITY = 0.80
TOP_ASPECTS = 2
RELATED_REVIEWS = 4
EXCERPT_CHARS = 300
SMALL_SAMPLE = 30

# 분석 항목·FAQ 설명 벡터는 바뀌지 않으므로 프로세스 안에서 한 번만 계산합니다.
_aspect_vectors: dict[str, list[tuple[tuple[str, str], list[float]]]] = {}
_faq_vectors: list[tuple[str, list[float]]] = []


# 두 벡터의 코사인 유사도(1에 가까울수록 뜻이 비슷함).
def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# [즉시 답] 질문 벡터로 관련 분석 항목과 비슷한 리뷰를 찾아, DB 집계값만으로 답 문장을 만듭니다.
class QuickAnswerService:
    def __init__(self, session: Session, embedder: OllamaEmbedder | None = None) -> None:
        self.session = session
        self.catalog = CatalogService(session)
        self.store = AnswerStore(session)
        self.search = ReviewSearchRepository(session)
        self.embedder = embedder or OllamaEmbedder(
            model=EMBEDDING_MODEL, base_url=get_settings().ollama_base_url, timeout_seconds=30
        )

    # === [벡터 준비] 항목 설명·FAQ 질문 벡터(캐시) ===
    def _aspects_for(self, category: str) -> list[tuple[tuple[str, str], list[float]]]:
        if category not in _aspect_vectors:
            labels = category_labels(category)
            keys = list(labels)
            texts = [
                f"{labels[key]['aspect_name_ko']} {labels[key]['detail_name_ko']}: "
                f"{labels[key]['include']}"
                for key in keys
            ]
            _aspect_vectors[category] = list(zip(keys, self.embedder.embed(texts), strict=True))
        return _aspect_vectors[category]

    # FAQ 질문들의 벡터(처음 한 번만 계산해 메모리에 보관).
    def _faqs(self) -> list[tuple[str, list[float]]]:
        if not _faq_vectors:
            keys = [key for key, _, _ in FAQ_QUESTIONS]
            vectors = self.embedder.embed([question for _, _, question in FAQ_QUESTIONS])
            _faq_vectors.extend(zip(keys, vectors, strict=True))
        return _faq_vectors

    # === [즉시 답변] ===
    def answer(self, product_id: str, question: str) -> dict[str, Any]:
        started = time.perf_counter()
        product = self.catalog.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        cleaned = " ".join(question.split())
        if len(cleaned) < 2:
            raise ValueError("질문을 2자 이상 입력해 주세요.")
        vector = self.embedder.embed([cleaned])[0]

        # 1) 가까운 FAQ가 있으면 저장된 답을 함께 돌려줍니다(분석 상태가 최신일 때만).
        matched_faq = None
        faq_key, faq_similarity = max(
            ((key, _cosine(vector, faq_vector)) for key, faq_vector in self._faqs()),
            key=lambda item: item[1],
        )
        if faq_similarity >= FAQ_MATCH_SIMILARITY:
            faq = self.store.faq(product_id)
            item = next((entry for entry in faq.items if entry.key == faq_key), None)
            if item and item.answer and not item.answer.is_stale:
                matched_faq = item.answer.model_dump(mode="json")

        # 2) 질문과 가까운 분석 항목 2개
        ranked = sorted(
            ((key, _cosine(vector, aspect_vector)) for key, aspect_vector in self._aspects_for(
                product.category
            )),
            key=lambda item: -item[1],
        )[:TOP_ASPECTS]
        insights = self.catalog.product_insights(product_id)
        stats = {(item.aspect, item.detail_label): item for item in insights.aspects}
        labels = category_labels(product.category)
        run = self.catalog._active_run(product)
        sample = self.catalog._sample_ids(product)
        analyzed = insights.analysis.succeeded
        aspects = []
        for (aspect, detail), similarity in ranked:
            stat = stats.get((aspect, detail))
            examples = []
            if run is not None and stat is not None:
                for polarity in ("negative", "positive"):
                    for example in self.catalog.insights.label_examples(
                        product_id, run.id, aspect, detail, polarity, limit=2, review_ids=sample
                    ):
                        examples.append(
                            {
                                "review_id": example.review_id,
                                "polarity": polarity,
                                "rating": example.rating,
                                "date": example.reviewed_at.date().isoformat(),
                                "evidence": example.evidence_span[:EXCERPT_CHARS],
                            }
                        )
            aspects.append(
                {
                    "aspect": aspect,
                    "detail_label": detail,
                    "name_ko": f"{labels[(aspect, detail)]['aspect_name_ko']} · "
                    f"{labels[(aspect, detail)]['detail_name_ko']}",
                    "similarity": round(similarity, 3),
                    "mention_count": stat.mention_count if stat else 0,
                    "positive_count": stat.positive_count if stat else 0,
                    "negative_count": stat.negative_count if stat else 0,
                    "examples": examples,
                }
            )

        # 3) 질문과 의미가 가까운 실제 리뷰(pgvector, 이 상품의 저장 월로 제한)
        months = self.catalog.products.available_months(product_id)
        hits = self.search.search(
            product_id=product_id,
            ranges=[month_bounds(month) for month in months],
            query_embedding=vector,
            model=self.embedder.model,
            limit=RELATED_REVIEWS,
        ) if months else []
        related = []
        for hit in hits:
            review = CatalogService._review_response(
                hit.review, category=product.category, active_run_id=run.id if run else None
            )
            related.append(
                {
                    "review_id": review.id,
                    "similarity": round(1 - hit.distance, 3),
                    "rating": review.rating,
                    "date": review.reviewed_at.date().isoformat(),
                    "title": review.title or "",
                    "text": review.text[:EXCERPT_CHARS],
                    "text_ko": (review.text_ko or "")[:EXCERPT_CHARS] or None,
                    "labels": [
                        f"{label.detail_name_ko or label.detail_label}:{label.polarity}"
                        for label in review.labels
                    ],
                }
            )

        return {
            "product_id": product_id,
            "question": cleaned,
            "answer_text": self._compose(aspects, analyzed, len(related)),
            "matched_faq": matched_faq,
            "aspects": aspects,
            "related_reviews": related,
            "analyzed_reviews": analyzed,
            "is_small_sample": analyzed < SMALL_SAMPLE,
            "version": QUICK_VERSION,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    @staticmethod
    def _compose(aspects: list[dict[str, Any]], analyzed: int, related: int) -> str:
        """DB 값만으로 만든 짧은 한국어 요약(수치를 새로 계산하지 않음)."""
        lines = [f"AI가 분석한 리뷰 {analyzed}건에서 질문과 관련된 항목을 찾았어요."]
        for item in aspects:
            if item["mention_count"]:
                lines.append(
                    f"· {item['name_ko']}: {item['mention_count']}건 언급 "
                    f"(아쉬워요 {item['negative_count']}건, 좋아요 {item['positive_count']}건)"
                )
            else:
                lines.append(f"· {item['name_ko']}: 분석된 리뷰에서 언급이 없어요")
        if related:
            lines.append(f"질문과 비슷한 실제 리뷰 {related}건을 아래에 모았어요.")
        if analyzed < SMALL_SAMPLE:
            lines.append("분석한 리뷰가 적어 참고용으로 봐 주세요.")
        return "\n".join(lines)
