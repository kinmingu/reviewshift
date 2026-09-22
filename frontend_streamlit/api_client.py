import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class ApiError(RuntimeError):
    pass


class ReviewShiftClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (
            base_url or os.getenv("API_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

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

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def categories(self, source_mode: str = "fixture") -> dict[str, Any]:
        return self._get("/api/v1/categories", {"source_mode": source_mode})

    def products(
        self, query: str = "", category: str = "", source_mode: str = "fixture"
    ) -> dict[str, Any]:
        params = {"page": 1, "page_size": 100, "source_mode": source_mode}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        return self._get("/api/v1/products", params)

    def product(self, product_id: str) -> dict[str, Any]:
        return self._get(f"/api/v1/products/{product_id}")

    def comparison(
        self, product_id: str, target_month: str, baseline_month: str
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v1/products/{product_id}/comparison",
            {"target_month": target_month, "baseline_month": baseline_month},
        )

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
