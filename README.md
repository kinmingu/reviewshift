# ReviewShift

상품을 검색하거나 카테고리로 찾아 들어가 월별 리뷰 변화를 비교하는 서비스다. 현재 가이드의
단계 0·1, 실제 Amazon 데이터 조사·선정·적재, 영어 원문 기반 항목별 감성 분류와 기간 비교
기능까지 구현되어 있다.

## 현재 구현

- FastAPI 상품 검색·카테고리·상세·리뷰·기간 비교 API
- PostgreSQL 17 + pgvector 0.8.6, SQLAlchemy, Alembic
- Streamlit 상품 목록·상세·월별 리뷰 수·평균 별점·리뷰 원문 화면
- 합성 fixture 3개와 별도로 관리되는 실제 Amazon 상품 17개
- 공식 7개 카테고리에서 각각 2개씩 총 14개, 정확 중복 제거 리뷰 5,224건
- 기존 Appliances 검증 상품 3개와 리뷰 7,801건은 보존하되 기본 14개 목록에서는 분리
- 14개 상품의 한국어 표시명·요약 설명과 제품별 리뷰 수·원천 평균 평점 표시
- 영어 원문 상품명·설명·리뷰는 보존하고 화면에서 원문임을 명시
- 영어 리뷰 원문 기반 항목별 감성 분류, 실행 재개·실패 재시도·버전 분리 저장
- 고정 70건 v1 실제 모델 시험 완료: 구조·근거 검증 성공 68건, 실패 2건
- 의심 사례를 반영한 v3 고정 개발 14건 시험 완료: 구조·근거 최종 통과 14건
- 일반 상품 화면과 분리된 140건 사람 검토 화면, 저장·재개·CSV 내보내기
- 실제 분류가 끝난 범위만 처리율과 항목별 긍정·부정 비율을 표시하고, 나머지는 `분석 전` 또는 `진행 중`으로 표시
- AI 질문은 미구현 상태이며 가짜 응답을 만들지 않음

API 계약은 [docs/API_CONTRACT.md](docs/API_CONTRACT.md), 데이터 조사 내용은 [docs/data_audit.md](docs/data_audit.md)를 참고한다.
분류 체계는 [docs/analysis_taxonomy.md](docs/analysis_taxonomy.md), 실제 모델 시험은
[docs/analysis_trial.md](docs/analysis_trial.md), 사람 검토 방법은
[docs/human_evaluation_guide.md](docs/human_evaluation_guide.md)를 참고한다. 의미 오류 점검은
[docs/analysis_semantic_audit.md](docs/analysis_semantic_audit.md)에 별도로 기록했다.

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
.\.venv\Scripts\python.exe -m scripts.seed_human_evaluation
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
사람 검토는 왼쪽 사이드바의 `개발·평가 화면`을 켜서 연다. 모델 예측은 검토 완료 저장
전까지 숨겨지며, 검토 내용은 PostgreSQL에 저장되어 중단 후 이어갈 수 있다.

## 검증

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe -c backend/alembic.ini check
.\.venv\Scripts\python.exe -m pytest -q
```

## 아직 하지 않은 작업

- 사람 정답 140건 기반 분류 정확도·F1 평가
- 전체 5,224건 항목별 감성 분류와 전체 리뷰 선행 번역
- RAG, Agent, AI 질문 API
- React 전환
- 전체 Amazon 데이터 수집이나 모델 가중치 다운로드
- 외부 공개 배포와 운영 보안 설정

## 7개 카테고리 수집 도구

카테고리별 원천 파일의 정확한 크기와 고정 revision은
[`docs/category_collection_plan.md`](docs/category_collection_plan.md)에 기록되어 있다. 대용량 자료를
먼저 dry-run으로 확인한 뒤 승인된 7개 카테고리 전체를 다운로드·검증했다.

```powershell
# 파일 수와 예상 용량만 확인(카테고리 키를 바꿔 실행)
.\.venv\Scripts\python.exe -m scripts.download_amazon_category --category Electronics

# 중단 시 이어받기, 파일 4개 병렬 다운로드, 완료 파일 SHA-256 검증
.\.venv\Scripts\python.exe -m scripts.download_amazon_category --category Electronics --execute --workers 4

