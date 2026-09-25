# ReviewShift API 계약

기본 경로는 `/api/v1`이다. 모든 목록 응답과 레코드는 `source_mode`가 `fixture` 또는 `real`인지 명시한다.

## GET `/health`

API와 DB 연결 상태를 반환한다.

## GET `/api/v1/categories`

쿼리:

- `source_mode`: `fixture|real`, 생략 시 서버 기본값

`source_mode=real`은 프로젝트 대상으로 확정한 공식 7개 카테고리를 고정 순서로 반환한다.
기존 검증용 `Appliances` 데이터는 보존하지만 이 기본 카테고리 목록에는 포함하지 않는다.

## GET `/api/v1/products`

쿼리:

- `query`: 원문 상품명, 별도 한국어 표시 상품명 또는 parent_asin 부분 검색
- `category`: 정확한 카테고리
- `source_mode`: `fixture|real`, 생략 시 서버 기본값
- `page`, `page_size`

fixture와 실제 데이터는 한 목록에서 섞이지 않는다.
실제 데이터에서 카테고리를 생략하면 공식 7개 카테고리의 14개 상품만 반환한다. 기존
`Appliances` 3개는 `category=Appliances`를 명시했을 때 조회할 수 있다.
상품 항목의 `title`은 원문 상품명이고 `title_ko`는 별도로 준비된 한국어 표시명 또는 `null`이다.
`review_count`는 해당 제품에 실제 저장된 적격·중복 제거 리뷰 수다.
`source_average_rating`과 `source_rating_count`는 Amazon 원천 상품 메타데이터의 평균 평점과
평점 등록 수다. `source_rating_count`는 실제 구매 수나 판매량으로 해석하지 않는다.

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

리뷰는 활성 분석 버전의 `labels`와 `analysis_status`를 반환한다. `analysis_status=succeeded`인데
`labels: []`인 경우는 모델 호출이 정상 완료됐으나 명시적으로 분류할 항목이 없다는 뜻이다.
`not_started`, `pending`, `running`, `failed`를 0건 불만이나 정상 판정으로 해석하지 않는다.
영어 원문은 `title`, `text`에 항상 보존한다. 자동 번역이 완료된 리뷰는 `title_ko`,
`text_ko`, `translation_model`, `translation_prompt_version`, `translated_at`을 함께 반환하고,
미번역 리뷰의 해당 필드는 `null`이다. 번역문을 원문 인용으로 취급하지 않는다.

## GET `/api/v1/products/{product_id}/insights`

상품 상세 화면의 리뷰 리포트다. 모든 수치는 SQL 집계이며 LLM이 계산하지 않는다.

- `rating_distribution`: 저장된 적격 리뷰의 별점 1~5 건수, `average_rating`: 그 평균
- `analysis`: 상품 전체 기간의 활성 분석 처리 현황과 버전(`status`는 비교 API와 같은 규칙)
- `positive_review_share`, `negative_review_share`: 분석 성공 리뷰 중 긍정/부정 라벨이 하나 이상인
  리뷰 비율. 분석 성공 리뷰가 없으면 `null`
- `aspects`: 항목별 언급 리뷰 수와 극성별 리뷰 수·비율(분모 = 분석 성공 리뷰)
- `top_complaints`: 부정 리뷰 수 상위 3개 항목과 최신순 대표 근거(리뷰당 1개, 최대 3개)
- `monthly`: 월별 리뷰 수·평균 별점·분석 성공 수·긍정/부정 리뷰 비율
- `latest_change`: 인접한 마지막 두 달의 비교 결과. 기간을 결과를 보고 고르지 않는다. 부정 항목 중
  증가한 것만 증가폭 순으로 최대 3개. `is_provisional=true`이면 잠정 결과다.

상품 목록·상세의 상품 요약에는 `analyzed_review_count`, `positive_review_share`,
`negative_review_share`가 추가되었다(분석 전이면 0 / `null`).

## GET `/api/v1/products/{product_id}/search`

리뷰 의미 검색(RAG의 검색 단계). 상품과 기간을 반드시 지정한다.

- `q`: 필수, 1~300자. 한국어 질의로 영어 리뷰를 찾을 수 있다(bge-m3 다국어 임베딩).
- `month`: 필수 `YYYY-MM`, 여러 번 지정 가능. 지정한 월의 리뷰만 검색한다.
- `limit`: 1~30, 기본 8

