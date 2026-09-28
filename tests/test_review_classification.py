"""AI 분류기 테스트: 모델 응답 JSON 파싱, 분류 체계에 없는 항목 거부, 근거 문장 검증(원문 포함·단어 경계·최소 길이).

실제 모델 없이 가짜 응답으로 검증 규칙만 확인합니다.
"""

import json
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from backend.app.core.analysis_taxonomy import category_labels, load_taxonomy
from backend.app.core.database import SessionLocal
from backend.app.models import AnalysisRun, Review, ReviewAnalysisResult
from backend.app.repositories.catalog import AnalysisCoverageAggregate
from backend.app.services.catalog import CatalogService
from backend.app.services.review_classification import (
    ClassificationOutput,
    EvidenceValidationError,
    OllamaReviewClassifier,
    TaxonomyValidationError,
    output_schema,
    parse_classification,
)
from scripts.classify_reviews import process_review, product_month_review_ids

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_category_taxonomy_has_korean_display_names() -> None:
    label = category_labels("Beauty_and_Personal_Care")[("beauty_use", "hair_drying")]
    assert label["aspect_name_ko"] == "미용 사용 경험"
    assert label["detail_name_ko"] == "모발 건조"


def test_classification_parser_accepts_multiple_and_opposite_labels() -> None:
    title = "Good sound, bad connection"
    text = "The sound is clear but Bluetooth keeps disconnecting."
    content = json.dumps(
        {
            "labels": [
                {
                    "aspect_code": "audio_video",
                    "detail_code": "sound_quality",
                    "polarity": "positive",
                    "evidence_span": "sound is clear",
                },
                {
                    "aspect_code": "power_connection",
                    "detail_code": "connectivity",
                    "polarity": "negative",
                    "evidence_span": "Bluetooth keeps disconnecting",
                },
            ]
        }
    )

    output = parse_classification(
        content, category="Electronics", title=title, text=text
    )

    assert len(output.labels) == 2
    assert {label.polarity for label in output.labels} == {"positive", "negative"}


def test_classification_parser_accepts_normal_empty_result() -> None:
    output = parse_classification(
        '{"labels": []}',
        category="Electronics",
        title="No opinion",
        text="This is the model I received.",
    )
    assert output.labels == ()


def test_v2_schema_uses_only_valid_combined_taxonomy_codes() -> None:
    item_schema = output_schema("Sports_and_Outdoors")["properties"]["labels"][
        "items"
    ]
    codes = item_schema["properties"]["code"]["enum"]
    assert "sports_use.inflation" in codes
    assert "performance.inflation" not in codes
    assert item_schema["required"] == ["code", "sentiment", "evidence"]


def test_v2_compact_output_is_parsed_and_invalid_pair_is_rejected() -> None:
    output = parse_classification(
        json.dumps(
            {
                "labels": [
                    {
                        "code": "sports_use.inflation",
                        "sentiment": "negative",
                        "evidence": "no pump included",
                    }
                ]
            }
        ),
        category="Sports_and_Outdoors",
        title="no pump included",
        text="The box was empty.",
    )
    assert output.labels[0].detail_code == "inflation"
    with pytest.raises(TaxonomyValidationError):
        parse_classification(
            '{"labels":[{"code":"performance.inflation",'
            '"sentiment":"negative","evidence":"no pump included"}]}',
            category="Sports_and_Outdoors",
            title="no pump included",
            text="The box was empty.",
        )


def test_classifier_excludes_product_metadata_and_records_ollama_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "message": {"content": '{"labels":[]}'},
                "total_duration": 20,
                "load_duration": 1,
                "prompt_eval_count": 30,
                "prompt_eval_duration": 10,
                "eval_count": 5,
                "eval_duration": 9,
                "done_reason": "stop",
            }

    def fake_post(*_: object, **kwargs: object) -> _Response:
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("backend.app.services.review_classification.requests.post", fake_post)
    classifier = OllamaReviewClassifier(model="test-model")
    result = classifier.classify(
        category="Toys_and_Games",
        product_title="Multicolor product metadata must not be evidence",
        review_title="A gift",
        review_text="I gave it to my grandson.",
    )

    request_json = captured["json"]
    assert isinstance(request_json, dict)
    user_payload = json.loads(request_json["messages"][1]["content"])
    assert "product_title" not in user_payload
    assert request_json["think"] is False
    assert request_json["keep_alive"] == "30m"
    assert result.model_metrics["prompt_eval_count"] == 30


