from pathlib import Path

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_catalog_and_product_detail_smoke(monkeypatch, live_api_url: str) -> None:
    monkeypatch.setenv("API_BASE_URL", live_api_url)
    page = AppTest.from_file(
        str(PROJECT_ROOT / "frontend_streamlit" / "app.py"), default_timeout=30
    ).run()

    assert not page.exception
    assert not page.error
    assert page.title[0].value == "ReviewShift"

    page.radio[0].set_value("합성 테스트 데이터").run(timeout=30)
    assert any("합성 테스트 데이터" in warning.value for warning in page.warning)
    assert len(page.button) == 3

    page.button[0].click().run(timeout=30)
    assert not page.exception
    assert not page.error
    assert page.title[0].value == "AeroBrew 12-Cup Coffee Maker"
    assert len(page.dataframe) == 2
    assert any("AI 질문은 아직 구현하지 않았습니다" in info.value for info in page.info)


def test_real_catalog_detail_shows_monthly_data_and_analysis_pending(
    monkeypatch, live_api_url: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", live_api_url)
    page = AppTest.from_file(
        str(PROJECT_ROOT / "frontend_streamlit" / "app.py"), default_timeout=30
    ).run()

    assert not page.exception
    assert not page.error
    assert any("실제 공개 배포 데이터" in info.value for info in page.info)
    assert len(page.button) == 14

    page.selectbox[0].set_value("Home_and_Kitchen").run(timeout=30)
    assert len(page.button) == 2
    page.button[0].click().run(timeout=30)
    assert not page.exception
    assert not page.error
    assert page.title[0].value.startswith("임프레사 커피머신")
    assert len(page.dataframe) >= 2
    analysis_messages = [
        item.value for item in [*page.warning, *page.info, *page.success]
    ]
    assert any("항목별 분석 상태:" in value for value in analysis_messages)
    assert any("항목 분류:" in caption.value for caption in page.caption)
    assert any("영어 원문" in info.value for info in page.info)


def test_electronics_catalog_shows_each_product_review_count(
    monkeypatch, live_api_url: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", live_api_url)
    page = AppTest.from_file(
        str(PROJECT_ROOT / "frontend_streamlit" / "app.py"), default_timeout=30
    ).run()

    page.selectbox[0].set_value("Electronics").run(timeout=30)
    assert not page.exception
    assert not page.error
    review_metrics = [
        metric for metric in page.metric if metric.label == "제품별 저장 리뷰 수"
    ]
    assert len(review_metrics) == 2
    assert {metric.value for metric in review_metrics} == {"373건"}
    source_rating_metrics = [
        metric for metric in page.metric if metric.label == "원천 전체 평균 평점"
    ]
    assert len(source_rating_metrics) == 2

    page.button[0].click().run(timeout=30)
    assert page.title[0].value.startswith("알로 에센셜 스포트라이트")
    assert any(
        metric.label == "저장된 분석 대상 리뷰 수" and metric.value == "373건"
        for metric in page.metric
    )
    assert any(
        metric.label == "원천 평점 등록 수" and metric.value == "12,890건"
        for metric in page.metric
    )
    assert len(page.dataframe) >= 2


def test_human_evaluation_screen_is_separate_and_blind(
    monkeypatch, live_api_url: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", live_api_url)
    page = AppTest.from_file(
        str(PROJECT_ROOT / "frontend_streamlit" / "app.py"), default_timeout=30
    ).run()

    page.toggle[0].set_value(True).run(timeout=30)
    assert not page.exception
    assert not page.error
    assert page.title[0].value == "리뷰 분류 사람 검토"
    assert any("모델 예측은 사람이 정답" in item.value for item in page.warning)
    assert any("리뷰 ID:" in item.value for item in page.caption)
    assert any(item.label == "언급된 평가 항목(복수 선택)" for item in page.multiselect)
    assert not any("정답 저장 후 모델 예측 비교" in item.value for item in page.subheader)
