# ReviewShift 단계 1 API 계약

기본 주소는 `http://localhost:8000`, API prefix는 `/api/v1`이다. 모든 상품·리뷰 응답은 현재 `source_mode: fixture`로 표시된다.

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 프로세스와 DB 연결 상태 |
| GET | `/api/v1/categories` | 준비된 카테고리 목록 |
| GET | `/api/v1/products` | `query`, `category`, `page`, `page_size` 상품 검색 |
| GET | `/api/v1/products/{id}` | 상품 정보와 실제 데이터에 존재하는 월 |
| GET | `/api/v1/products/{id}/comparison` | `target_month`, `baseline_month` 월간 비교 |
| GET | `/api/v1/products/{id}/reviews` | `month`, 선택적 `aspect`, `polarity`, pagination |

월 형식은 `YYYY-MM`이며 범위는 UTC 기준 `[월초, 다음 월초)`다. 존재하지 않는 상품은 404, 잘못된 입력은 422다. 리뷰가 없거나 분류가 덜 된 월은 성공 응답 안에 `status: insufficient_data`, 빈 `issues`와 실제 coverage를 반환한다.

비율은 0~1이고 `change_pp`만 퍼센트포인트다. 집계는 분석 가능 리뷰 분모와 `COUNT(DISTINCT review_id)`를 사용한다. 응답의 `evidence_review_ids`는 실제 fixture 리뷰 ID다.

`POST /api/v1/chat`은 단계 1 범위가 아니므로 제공하지 않는다. Streamlit에도 미구현 상태로 표시하며 가짜 답변을 만들지 않는다.

