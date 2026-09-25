"""공식 14개 상품 리뷰의 bge-m3 임베딩을 생성해 pgvector에 저장합니다.

- 멱등: 같은 모델·같은 원문(content_hash)이면 건너뜁니다. 원문이 바뀐 리뷰만 다시 계산합니다.
- 중단 후 재실행하면 남은 리뷰부터 이어서 처리합니다(배치마다 커밋).
- 기본은 50건만 처리합니다. 전체는 --all로 명시합니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.database import SessionLocal
from backend.app.models import Product, Review, ReviewEmbedding
from backend.app.services.embeddings import (
    EMBEDDING_MODEL,
    OllamaEmbedder,
    content_hash,
    embedding_text,
)


# === [대상 선정] 아직 임베딩이 없거나 원문이 바뀐 공식 카테고리 리뷰 ===
def pending_reviews(model: str, product_id: str | None) -> list[tuple[str, str | None, str]]:
    with SessionLocal() as session:
        existing = dict(
            session.execute(
                select(ReviewEmbedding.review_id, ReviewEmbedding.content_hash).where(
                    ReviewEmbedding.model == model
                )
            ).all()
        )
        query = (
            select(Review.id, Review.title, Review.text)
            .join(Product, Product.id == Review.product_id)
            .where(
                Review.source_mode == "real",
                Review.eligible.is_(True),
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
            .order_by(Product.category, Product.id, Review.id)
        )
        if product_id:
            query = query.where(Review.product_id == product_id)
        rows = session.execute(query).all()
    return [
        (review_id, title, text)
        for review_id, title, text in rows
        if existing.get(review_id) != content_hash(title, text)
    ]


def _embedding_id(model: str, review_id: str) -> str:
    return f"embedding:{hashlib.sha256(f'{model}|{review_id}'.encode()).hexdigest()}"


# === [저장] 같은 리뷰·모델이면 벡터와 해시를 갱신합니다 ===
def save_batch(
    model: str, digest: str | None, batch: list[tuple[str, str | None, str]], vectors: list[list[float]]
) -> None:
    rows = [
        {
            "id": _embedding_id(model, review_id),
            "review_id": review_id,
            "model": model,
            "model_digest": digest,
            "content_hash": content_hash(title, text),
            "embedding": vector,
        }
        for (review_id, title, text), vector in zip(batch, vectors, strict=True)
    ]
    statement = insert(ReviewEmbedding).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_review_embeddings_review_model",
        set_={
            "embedding": statement.excluded.embedding,
            "content_hash": statement.excluded.content_hash,
            "model_digest": statement.excluded.model_digest,
        },
    )
    with SessionLocal() as session:
        session.execute(statement)
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="리뷰 임베딩(bge-m3)을 생성해 저장합니다.")
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--product-id")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true", help="남은 리뷰를 모두 처리합니다.")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    embedder = OllamaEmbedder(model=args.model, base_url=args.ollama_url, timeout_seconds=args.timeout)
    digest = embedder.model_digest()
    targets = pending_reviews(args.model, args.product_id)
    if not args.all:
        targets = targets[: args.limit]
    print(f"임베딩 대상 {len(targets)}건 (model={args.model}, digest={digest})", flush=True)

    started = time.perf_counter()
    done = 0
    for index in range(0, len(targets), args.batch_size):
        batch = targets[index : index + args.batch_size]
        batch_started = time.perf_counter()
        vectors = embedder.embed([embedding_text(title, text) for _, title, text in batch])
        save_batch(args.model, digest, batch, vectors)
        done += len(batch)
        print(
            f"[{done}/{len(targets)}] {len(batch)}건 {time.perf_counter() - batch_started:.1f}s",
            flush=True,
        )
    elapsed = time.perf_counter() - started
    report = {
        "model": args.model,
        "model_digest": digest,
        "processed": done,
        "elapsed_seconds": round(elapsed, 2),
        "seconds_per_review": round(elapsed / done, 3) if done else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
