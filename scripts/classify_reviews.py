from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.app.core.analysis_taxonomy import load_taxonomy
from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.database import SessionLocal
from backend.app.models import (
    AnalysisRun,
    Product,
    Review,
    ReviewAnalysisResult,
    ReviewLabel,
)
from backend.app.services.review_classification import (
    PROMPT_VERSION,
    ClassificationError,
    OllamaReviewClassifier,
    review_input_hash,
)

DEFAULT_RUN_ID = "amazon-absa-qwen35-v2"
DEFAULT_SAMPLE = Path("data/evaluation/trial_70.json")
DEFAULT_OUTPUT = Path("data/evaluation")
DATA_VERSION = "amazon-reviews-2023-official-7-v1"


def ollama_model_identity(base_url: str, model: str) -> dict[str, Any]:
    """실행 재현성을 위해 태그뿐 아니라 Ollama 모델 digest도 가능한 경우 기록합니다."""
    identity: dict[str, Any] = {"requested_name": model}
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json().get("models", [])
        matched = next(
            (
                item
                for item in models
                if item.get("name") == model or item.get("model") == model
            ),
            None,
        )
        if matched:
            identity.update(
                {
                    "name": matched.get("name") or matched.get("model"),
                    "digest": matched.get("digest"),
                    "size_bytes": matched.get("size"),
                    "details": matched.get("details"),
                }
            )
    except (requests.RequestException, TypeError, ValueError):
        identity["metadata_status"] = "unavailable"
    return identity


def load_review_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    review_ids = [str(value) for value in payload.get("review_ids", [])]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("시험 표본에 중복 review_id가 있습니다.")
    return review_ids


def official_review_ids(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(Review.id)
            .join(Product, Product.id == Review.product_id)
            .where(
                Review.source_mode == "real",
                Review.eligible.is_(True),
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
            .order_by(Product.category, Product.id, Review.reviewed_at, Review.id)
        )
    )


