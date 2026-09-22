# ReviewShift

상품을 검색하거나 카테고리로 탐색하고, 두 완료 월의 리뷰 평가 변화를 실제 근거 리뷰와 함께 비교하는 서비스다. 현재 **단계 0과 단계 1**이 구현되어 있다.

현재 데이터는 전부 합성 fixture다. 화면과 API의 `source_mode`가 이를 명시하며 실제 Amazon 데이터나 AI 분석 결과가 아니다.

## 구현 범위

- FastAPI 상품 검색·카테고리·상세·리뷰·월간 비교 API
- PostgreSQL 17 + pgvector 0.8.6, SQLAlchemy 모델과 Alembic 마이그레이션
- 상품 3개, 2025-01/2025-02 리뷰 36개, 사전 라벨 43개의 멱등 fixture seed
- `COUNT(DISTINCT review_id)`와 실제 월 분모를 사용하는 SQL 집계
- Streamlit 상품 카드·상세·월 선택·비교표·근거 리뷰 화면
- 분모 0, 과거 건수 0, 중복 라벨, 404/422, 검색/pagination 테스트
- AI 질문은 미구현 상태로 표시

API 계약은 [docs/API_CONTRACT.md](docs/API_CONTRACT.md), 설계 원칙은 [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)를 참고한다.

## 준비된 환경

- Windows 64-bit, Python 3.12.10
- WSL 2.7.14, Docker Desktop 4.91.0
- PostgreSQL 17.11 + pgvector 0.8.6

## 처음 실행

PowerShell에서 프로젝트 루트를 기준으로 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

이미 `.venv`와 `.env`가 있으면 다시 만들 필요가 없다. `.env`의 기본 암호는 로컬 개발 전용이며 공유·배포 환경에서는 변경해야 한다.

DB를 시작하고 스키마와 fixture를 준비한다.

```powershell
docker compose up -d db
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_fixtures
```

seed는 같은 ID를 갱신하므로 여러 번 실행해도 상품·리뷰·라벨 중복이 생기지 않는다.

## 서버 실행

첫 번째 PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

- API 문서: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

두 번째 PowerShell:

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend_streamlit\app.py --server.address 127.0.0.1 --server.port 8501
```

- 화면: `http://127.0.0.1:8501`

## 검사와 테스트

Docker DB가 실행 중이어야 한다. 테스트는 Alembic을 head까지 적용하고 결정적 fixture를 다시 seed한다.

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe -c backend/alembic.ini check
.\.venv\Scripts\python.exe -m pytest -q
```

## 운영 명령

```powershell
docker compose ps
docker compose stop db
docker compose start db
```

Docker 볼륨 삭제는 로컬 DB 데이터를 제거하므로 일반 실행 절차에 포함하지 않는다.

## 현재 한계

- 실제 Amazon 데이터, 임베딩, RAG, Agent, React는 구현하지 않았다.
- `POST /api/v1/chat`은 제공하지 않으며 UI의 질문 입력도 비활성화되어 있다.
- fixture의 사전 라벨은 모델 예측이 아니며 성능 측정값으로 사용할 수 없다.
- 로컬 PC 자원상 Qwen3-14B는 제외한다. 모델 선택은 실제 데이터 분류 단계에서 별도 검증한다.