def test_classification_parser_rejects_free_text_taxonomy() -> None:
    content = json.dumps(
        {
            "labels": [
                {
                    "aspect_code": "invented",
                    "detail_code": "anything",
                    "polarity": "negative",
                    "evidence_span": "bad",
                }
            ]
        }
    )
    with pytest.raises(TaxonomyValidationError):
        parse_classification(
            content, category="Electronics", title="bad", text="bad"
        )


def test_classification_parser_rejects_non_verbatim_evidence() -> None:
    content = json.dumps(
        {
            "labels": [
                {
                    "aspect_code": "performance",
                    "detail_code": "reliability",
                    "polarity": "negative",
                    "evidence_span": "stopped after one week",
                }
            ]
        }
    )
    with pytest.raises(EvidenceValidationError):
        parse_classification(
            content,
            category="Electronics",
            title="Broken",
            text="It stopped working after seven days.",
        )


def test_typographic_quote_is_mapped_back_to_exact_source_text() -> None:
    content = json.dumps(
        {
            "labels": [
                {
                    "aspect_code": "performance",
                    "detail_code": "reliability",
                    "polarity": "negative",
                    "evidence_span": "it doesn't work",
                }
            ]
        }
    )
    output = parse_classification(
        content,
        category="Electronics",
        title=None,
        text="After a week it doesn’t work anymore.",
    )
    assert output.labels[0].evidence_span == "it doesn’t work"


def test_collapsed_whitespace_is_mapped_back_to_exact_source_text() -> None:
    output = parse_classification(
        json.dumps(
            {
                "labels": [
                    {
                        "aspect_code": "service",
                        "detail_code": "shipping",
                        "polarity": "positive",
                        "evidence_span": "shipped fast",
                    }
                ]
            }
        ),
        category="Sports_and_Outdoors",
        title=None,
        text="packaged well and shipped  fast",
    )
    assert output.labels[0].evidence_span == "shipped  fast"


class _EmptyClassifier:
    model = "test-model"

    def __init__(self, fail_once: bool = False) -> None:
        self.calls = 0
        self.fail_once = fail_once
        self.last_previous_error: str | None = None

    def classify(self, **kwargs: object) -> ClassificationOutput:
        self.calls += 1
        previous_error = kwargs.get("previous_error")
        self.last_previous_error = (
            str(previous_error) if previous_error is not None else None
        )
        if self.fail_once and self.calls == 1:
            raise EvidenceValidationError("test evidence failure")
        return ClassificationOutput(labels=(), raw_response='{"labels":[]}')


class _AlwaysFailClassifier:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, **_: object) -> ClassificationOutput:
        self.calls += 1
        raise EvidenceValidationError("test evidence failure")


real_data = pytest.mark.real_data


def _create_test_run(run_id: str) -> str:
    trial = json.loads(
        (PROJECT_ROOT / "data" / "evaluation" / "trial_70.json").read_text(
            encoding="utf-8"
        )
    )
    review_id = trial["review_ids"][0]
    with SessionLocal() as session:
        session.add(
            AnalysisRun(
                id=run_id,
                data_version="test-data",
                model="test-model",
                prompt_version="test-prompt",
                label_schema_version=str(load_taxonomy()["version"]),
                source_mode="real",
                is_active=False,
                target_review_count=1,
                config_json={"test": True},
                status="in_progress",
            )
        )
        session.commit()
        assert session.get(Review, review_id) is not None
    return review_id


