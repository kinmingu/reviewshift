"""상품별 자주 묻는 질문(FAQ) 답변을 미리 생성해 저장합니다.

- 분석 상태가 그대로인 최신 답은 건너뛰고, 없거나 낡은 답만 만듭니다(--force면 모두 다시).
- 검증에 실패한 답은 저장하지 않고 실패로 보고합니다.
- CPU에서 답변 1개에 1~3분 걸립니다(--fast: 빠른 요약본 RAG, 약 35초). 분류 배치와 동시에 돌리면 둘 다 느려집니다.

예) 데모 4개 상품:  python -m scripts.generate_faq_answers --demo
    특정 상품:       python -m scripts.generate_faq_answers --product-id amazon-B000FS05VG
    추가 질문(빠르게): python -m scripts.generate_faq_answers --all --fast --only quality --only size
"""

from __future__ import annotations

import argparse
import json
import time

from sqlalchemy import select

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.database import SessionLocal
from backend.app.models import Product
from backend.app.schemas.catalog import AgentAnswerResponse
from backend.app.services.answer_store import FAQ_QUESTIONS, AnswerStore
from backend.app.services.fast_answer import FastAnswerService
from backend.app.services.review_agent import AgentUnavailableError, ReviewQuestionAgent

# README "데모 분류 범위"와 같은 4개 상품
DEMO_PRODUCTS = (
    "amazon-B087H2LWWZ",
    "amazon-B08VD2NX25",
    "amazon-B07NZJ1MHX",
    "amazon-B0BWLH7QX5",
)


# 상품 × FAQ 질문마다 최신 답이 없으면 AI 에이전트로 만들어 저장하고, 결과 개수를 셉니다.
def _fast_answer(session, product_id: str, question: str) -> AgentAnswerResponse:
    """빠른 요약본 RAG로 답을 만들고 마지막(done) 결과만 씁니다."""
    product = session.get(Product, product_id)
    name = str(product.metadata_json.get("title_ko") or product.title) if product else None
    result = None
    for event in FastAnswerService().stream(product_id, question, product_name=name):
        if event["type"] == "done":
            result = event["result"]
    if result is None:
        raise AgentUnavailableError("답변을 끝까지 받지 못했습니다.")
    return AgentAnswerResponse.model_validate(result)


def generate(
    product_ids: list[str], *, force: bool, only: set[str] | None = None, fast: bool = False
) -> dict:
    counts = {"generated": 0, "skipped_fresh": 0, "failed": 0, "unavailable": 0}
    for product_id in product_ids:
        for key, label, question in FAQ_QUESTIONS:
            if only and key not in only:
                continue
            with SessionLocal() as session:
                store = AnswerStore(session)
                snapshot = store.snapshot(product_id)
                existing = store.get(product_id, question)
                if existing and not force and not store.is_stale(existing, snapshot):
                    counts["skipped_fresh"] += 1
                    print(f"[skip] {product_id} {key} (최신)", flush=True)
                    continue
                started = time.perf_counter()
                try:
                    result = (
                        _fast_answer(session, product_id, question)
                        if fast
                        else ReviewQuestionAgent(session).ask(product_id, question)
                    )
                except AgentUnavailableError as exc:
                    counts["unavailable"] += 1
                    print(f"[model-error] {product_id} {key}: {exc}", flush=True)
                    continue
                store.save(product_id, result, snapshot, faq_key=key)
                outcome = "generated" if result.status == "answered" else "failed"
                counts[outcome] += 1
                print(
                    f"[{outcome}] {product_id} {label} {time.perf_counter() - started:.0f}s "
                    f"(분석 {snapshot.analyzed_count}건 기준)"
                    + (f" 사유: {result.failure_reason}" if outcome == "failed" else ""),
                    flush=True,
                )
    return counts


# 대상 상품(특정/데모/전체)을 정해 FAQ 답 생성을 실행합니다.
def main() -> None:
    parser = argparse.ArgumentParser(description="상품별 FAQ 답변을 미리 생성합니다.")
    parser.add_argument("--product-id", action="append", default=[])
    parser.add_argument("--demo", action="store_true", help="데모 4개 상품")
    parser.add_argument("--all", action="store_true", help="공식 14개 상품 전체")
    parser.add_argument("--only", action="append", default=[], help="FAQ 키만(예: summary)")
    parser.add_argument("--force", action="store_true", help="최신 답도 다시 생성")
    parser.add_argument("--fast", action="store_true", help="빠른 요약본 RAG로 생성(약 35초/개)")
    args = parser.parse_args()

    product_ids = list(args.product_id)
    if args.demo:
        product_ids += list(DEMO_PRODUCTS)
    if args.all:
        with SessionLocal() as session:
            product_ids += list(
                session.scalars(
                    select(Product.id)
                    .where(Product.source_mode == "real", Product.category.in_(REAL_CATEGORY_KEYS))
                    .order_by(Product.category, Product.id)
                )
            )
    product_ids = list(dict.fromkeys(product_ids))
    if not product_ids:
        parser.error("--product-id, --demo, --all 중 하나가 필요합니다.")
    started = time.perf_counter()
    counts = generate(product_ids, force=args.force, only=set(args.only) or None, fast=args.fast)
    counts["elapsed_seconds"] = round(time.perf_counter() - started, 1)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
