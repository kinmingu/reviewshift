"""번역 응답 파싱 테스트: 한국어 번역 유지, 원문 숫자 보존, 빈 값 거부."""

import json

import pytest

from backend.app.services.review_translation import parse_translation


def test_translation_parser_keeps_korean_text_and_source_numbers() -> None:
    content = json.dumps(
        {
            "title_ko": "12롤 세트",
            "text_ko": "2주 동안 사용했고 별점은 5점입니다.",
        },
        ensure_ascii=False,
    )

    result = parse_translation(
        content,
        original_title="12 roll pack",
        original_text="Used it for 2 weeks and rated it 5 stars.",
    )

    assert result.title_ko == "12롤 세트"
    assert result.text_ko.startswith("2주")


def test_translation_parser_rejects_missing_source_number() -> None:
    content = json.dumps(
        {"title_ko": "충전기", "text_ko": "빠르게 충전됩니다."},
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="숫자가 누락"):
        parse_translation(
            content,
            original_title="20W charger",
            original_text="Charges quickly.",
        )


def test_translation_parser_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="비어 있습니다"):
        parse_translation('{"title_ko": "", "text_ko": "번역"}', "Title", "Text")
