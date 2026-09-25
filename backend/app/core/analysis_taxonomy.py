from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import PROJECT_ROOT

TAXONOMY_PATH = PROJECT_ROOT / "config" / "review_analysis_taxonomy.json"


@lru_cache
def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("version") or not payload.get("common"):
        raise ValueError("분류 체계에 version과 common 항목이 필요합니다.")
    return payload


def category_labels(category: str) -> dict[tuple[str, str], dict[str, str]]:
    taxonomy = load_taxonomy()
    groups = [*taxonomy["common"], *taxonomy["categories"].get(category, [])]
    result: dict[tuple[str, str], dict[str, str]] = {}
    for group in groups:
        for detail in group["details"]:
            result[(group["aspect_code"], detail["detail_code"])] = {
                "aspect_name_ko": group["aspect_name_ko"],
                "detail_name_ko": detail["name_ko"],
                "include": detail["include"],
                "exclude": detail["exclude"],
            }
    return result


def compact_taxonomy_for_prompt(category: str) -> dict[str, str]:
    """코드는 JSON schema에도 있으므로 설명만 짧게 묶어 반복 토큰을 줄입니다."""
    return {
        f"{aspect}.{detail}": f"포함: {values['include']} / 제외: {values['exclude']}"
        for (aspect, detail), values in category_labels(category).items()
    }
