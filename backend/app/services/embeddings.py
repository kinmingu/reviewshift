"""리뷰 임베딩 생성(Ollama bge-m3)과 의미 검색 서비스.

- 임베딩 입력은 영어 리뷰 제목과 본문입니다(번역문은 쓰지 않음).
- 검색은 반드시 상품과 월(기간)을 지정해야 합니다. 전체 DB 대상 검색은 하지 않습니다.
- 모델 서버 오류·시간 초과·잘못된 응답은 EmbeddingError로 명확히 알립니다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import requests

from backend.app.models.domain import EMBEDDING_DIMENSIONS

EMBEDDING_MODEL = "bge-m3"


# 임베딩 모델(Ollama) 호출이 실패했을 때의 오류.
class EmbeddingError(RuntimeError):
    pass


# === [임베딩 입력] 원문이 바뀌면 content_hash가 달라져 다시 계산합니다 ===
def embedding_text(title: str | None, text: str) -> str:
    return f"{title or ''}\n{text}".strip()


# 리뷰 본문의 해시. 본문이 바뀌면 임베딩을 다시 만들기 위해 씁니다.
def content_hash(title: str | None, text: str) -> str:
    return hashlib.sha256(embedding_text(title, text).encode("utf-8")).hexdigest()


# === [Ollama 임베딩 클라이언트] ===
@dataclass
class OllamaEmbedder:
    model: str = EMBEDDING_MODEL
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120

    # 문장 목록을 Ollama bge-m3로 보내 1024차원 벡터 목록을 받습니다.
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/api/embed",
                json={"model": self.model, "input": texts, "keep_alive": "30m"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload: Any = response.json()
        except requests.Timeout as exc:
            raise EmbeddingError(f"임베딩 모델 응답 시간 초과({self.timeout_seconds}초)") from exc
        except (requests.RequestException, ValueError) as exc:
            raise EmbeddingError(f"임베딩 모델 요청 실패: {exc}") from exc
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError("임베딩 응답 개수가 입력과 다릅니다.")
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError(
                    f"임베딩 차원이 {EMBEDDING_DIMENSIONS}이 아닙니다: "
                    f"{len(vector) if isinstance(vector, list) else type(vector).__name__}"
                )
        return [[float(value) for value in vector] for vector in vectors]

    def model_digest(self) -> str | None:
        """재현성을 위해 설치된 모델의 digest를 기록합니다(조회 실패 시 None)."""
        try:
            response = requests.get(f"{self.base_url.rstrip('/')}/api/tags", timeout=10)
            response.raise_for_status()
            for item in response.json().get("models", []):
                if item.get("name") in (self.model, f"{self.model}:latest"):
                    return item.get("digest")
        except (requests.RequestException, ValueError):
            return None
        return None