def _delete_test_run(run_id: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(AnalysisRun).where(AnalysisRun.id == run_id))
        session.commit()


@real_data
def test_processing_is_idempotent_for_same_version_and_input() -> None:
    run_id = "test-analysis-idempotency"
    review_id = _create_test_run(run_id)
    classifier = _EmptyClassifier()
    try:
        first = process_review(
            run_id=run_id,
            review_id=review_id,
            classifier=classifier,  # type: ignore[arg-type]
            max_attempts=2,
            retry_failed=False,
        )
        second = process_review(
            run_id=run_id,
            review_id=review_id,
            classifier=classifier,  # type: ignore[arg-type]
            max_attempts=2,
            retry_failed=False,
        )
        assert first == "succeeded"
        assert second == "skipped"
        assert classifier.calls == 1
        with SessionLocal() as session:
            results = list(
                session.scalars(
                    select(ReviewAnalysisResult).where(
                        ReviewAnalysisResult.run_id == run_id,
                        ReviewAnalysisResult.review_id == review_id,
                    )
                )
            )
            assert len(results) == 1
            assert results[0].status == "succeeded"
    finally:
        _delete_test_run(run_id)


@real_data
def test_validation_failure_is_retried_and_recorded() -> None:
    run_id = "test-analysis-retry"
    review_id = _create_test_run(run_id)
    classifier = _EmptyClassifier(fail_once=True)
    try:
        outcome = process_review(
            run_id=run_id,
            review_id=review_id,
            classifier=classifier,  # type: ignore[arg-type]
            max_attempts=2,
            retry_failed=False,
        )
        assert outcome == "succeeded"
        with SessionLocal() as session:
            result = session.scalar(
                select(ReviewAnalysisResult).where(
                    ReviewAnalysisResult.run_id == run_id,
                    ReviewAnalysisResult.review_id == review_id,
                )
            )
            assert result is not None
            assert result.attempt_count == 2
            assert result.status == "succeeded"
            assert result.error_history[0]["type"] == "evidence_validation_error"
            assert result.error_history[0]["duration_ms"] >= 0
    finally:
        _delete_test_run(run_id)


@real_data
def test_explicit_retry_preserves_cumulative_attempt_count() -> None:
    run_id = "test-analysis-cumulative-retry"
    review_id = _create_test_run(run_id)
    failing = _AlwaysFailClassifier()
    succeeding = _EmptyClassifier()
    try:
        assert (
            process_review(
                run_id=run_id,
                review_id=review_id,
                classifier=failing,  # type: ignore[arg-type]
                max_attempts=2,
                retry_failed=False,
            )
            == "failed"
        )
        assert (
            process_review(
                run_id=run_id,
                review_id=review_id,
                classifier=succeeding,  # type: ignore[arg-type]
                max_attempts=2,
                retry_failed=True,
            )
            == "succeeded"
        )
        with SessionLocal() as session:
            result = session.scalar(
                select(ReviewAnalysisResult).where(
                    ReviewAnalysisResult.run_id == run_id,
                    ReviewAnalysisResult.review_id == review_id,
                )
            )
            assert result is not None
            assert result.attempt_count == 3
            assert len(result.error_history) == 2
            assert succeeding.last_previous_error == "test evidence failure"
    finally:
        _delete_test_run(run_id)


