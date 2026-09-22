# ReviewShift

상품을 검색하거나 카테고리로 찾아 들어가 월별 리뷰 변화를 비교하는 서비스다. 현재 가이드의 단계 0·1과 단계 2의 실제 Amazon 데이터 조사·선정·적재까지 구현되어 있다.

## 현재 구현

- FastAPI 상품 검색·카테고리·상세·리뷰·기간 비교 API
- PostgreSQL 17 + pgvector 0.8.6, SQLAlchemy, Alembic
- Streamlit 상품 목록·상세·월별 리뷰 수·평균 별점·리뷰 원문 화면
- 합성 fixture 3개 상품과 별도로 관리되는 실제 Amazon Appliances 상품 3개
- 실제 상품 7,801개 리뷰(선정한 각 12개월, 정확 중복 제거 후)
- 실제 데이터는 분류 라벨이 없으며 항목별 불만률을 `분석 전`으로 표시
- AI 질문은 미구현 상태이며 가짜 응답을 만들지 않음

API 계약은 [docs/API_CONTRACT.md](docs/API_CONTRACT.md), 데이터 조사 내용은 [docs/data_audit.md](docs/data_audit.md)를 참고한다.

## 준비 환경

- Windows 64-bit, Python 3.12
- Docker Desktop + WSL 2
- PostgreSQL 17 + pgvector 0.8.6

PowerShell에서 프로젝트 루트로 이동해 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d db
.\.venv\Scripts\alembic.exe -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_fixtures
```

`.env`에는 실제 비밀 값을 저장할 수 있으므로 Git에 포함하지 않는다.

## 실제 Appliances 데이터 준비

건조 실행으로 정확한 대상과 크기를 먼저 확인한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.download_amazon_appliances
```

명시적으로 다운로드하고 전체 데이터를 프로파일링한 뒤 선정된 상품만 적재한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.download_amazon_appliances --execute
.\.venv\Scripts\python.exe -m scripts.profile_amazon_appliances
.\.venv\Scripts\python.exe -m scripts.import_amazon_appliances
```

다운로드 대상은 고정 리비전의 Parquet 3개, 총 488,307,356바이트다. 원본과 조사 산출물은 `data/` 아래에 저장되고 Git으로 추적하지 않는다. 가져오기는 동일 입력으로 다시 실행해도 리뷰가 중복 저장되지 않는다.

## 실행

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

브라우저에서 `http://127.0.0.1:8501`을 열고 `실제 Amazon 데이터`를 선택한다. 다른 PC에 공개하는 배포 설정은 이번 단계의 범위가 아니다.

## 검증

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe -c backend/alembic.ini check
.\.venv\Scripts\python.exe -m pytest -q
```

## 아직 하지 않은 작업

- LLM 기반 항목·극성 분류
- RAG, Agent, AI 질문 API
- React 전환
- 전체 Amazon 데이터 수집이나 모델 가중치 다운로드
- 외부 공개 배포와 운영 보안 설정

