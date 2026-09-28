"""리뷰 번역기: 로컬 LLM으로 영어 리뷰를 한국어로 번역합니다(결과는 리뷰에 캐시)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

PROMPT_VERSION = "review-translation-ko-v1"
SYSTEM_PROMPT = """Translate the Amazon review title and body from English to natural Korean.
Preserve negation, numbers, units, durations, product/brand names, failures, side effects,
and uncertainty. Do not summarize, omit details, or add claims. Return only a JSON object
with title_ko and text_ko strings. The translation is a reference; the English text remains
the authoritative source."""


# 번역된 제목과 본문.
@dataclass(frozen=True)
class TranslationResult:
    title_ko: str
    text_ko: str


class TranslationError(RuntimeError):
    """로컬 번역 모델 호출 또는 응답 검증 실패입니다."""


def _normalized_numbers(value: str) -> list[str]:
    """쉼표 표기 차이는 허용하되 원문의 숫자가 번역에서 사라졌는지 검사합니다."""
    return re.findall(r"\d+(?:\.\d+)?", value.replace(",", ""))


# 모델 응답 JSON에서 번역문을 꺼내고 비어 있지 않은지 확인합니다.
def parse_translation(content: str, original_title: str, original_text: str) -> TranslationResult:
    payload: Any = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("번역 응답이 JSON 객체가 아닙니다.")
    title_ko = str(payload.get("title_ko") or "").strip()
    text_ko = str(payload.get("text_ko") or "").strip()
    if not title_ko or not text_ko:
        raise ValueError("번역 응답의 title_ko 또는 text_ko가 비어 있습니다.")

    # 자동 검사는 최소 안전망입니다. 부정어·고장·부작용 의미는 별도 사람 표본 검토가 필요합니다.
    source_numbers = _normalized_numbers(f"{original_title} {original_text}")
    translated_numbers = _normalized_numbers(f"{title_ko} {text_ko}")
    missing = [number for number in source_numbers if number not in translated_numbers]
    if missing:
        raise ValueError(f"번역에서 원문 숫자가 누락됐습니다: {missing}")
    return TranslationResult(title_ko=title_ko, text_ko=text_ko)


# [번역기] Ollama 모델에 번역을 요청합니다.
class OllamaReviewTranslator:
    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    # 제목·본문을 번역해 돌려줍니다(모델 오류는 TranslationError).
    def translate(self, title: str | None, text: str) -> TranslationResult:
        original_title = title or ""
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": "json",
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"title": original_title, "text": text},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            return parse_translation(content, original_title, text)
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise TranslationError(str(exc)) from exc