def test_period_status_tolerates_small_final_failure_rate() -> None:
    status = CatalogService._period_status
    # (total, succeeded, failed, in_progress, labeled)
    assert status(AnalysisCoverageAggregate(0, 0, 0, 0, 0), 0.05) == "not_started"
    assert status(AnalysisCoverageAggregate(10, 2, 0, 0, 2), 0.05) == "in_progress"
    # 처리 중에 실패가 생겨도 남은 리뷰가 있으면 아직 진행 중입니다.
    assert status(AnalysisCoverageAggregate(100, 50, 1, 0, 40), 0.05) == "in_progress"
    assert status(AnalysisCoverageAggregate(100, 98, 1, 1, 80), 0.05) == "in_progress"
    assert status(AnalysisCoverageAggregate(10, 10, 0, 0, 8), 0.05) == "complete"
    # 재시도 후에도 남은 실패 1건이 기간 전체를 영원히 막지 않습니다(1/125 = 0.8%).
    assert status(AnalysisCoverageAggregate(125, 124, 1, 0, 100), 0.05) == "complete"
    # 기준과 같은 실패율은 허용하고, 넘으면 일부 실패로 남깁니다.
    assert status(AnalysisCoverageAggregate(100, 95, 5, 0, 80), 0.05) == "complete"
    assert status(AnalysisCoverageAggregate(100, 94, 6, 0, 80), 0.05) == "partial_failure"
    assert status(AnalysisCoverageAggregate(10, 8, 2, 0, 7), 0.05) == "partial_failure"


def test_model_evidence_requires_word_boundary_and_minimum_length() -> None:
    def parse(evidence: str, *, title: str | None = "Great value", min_words: int = 2):
        return parse_classification(
            json.dumps(
                {
                    "labels": [
                        {
                            "code": "performance.core_performance",
                            "sentiment": "positive",
                            "evidence": evidence,
                        }
                    ]
                }
            ),
            category="Electronics",
            title=title,
            text="Bought on Amazon. The volume is loud and it works great.",
            min_evidence_words=min_words,
        )

    assert parse("works great").labels[0].evidence_span == "works great"
    # 단어 일부 일치 거부: "on"이 "Amazon" 안에, "work"가 "works" 안에 있어도 안 됩니다.
    with pytest.raises(EvidenceValidationError, match="찾을 수 없는"):
        parse("azon. The")
    with pytest.raises(EvidenceValidationError, match="찾을 수 없는"):
        parse("it work")
    # 모델 출력의 한 단어 근거는 원문에 있어도 거부합니다.
    with pytest.raises(EvidenceValidationError, match="너무 짧습니다"):
        parse("volume")
    # 제목 전체가 한 단어인 짧은 리뷰는 예외로 허용합니다.
    assert parse("Amazin!!!", title="Amazin!!!").labels[0].evidence_span == "Amazin!!!"
    # 제목·본문이 4단어 이하로 짧으면 그 안의 한 단어 근거도 허용합니다(규칙 v3).
    assert parse("powerful", title="Very powerful!").labels[0].evidence_span == "powerful"
    # 사람 정답은 한 단어 근거를 허용하되 단어 경계는 똑같이 검사합니다.
    assert parse("volume", min_words=1).labels[0].evidence_span == "volume"
    with pytest.raises(EvidenceValidationError):
        parse("olume", min_words=1)


@real_data
def test_product_month_selection_includes_every_eligible_review() -> None:
    with SessionLocal() as session:
        ids = product_month_review_ids(
            session,
            "amazon-B087H2LWWZ",
            ["2022-01", "2022-02"],
        )
        reviews = [session.get(Review, review_id) for review_id in ids]

    assert len(ids) == 233
    assert len(ids) == len(set(ids))
    months = [
        month_bounds_label(review.reviewed_at) for review in reviews if review is not None
    ]
    assert set(months) == {"2022-01", "2022-02"}
    assert all(review is not None and review.eligible for review in reviews)
    # 중간에 멈춰도 한 달만 끝나지 않도록 두 달을 번갈아 처리합니다(2월 67건이 먼저 소진).
    assert months[:134] == ["2022-01", "2022-02"] * 67
    # 월 안에서도 날짜순이 아니어야 월초 리뷰에 치우치지 않습니다.
    january = [review.reviewed_at for review in reviews if review is not None][:134:2]
    assert january != sorted(january)
    # 같은 입력이면 순서는 항상 같습니다.
    with SessionLocal() as session:
        again = product_month_review_ids(session, "amazon-B087H2LWWZ", ["2022-02", "2022-01"])
    assert again == ids


def month_bounds_label(value) -> str:
    return value.astimezone(UTC).strftime("%Y-%m")
