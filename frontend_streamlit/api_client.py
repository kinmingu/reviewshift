"""Streamlit 화면이 백엔드 API를 부르는 HTTP 클라이언트.

Streamlit은 DB에 직접 접근하지 않고 이 클라이언트로만 데이터를 받습니다.
"""

import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


# API 호출 실패(연결 오류, 오류 응답)를 화면에 알리기 위한 오류.
class ApiError(RuntimeError):
    pass


# [API 클라이언트] 백엔드 주소(API_BASE_URL)로 요청을 보내고 JSON을 받습니다.
class ReviewShiftClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (
            base_url or os.getenv("API_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    # GET 요청을 보내고 JSON을 돌려줍니다(오류는 ApiError로 바꿈).
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            raise ApiError(f"API 오류 ({exc.response.status_code}): {detail}") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"API에 연결할 수 없습니다: {exc}") from exc
        return response.json()

    # GET 외 요청(PUT 등)을 JSON 본문과 함께 보냅니다.
    def _request_json(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=json_body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            raise ApiError(f"API 오류 ({exc.response.status_code}): {detail}") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"API에 연결할 수 없습니다: {exc}") from exc
        return response.json()

    # 서버·DB 상태 확인.
    def health(self) -> dict[str, Any]:
        return self._get("/health")

    # 카테고리 목록.
    def categories(self, source_mode: str = "fixture") -> dict[str, Any]:
        return self._get("/api/v1/categories", {"source_mode": source_mode})

    # 상품 목록(검색어·카테고리).
    def products(
        self, query: str = "", category: str = "", source_mode: str = "fixture"
    ) -> dict[str, Any]:
        params = {"page": 1, "page_size": 100, "source_mode": source_mode}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        return self._get("/api/v1/products", params)

    # 상품 상세.
    def product(self, product_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/products/{product_id}")

    # 두 달 비교 결과.
    def comparison(
        self, product_id: str, target_month: str, baseline_month: str
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v1/products/{product_id}/comparison",
            {"target_month": target_month, "baseline_month": baseline_month},
        )

    # 특정 달 리뷰 목록.
    def reviews(
        self,
        product_id: str,
        month: str,
        aspect: str | None = None,
        polarity: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"month": month, "page": 1, "page_size": 100}
        if aspect:
            params["aspect"] = aspect
        if polarity:
            params["polarity"] = polarity
        return self._get(f"/api/v1/products/{product_id}/reviews", params)

    # [사람 평가] 진행 현황.
    def evaluation_progress(self, dataset_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/evaluation/datasets/{dataset_id}/progress")

    # [사람 평가] N번째 평가 항목.
    def evaluation_item(self, dataset_id: str, position: int) -> dict[str, Any]:
        return self._get(
            f"/api/v1/evaluation/datasets/{dataset_id}/items/{position}"
        )

    # [사람 평가] 정답 라벨 저장.
    def save_evaluation(
        self, dataset_id: str, position: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request_json(
            "PUT",
            f"/api/v1/evaluation/datasets/{dataset_id}/items/{position}",
            payload,
        )

    # 리뷰 번역 요청(모델이 느려 시간 제한을 길게 둠).
    def translate_review(self, review_id: str) -> dict[str, Any]:
        try:
            response = self._client.post(
                f"/api/v1/reviews/{review_id}/translate", timeout=310.0
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(
                f"API 오류 ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"API에 연결할 수 없습니다: {exc}") from exc
        return response.json()

    # [사람 평가] 결과 CSV 파일 받기.
    def evaluation_export(self, dataset_id: str) -> bytes:
        try:
            response = self._client.get(
                f"/api/v1/evaluation/datasets/{dataset_id}/export"
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiError(
                f"API 오류 ({exc.response.status_code}): {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"API에 연결할 수 없습니다: {exc}") from exc
        return response.content