def product_month_review_ids(
    session: Session, product_id: str, months: list[str]
) -> list[str]:
    """선택 상품·월의 적격 리뷰를 별점과 무관하게 전부 반환합니다."""
    if not months:
        raise ValueError("상품 기간 실행에는 하나 이상의 --month가 필요합니다.")
    reviews = list(
        session.scalars(
            select(Review)
            .join(Product, Product.id == Review.product_id)
            .where(
                Review.product_id == product_id,
                Review.source_mode == "real",
                Review.eligible.is_(True),
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
            .order_by(Review.reviewed_at, Review.id)
        )
    )
    selected = [
        review.id
        for review in reviews
        if review.reviewed_at.strftime("%Y-%m") in set(months)
    ]
    if not selected:
        raise ValueError(f"선택 상품·월에 분석 가능한 리뷰가 없습니다: {product_id}")
    return selected


def ensure_run(
    session: Session,
    *,
    run_id: str,
    model: str,
    target_review_count: int,
    max_attempts: int,
    timeout_seconds: float,
    model_identity: dict[str, Any],
    activate: bool,
) -> AnalysisRun:
    taxonomy_version = str(load_taxonomy()["version"])
    run = session.get(AnalysisRun, run_id)
    if run is not None:
        expected = (model, PROMPT_VERSION, taxonomy_version, "real")
        actual = (run.model, run.prompt_version, run.label_schema_version, run.source_mode)
        if actual != expected:
            raise ValueError(
                f"기존 run {run_id}의 버전이 요청과 다릅니다: {actual} != {expected}"
            )
    if activate:
        session.execute(
            update(AnalysisRun)
            .where(
                AnalysisRun.source_mode == "real",
                AnalysisRun.is_active.is_(True),
                AnalysisRun.id != run_id,
            )
            .values(is_active=False)
        )
    if run is None:
        run = AnalysisRun(
            id=run_id,
            data_version=DATA_VERSION,
            model=model,
            prompt_version=PROMPT_VERSION,
            label_schema_version=taxonomy_version,
            source_mode="real",
            is_active=activate,
            target_review_count=target_review_count,
            config_json={
                "max_attempts": max_attempts,
                "timeout_seconds": timeout_seconds,
                "input_language": "English",
                "rating_used_for_classification": False,
                "model_identity": model_identity,
            },
            status="in_progress",
        )
        session.add(run)
    else:
        if activate:
            run.is_active = True
        run.target_review_count = target_review_count
        run.status = "in_progress"
        run.completed_at = None
        run.config_json = {
            **run.config_json,
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
            "model_identity": model_identity,
        }
    session.commit()
    return run


def _result_id(run_id: str, review_id: str) -> str:
    return f"analysis:{hashlib.sha256(f'{run_id}|{review_id}'.encode()).hexdigest()}"


def ensure_result(session: Session, run_id: str, review: Review) -> ReviewAnalysisResult:
    input_hash = review_input_hash(review.title, review.text)
    result = session.scalar(
        select(ReviewAnalysisResult).where(
            ReviewAnalysisResult.run_id == run_id,
            ReviewAnalysisResult.review_id == review.id,
        )
    )
    if result is None:
        result = ReviewAnalysisResult(
            id=_result_id(run_id, review.id),
            run_id=run_id,
            review_id=review.id,
            input_hash=input_hash,
            status="pending",
            attempt_count=0,
            input_chars=len(review.title or "") + len(review.text),
            error_history=[],
        )
        session.add(result)
        session.commit()
    elif result.input_hash != input_hash:
        session.execute(
            delete(ReviewLabel).where(
                ReviewLabel.run_id == run_id, ReviewLabel.review_id == review.id
            )
        )
        result.input_hash = input_hash
        result.status = "pending"
        result.attempt_count = 0
        result.input_chars = len(review.title or "") + len(review.text)
        result.duration_ms = None
        result.last_error_type = None
        result.last_error = None
        result.error_history = []
        result.raw_response = None
        result.model_metrics_json = {}
        result.db_write_ms = None
        result.completed_at = None
        session.commit()
    return result


def _label_id(
    run_id: str, review_id: str, aspect: str, detail: str, polarity: str, evidence: str
) -> str:
    value = "|".join((run_id, review_id, aspect, detail, polarity, evidence))
    return f"llm-label:{hashlib.sha256(value.encode()).hexdigest()}"


def process_review(
    *,
    run_id: str,
    review_id: str,
    classifier: OllamaReviewClassifier,
    max_attempts: int,
    retry_failed: bool,
) -> str:
    with SessionLocal() as session:
        review = session.get(Review, review_id)
        if review is None:
            raise ValueError(f"리뷰를 찾을 수 없습니다: {review_id}")
        product = session.get(Product, review.product_id)
        if product is None or product.category not in REAL_CATEGORY_KEYS:
            raise ValueError(f"공식 7개 카테고리 리뷰가 아닙니다: {review_id}")
        result = ensure_result(session, run_id, review)
        if result.status == "succeeded":
            return "skipped"
        # 명시적 재실행에서도 직전 검증 오류를 모델 수정 지시에 전달합니다.
        previous_error: str | None = result.last_error
        if result.status == "failed" and retry_failed:
            result.status = "pending"
            result.last_error_type = None
            result.last_error = None
            session.commit()
        if result.status == "failed":
            return "failed"

        # attempt_count는 여러 번 재개해도 누적되는 실제 호출 횟수입니다.
        # max_attempts는 한 번의 명령 실행에서 허용할 호출 횟수를 제한합니다.
        invocation_attempts = 0
        while invocation_attempts < max_attempts:
            result.status = "running"
            invocation_attempts += 1
            result.attempt_count += 1
            result.started_at = datetime.now(UTC)
            session.commit()
            started = time.perf_counter()
            try:
                output = classifier.classify(
                    category=product.category,
                    product_title=product.title,
                    review_title=review.title,
                    review_text=review.text,
                    previous_error=previous_error,
                )
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                error_type = (
                    exc.error_type
                    if isinstance(exc, ClassificationError)
                    else "unexpected_error"
                )
                result.duration_ms = (result.duration_ms or 0) + elapsed_ms
                result.last_error_type = error_type
                result.last_error = str(exc)[:4000]
                result.error_history = [
                    *result.error_history,
                    {
                        "attempt": result.attempt_count,
                        "type": error_type,
                        "message": str(exc)[:1000],
                        "duration_ms": elapsed_ms,
                        "at": datetime.now(UTC).isoformat(),
                    },
                ]
                previous_error = result.last_error
                if invocation_attempts >= max_attempts:
                    result.status = "failed"
                    result.completed_at = datetime.now(UTC)
                else:
                    result.status = "pending"
                session.commit()
                continue

            elapsed_ms = round((time.perf_counter() - started) * 1000)
            session.execute(
                delete(ReviewLabel).where(
                    ReviewLabel.run_id == run_id,
                    ReviewLabel.review_id == review.id,
                )
            )
            for label in output.labels:
                session.add(
                    ReviewLabel(
                        id=_label_id(
                            run_id,
                            review.id,
                            label.aspect_code,
                            label.detail_code,
                            label.polarity,
                            label.evidence_span,
                        ),
                        review_id=review.id,
                        aspect=label.aspect_code,
                        detail_label=label.detail_code,
                        polarity=label.polarity,
                        evidence_span=label.evidence_span,
                        run_id=run_id,
                    )
                )
            result.status = "succeeded"
            result.duration_ms = (result.duration_ms or 0) + elapsed_ms
            result.last_error_type = None
            result.last_error = None
            result.raw_response = output.raw_response
            result.model_metrics_json = output.model_metrics
            result.completed_at = datetime.now(UTC)
            db_started = time.perf_counter()
            session.flush()
            result.db_write_ms = round((time.perf_counter() - db_started) * 1000)
            session.commit()
            return "succeeded"
        return "failed"


def _percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return float(ordered[index])


def run_report(session: Session, run_id: str, review_ids: list[str]) -> dict[str, Any]:
    results = list(
        session.scalars(
            select(ReviewAnalysisResult).where(
                ReviewAnalysisResult.run_id == run_id,
                ReviewAnalysisResult.review_id.in_(review_ids),
            )
        )
    )
    statuses = Counter(result.status for result in results)
    errors = Counter(
        entry["type"] for result in results for entry in (result.error_history or [])
    )
    durations = [result.duration_ms for result in results if result.duration_ms is not None]
    input_chars = [result.input_chars for result in results]
    completed_durations = [
        result.duration_ms
        for result in results
        if result.status == "succeeded" and result.duration_ms is not None
    ]
    total_official = int(
        session.scalar(
            select(func.count(Review.id))
            .join(Product, Product.id == Review.product_id)
            .where(
                Review.source_mode == "real",
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
        )
        or 0
    )
    p25 = _percentile(completed_durations, 0.25)
    p95 = _percentile(completed_durations, 0.95)
    mean_ms = statistics.mean(completed_durations) if completed_durations else None
    return {
        "run_id": run_id,
        "sample_size": len(review_ids),
        "result_records": len(results),
        "status_counts": dict(sorted(statuses.items())),
        "attempt_error_counts": dict(sorted(errors.items())),
        "duration_ms": {
            "mean": round(mean_ms, 1) if mean_ms is not None else None,
            "median": round(statistics.median(completed_durations), 1)
            if completed_durations
            else None,
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
            "p25": p25,
            "p95": p95,
        },
        "input_chars": {
            "mean": round(statistics.mean(input_chars), 1) if input_chars else None,
            "min": min(input_chars) if input_chars else None,
            "max": max(input_chars) if input_chars else None,
        },
        "full_batch_estimate_hours": {
            "mean": round(mean_ms * total_official / 3_600_000, 2)
            if mean_ms is not None
            else None,
            "p25_to_p95": [
                round(p25 * total_official / 3_600_000, 2),
                round(p95 * total_official / 3_600_000, 2),
            ]
            if p25 is not None and p95 is not None
            else None,
            "note": "CPU 단독 순차 실행의 단순 환산이며 재시도·다른 작업 부하에 따라 달라짐",
        },
    }


def refresh_run_status(session: Session, run_id: str) -> None:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        return
    # 이전 버전에서 명시적 재시도 시 attempt_count를 0으로 되돌리던 기록도
    # 실패 이력과 최종 성공 여부를 이용해 보수적으로 복구합니다.
    results = list(
        session.scalars(
            select(ReviewAnalysisResult).where(ReviewAnalysisResult.run_id == run_id)
        )
    )
    for result in results:
        minimum_attempts = len(result.error_history or [])
        if result.status == "succeeded":
            minimum_attempts += 1
        result.attempt_count = max(result.attempt_count, minimum_attempts)
    counts = dict(
        session.execute(
            select(ReviewAnalysisResult.status, func.count(ReviewAnalysisResult.id))
            .where(ReviewAnalysisResult.run_id == run_id)
            .group_by(ReviewAnalysisResult.status)
        ).all()
    )
    succeeded = int(counts.get("succeeded", 0))
    failed = int(counts.get("failed", 0))
    if run.target_review_count > 0 and succeeded == run.target_review_count:
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
    elif run.target_review_count > 0 and succeeded + failed == run.target_review_count:
        run.status = "partial_failure"
        run.completed_at = datetime.now(UTC)
    else:
        run.status = "in_progress"
        run.completed_at = None
    session.commit()


def export_trial_predictions(
    session: Session, run_id: str, review_ids: list[str], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, review_id in enumerate(review_ids, start=1):
        review = session.get(Review, review_id)
        if review is None:
            continue
        product = session.get(Product, review.product_id)
        result = session.scalar(
            select(ReviewAnalysisResult).where(
                ReviewAnalysisResult.run_id == run_id,
                ReviewAnalysisResult.review_id == review_id,
            )
        )
        labels = list(
            session.scalars(
                select(ReviewLabel)
                .where(ReviewLabel.run_id == run_id, ReviewLabel.review_id == review_id)
                .order_by(
                    ReviewLabel.aspect,
                    ReviewLabel.detail_label,
                    ReviewLabel.polarity,
                    ReviewLabel.id,
                )
            )
        )
        rows.append(
            {
                "sample_id": f"trial-{index:03d}",
                "product_id": review.product_id,
                "product_name_ko": product.metadata_json.get("title_ko") if product else "",
                "category": product.category if product else "",
                "review_id": review.id,
                "month": review.reviewed_at.strftime("%Y-%m"),
                "rating_reference_only": review.rating,
                "title_en": review.title or "",
                "text_en": review.text,
                "status": result.status if result else "not_run",
                "attempt_count": result.attempt_count if result else 0,
                "duration_ms": result.duration_ms if result else "",
                "input_chars": result.input_chars if result else len(review.text),
                "error_history_json": json.dumps(
                    result.error_history if result else [], ensure_ascii=False
                ),
                "predicted_labels_json": json.dumps(
                    [
                        {
                            "aspect_code": label.aspect,
                            "detail_code": label.detail_label,
                            "polarity": label.polarity,
                            "evidence_span": label.evidence_span,
                        }
                        for label in labels
                    ],
                    ensure_ascii=False,
                ),
                "analysis_version": run_id,
            }
        )
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="영어 원문 리뷰를 Ollama로 항목별 감성 분류하고 결과를 재개 가능하게 저장합니다."
    )
    parser.add_argument("--model", default="qwen3.5:latest")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--sample-file", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--product-id")
    parser.add_argument("--month", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="완료되지 않은 개발 시험은 기본적으로 활성 통계 버전을 바꾸지 않습니다.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.max_attempts < 1 or args.max_attempts > 5:
        parser.error("--max-attempts는 1~5여야 합니다.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")
    if args.all and args.product_id:
        parser.error("--all과 --product-id는 함께 사용할 수 없습니다.")
    if args.month and not args.product_id:
        parser.error("--month에는 --product-id가 필요합니다.")

    with SessionLocal() as session:
        all_official_ids = official_review_ids(session)
        if args.product_id:
            review_ids = product_month_review_ids(
                session, args.product_id, list(args.month)
            )
        elif args.all:
            review_ids = all_official_ids
        else:
            review_ids = load_review_ids(args.sample_file)
        if args.limit is not None:
            review_ids = review_ids[: args.limit]
        model_identity = ollama_model_identity(args.ollama_url, args.model)
        ensure_run(
            session,
            run_id=args.run_id,
            model=args.model,
            target_review_count=len(all_official_ids),
            max_attempts=args.max_attempts,
            timeout_seconds=args.timeout,
            model_identity=model_identity,
            activate=args.activate,
        )

    classifier = OllamaReviewClassifier(
        model=args.model, base_url=args.ollama_url, timeout_seconds=args.timeout
    )
    invocation = Counter()
    invocation_started = time.perf_counter()
    for index, review_id in enumerate(review_ids, start=1):
        item_started = time.perf_counter()
        outcome = process_review(
            run_id=args.run_id,
            review_id=review_id,
            classifier=classifier,
            max_attempts=args.max_attempts,
            retry_failed=args.retry_failed,
        )
        invocation[outcome] += 1
        print(
            f"[{index}/{len(review_ids)}] {review_id} {outcome} "
            f"({time.perf_counter() - item_started:.1f}초)",
            flush=True,
        )

    args.output.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        refresh_run_status(session, args.run_id)
        report = run_report(session, args.run_id, review_ids)
        report["model"] = args.model
        report["prompt_version"] = PROMPT_VERSION
        report["taxonomy_version"] = load_taxonomy()["version"]
        report["invocation_counts"] = dict(invocation)
        report["invocation_elapsed_seconds"] = round(
            time.perf_counter() - invocation_started, 2
        )
        report_stem = args.sample_file.stem if not args.all and not args.product_id else "run"
        report_path = args.output / f"{report_stem}_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        export_trial_predictions(
            session,
            args.run_id,
            review_ids,
            args.output / f"{report_stem}_predictions.csv",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"시험 보고서: {report_path.resolve()}")


if __name__ == "__main__":
    main()
