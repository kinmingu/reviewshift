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
    assert len(page.button) == 3

    page.button[0].click().run(timeout=30)
    assert not page.exception
    assert not page.error
    assert page.title[0].value.startswith("12 Pack Keurig Filter Replacement")
    assert len(page.dataframe) == 1
    assert any("항목별 불만률: 분석 전" in warning.value for warning in page.warning)
    assert any("항목 분류: 분석 전" in caption.value for caption in page.caption)
