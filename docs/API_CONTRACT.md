# ReviewShift API 계약

기본 경로는 `/api/v1`이다. 모든 목록 응답과 레코드는 `source_mode`가 `fixture` 또는 `real`인지 명시한다.

## GET `/health`

API와 DB 연결 상태를 반환한다.

## GET `/api/v1/categories`

쿼리:

- `source_mode`: `fixture|real`, 생략 시 서버 기본값

선택한 출처에 존재하는 카테고리만 반환한다.

## GET `/api/v1/products`

쿼리:

- `query`: 상품명 또는 parent_asin 부분 검색
- `category`: 정확한 카테고리
- `source_mode`: `fixture|real`, 생략 시 서버 기본값
- `page`, `page_size`

fixture와 실제 데이터는 한 목록에서 섞이지 않는다.

## GET `/api/v1/products/{product_id}`

상품 메타데이터, 저장된 전체 리뷰 수, 사용 가능한 월과 `monthly_stats`를 반환한다. `monthly_stats`의 각 항목은 다음을 포함한다.

- `month`: `YYYY-MM`
- `review_count`: DB의 적격·중복 제거 리뷰 수
- `average_rating`: DB 리뷰 별점 평균

## GET `/api/v1/products/{product_id}/reviews`

쿼리:

- `month`: 필수 `YYYY-MM`
- `aspect`, `polarity`: fixture 분류 결과 필터(선택)
- `page`, `page_size`

실제 리뷰는 `labels: []`로 반환한다. 이는 불만 0건이나 정상 판정이 아니라 아직 분류하지 않았다는 뜻이다.

## GET `/api/v1/products/{product_id}/comparison`

쿼리:

- `target_month`, `baseline_month`: 필수 `YYYY-MM`

`coverage`에는 두 월의 리뷰 수, 분류된 리뷰 수, 평균 별점이 포함된다. 실제 상품은 현재 `status: insufficient_data`, `issues: []`, `analysis_version: not-analyzed`를 반환한다. 실제 리뷰의 수와 평균 별점은 DB에서 계산하지만 항목별 불만률은 분류 전이므로 만들지 않는다.

