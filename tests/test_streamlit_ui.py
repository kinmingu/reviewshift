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
    assert any("합성 테스트 데이터" in warning.value for warning in page.warning)
    assert len(page.button) == 3

    page.button[0].click().run(timeout=30)
    assert not page.exception
    assert not page.error
    assert page.title[0].value == "AeroBrew 12-Cup Coffee Maker"
    assert len(page.dataframe) == 1
    assert any("AI 질문은 아직 구현되지 않았습니다" in info.value for info in page.info)