응답 `items`는 코사인 유사도(`similarity = 1 - 거리`) 내림차순의 실제 저장 리뷰다.
`embedded_reviews / total_reviews`로 검색 기간의 임베딩 준비 정도를 알 수 있다.
검색어·월 누락이나 잘못된 월은 `422`, 없는 상품은 `404`, 임베딩 모델 오류·시간 초과는 `503`.

## GET `/api/v1/products/{product_id}/comparison`

쿼리:

- `target_month`, `baseline_month`: 필수 `YYYY-MM`
- `baseline_month`는 `target_month`보다 이전 달이어야 한다. 같은 달이거나 역순이면 `422`.

월별 분석 상태(`*_analysis_status`)는 다음과 같다.

- `complete`: 모든 리뷰가 성공 또는 최종 실패로 끝났고, 최종 실패 비율이
  `thresholds.max_failure_rate`(기본 0.05) 이하. 실패 리뷰는 비율 분모에서 빠지고 실패 수는
  `coverage`에 그대로 남는다.
- `partial_failure`: 모두 끝났지만 최종 실패 비율이 기준을 넘음
- `in_progress`: 대기·실행 중이거나 아직 처리하지 않은 리뷰가 있음(처리 중 실패 포함)
- `not_started`: 활성 분석 결과가 없음

`coverage`에는 두 월별 전체 리뷰, 라벨이 하나 이상인 리뷰, 성공·실패·진행 중·미처리 수,
성공 처리율, 평균 별점과 분석 상태가 포함된다. 성공에는 정상 빈 라벨 결과도 포함한다.

`issues`의 비율 분모는 전체 리뷰가 아니라 해당 월의 분류 성공 리뷰 수다. 동일 리뷰의 동일
항목·감성은 근거가 여러 개여도 SQL에서 한 번만 센다. 두 월 중 하나라도 완료 전이면
`is_provisional=true`, `signal_status=analysis_incomplete`이며 처리율을 함께 확인해야 한다.
미처리·실패 리뷰는 불만 없는 리뷰로 계산하지 않는다.

두 기간이 모두 완료된 경우에만 설정된 최소 성공 리뷰 수·최소 부정 건수·최소 증가 폭으로
`increase_signal` 또는 `no_increase_signal`을 반환한다. 이는 통계적 유의성 검정이 아니다.
비교 기간의 데이터 또는 성공 분모가 없으면 비율·변화폭은 `null`이며 0으로 대체하지 않는다.

응답의 `analysis_version`, `model`, `prompt_version`, `label_schema_version`은 실제 집계에 사용한
활성 버전을 나타낸다. 새 실행을 활성화해도 이전 버전 결과는 보존하지만 함께 집계하지 않는다.

## 사람 검토 API

일반 사용자 화면과 분리된 개발·평가 화면만 사용한다.

- `GET /api/v1/evaluation/datasets/{dataset_id}/progress`: 완료·미완료 수와 다음 위치
- `GET /api/v1/evaluation/datasets/{dataset_id}/items/{position}`: 원문, 캐시 번역, taxonomy,
  저장된 사람 정답. 모델 예측은 정답이 `completed`가 되기 전에는 반환하지 않는다.
- `PUT /api/v1/evaluation/datasets/{dataset_id}/items/{position}`: 진행 중 또는 완료 정답 저장.
  다중 항목, 같은 항목의 긍정·부정 동시 저장, `uncertain`, 명시적 정상 빈 라벨을 지원한다.
- `GET /api/v1/evaluation/datasets/{dataset_id}/export`: 기존 `gold_labels_json` CSV 형식으로 내보낸다.
- `POST /api/v1/reviews/{review_id}/translate`: 해당 리뷰 한 건만 자동 번역하고 캐시한다.

완료 정답의 근거 구간은 리뷰 제목 또는 본문에 실제 존재해야 한다. 정상 빈 라벨과 항목 라벨은
동시에 저장할 수 없고, 완료에는 검토자 이름이 필요하다. 자동 번역은 참고 자료이며 정답이나
영문 원문 인용을 대신하지 않는다.
