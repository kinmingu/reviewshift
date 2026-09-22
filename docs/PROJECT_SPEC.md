# ReviewShift 프로젝트 명세

원본 설계는 루트의 `REVIEW_SHIFT_PROJECT_GUIDE.md`를 기준으로 한다. 이 문서는 구현 중 반드시 지킬 핵심 범위만 요약한다.

## 목표

판매자와 상품 담당자가 상품별 고객 리뷰의 월간 변화를 확인하는 서비스다. 건수와 비율은 PostgreSQL의 실제 집계로 계산하고, 모든 설명은 실제 리뷰 ID와 연결한다.

## 단계별 구조

- UI: Streamlit. 화면 상태와 FastAPI HTTP 호출만 담당한다.
- API: FastAPI와 Pydantic. 입력 검증과 서비스 진입점을 담당한다.
- 업무 로직: repository/service 계층에서 상품 조회와 기간 비교를 수행한다.
- 저장소: PostgreSQL 17 + pgvector 0.8.6, SQLAlchemy, Alembic.
- 후속 AI: 실제 데이터 확보와 분류 검증 뒤 BGE-M3, Qwen, LangGraph 후보를 별도 평가한다.

## 구현된 범위

단계 0과 단계 1이 구현되어 있다. Python/Docker/PostgreSQL 환경, 관계 모델과 초기 마이그레이션, 결정적 fixture, 상품 탐색·상세·리뷰·월간 비교 API, HTTP 전용 Streamlit 화면과 기본 테스트를 제공한다.

현재 분석 실행은 `fixture-analysis-v1`, 데이터 버전은 `fixture-2026-09-v1`이다. 라벨은 사전에 작성한 합성 테스트 값이며 LLM 결과가 아니다. 실제 Amazon 데이터, 모델 가중치, RAG, Agent, React는 아직 다운로드하거나 구현하지 않는다.

## 단계 1 데이터 모델

- `products`: 출처·fixture 상태·상품명·카테고리·메타데이터
- `reviews`: 원천 중복 방지 키·원문·별점·UTC 작성일·분석 가능 여부
- `analysis_runs`: 데이터·모델·프롬프트·라벨 스키마 버전
- `review_labels`: 항목·세부 라벨·평가·실제 원문 근거·분석 실행

임베딩·월간 materialized 통계·보고서·피드백 테이블은 해당 후속 단계 전에는 만들지 않는다.

## 데이터 원칙

- fixture와 실제 데이터를 API와 화면에서 명확히 구분한다.
- 리뷰가 없는 달은 0%가 아니라 데이터 없음으로 처리한다.
- 언급률은 고유 리뷰 수를 기준으로 계산하며 같은 라벨의 중복 집계를 막는다.
- 월 범위는 UTC의 `[월초, 다음 월초)`로 계산한다.
- 데이터 원문, 모델 파일, 비밀 설정은 Git에 포함하지 않는다.