# 전체 리뷰에서 연속 3개월 조건을 만족하는 상품 후보 생성
.\.venv\Scripts\python.exe -m scripts.profile_amazon_category --category Electronics

# 검토해 선정 파일을 작성한 뒤 카테고리당 2개를 PostgreSQL에 중복 없이 적재
.\.venv\Scripts\python.exe -m scripts.import_amazon_category --category Electronics
```

화면의 상품 카드에는 제품별 저장 리뷰 수가, 상세 화면에는 월별 리뷰 수와 평균 별점이
DB 집계 결과로 표시된다. 원본 파일, 프로파일 결과, 다운로드 manifest는 `data/` 아래에만
저장되며 Git으로 추적하지 않는다.

상품명·요약 설명·카테고리 UI는 한국어다. 실제 리뷰 제목과 본문은 현재 영어 원문이며
설치된 Ollama 모델로 생성한 번역은 별도 DB 필드에 캐시해 `자동 번역`으로 표시하고 영어
원문을 함께 제공한다. CPU에서는 오래 걸리므로 기본 명령은 10건만 처리한다.

```powershell
# 안전한 소량 실행(기본 10건)
.\.venv\Scripts\python.exe -m scripts.translate_reviews --model qwen3.5:latest

# 특정 카테고리의 남은 리뷰 전체 처리(장시간 실행)
.\.venv\Scripts\python.exe -m scripts.translate_reviews --category Electronics --all
```

## 항목별 감성 분류

분류 입력에는 영어 리뷰 제목과 본문을 사용하며 별점은 넣지 않는다. 한 리뷰에서 여러 항목을 추출할 수 있고, 각 항목은 `긍정`, `부정`, `중립`, `판단 불가`로 구분한다. 결과에는 원문에 실제로 존재하는 근거 구간과 모델·프롬프트·분류 체계 버전이 함께 저장된다.

```powershell
# 카테고리별 10건, 총 70건의 고정 시험 표본 생성
.\.venv\Scripts\python.exe -m scripts.prepare_analysis_evaluation

# 프롬프트 개발용 고정 14건 v3 시험. 활성 월별 통계 버전은 바꾸지 않는다.
.\.venv\Scripts\python.exe -m scripts.classify_reviews `
  --run-id amazon-absa-qwen35-v3 `
  --sample-file config/analysis_dev_14.json `
  --max-attempts 2 --timeout 300 `
  --output data/evaluation/dev14_v3

# 실패 건만 제한 횟수 안에서 다시 시도한다.
.\.venv\Scripts\python.exe -m scripts.classify_reviews `
  --run-id amazon-absa-qwen35-v3 `
  --sample-file config/analysis_dev_14.json `
  --retry-failed --max-attempts 2 `
  --output data/evaluation/dev14_v3
```

사람 검토용 블라인드 파일은 `data/evaluation/human_review_blind_140.csv`, 기존 v1 시험 예측은
`data/evaluation/trial_70_predictions.csv`, v3 개발 비교는
`data/evaluation/dev14_comparison.csv`에 생성된다. 사람 정답을 작성하기 전에는 정확도나 F1을
계산하지 않는다.

우선 두 달 분석 후보는 결과를 보고 고른 것이 아니라, 공식 14개 상품 중 인접한 두 달 모두
30건 이상인 조합을 SQL로 집계해 합계가 가장 작은 조합으로 정했다. 현재 후보는
`amazon-B087H2LWWZ`의 2022-01 166건과 2022-02 67건, 총 233건이다. v3 개발 시험 1건은
재사용 가능하고 새로 처리할 리뷰는 232건이다. 아래 명령은 준비만 했으며 아직 실행하지 않았다.

```powershell
.\.venv\Scripts\python.exe -m scripts.classify_reviews `
  --run-id amazon-absa-qwen35-v3 `
  --product-id amazon-B087H2LWWZ `
  --month 2022-01 --month 2022-02 `
  --max-attempts 2 --timeout 300 --activate `
  --output data/evaluation/product_B087H2LWWZ_2022-01_2022-02
```

전체 5,224건 분류는 소량 시험의 처리 시간과 실패 원인을 먼저 확인한 뒤 사용자 승인을 받아 아래 명령으로 실행한다. 현재 작업에서는 실행하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m scripts.classify_reviews `
  --model qwen3.5:latest --run-id amazon-absa-qwen35-v3 --all --activate
```
