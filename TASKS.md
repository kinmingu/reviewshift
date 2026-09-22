# ReviewShift 작업 현황

기준일: 2026-09-22

## 단계 0 — 환경과 범위

- [x] 원본 가이드와 저장소 상태 확인
- [x] Windows 및 Python 3.12 확인
- [x] 프로젝트 로컬 `.venv` 생성
- [x] 단계 1용 Python 의존성 설치와 버전 고정
- [x] PostgreSQL 17 + pgvector 0.8.6 Compose 구성 작성
- [x] `.env.example`, `.gitignore`, 프로젝트 규칙 작성
- [x] WSL 2.7.14 및 Linux 커널 6.18 설치
- [x] Docker Desktop 4.91.0 설치, Docker 엔진/CLI/Compose 확인
- [x] PostgreSQL 17 + pgvector 0.8.6 이미지 다운로드 및 DB health check
- [x] PostgreSQL `vector` 확장 활성화 확인
- [x] RAM/CPU/GPU 상세 확인

## 단계 1 — 세로 연결

- [x] FastAPI/schema/model/repository/service 디렉터리와 설정 구성
- [x] Alembic 초기 마이그레이션과 `vector` 확장 활성화
- [x] 합성 상품 3개 및 두 달치 fixture 리뷰/라벨 seed
- [x] 조회·비교·리뷰 API 구현
- [x] Streamlit HTTP 클라이언트와 핵심 화면 구현
- [x] 통계·API·Streamlit 기본 테스트 작성
- [x] seed 재실행 후 상품 3·리뷰 36·라벨 43 유지 확인
- [x] Ruff, Alembic schema check, pytest 통과

## 다음 단계 — 단계 2 실제 데이터 조사

- [ ] Amazon Reviews 2023 원천 파일·압축 크기·이용 조건 확인
- [ ] 제한된 샘플로 스키마와 timestamp 단위 검증
- [ ] 후보 상품별 월간 리뷰 수 조사 및 `docs/data_audit.md` 작성
- [ ] 큰 다운로드 전에 범위·용량·예상 시간을 제시하고 승인 확인
- [ ] 승인된 상품 3개만 멱등적으로 가져오고 fixture와 분리

## 이번에 제외

- 실제 Amazon 데이터 및 대용량 원본 다운로드
- BGE-M3/Qwen 모델 가중치, RAG, LangGraph Agent
- React UI, 외부 배포, 유료 API

## 확인된 개발 PC

- CPU: AMD Ryzen 5 5500U, 6코어/12스레드
- RAM: 13.8GB
- GPU: AMD Radeon Graphics, 표시 메모리 2GB
- 판단: Qwen3-14B 로컬 실행에는 부적합하며 8B도 메모리와 속도 검증이 필요하다. 단계 3 전에는 모델 가중치를 받지 않는다.
