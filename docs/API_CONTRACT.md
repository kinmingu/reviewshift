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
`analysis_status`(`not_started|in_progress|complete|partial_failure`)는 상세 리포트의 `analysis.status`와
같은 규칙이다. 재시도 후에도 실패한 리뷰가 `ANALYSIS_MAX_FAILURE_RATE`(5%) 이하이면 `complete`다.

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

## POST `/api/v1/products/{product_id}/questions`

상품 리뷰 질문 Agent(LangGraph, 대화형). 본문 `{"question": "...", "history": [...]}`.

- `question`: 2~500자
- `history`: 선택, 최대 8개 `{role: "user"|"assistant", content}`(각 1,500자 이하). 서버는 최근 6개만,
  턴당 600자까지 답변 문맥으로 전달한다. 이전 답변의 수치·주장은 근거로 쓰지 않는다.
- 25자 미만의 짧은 후속 질문은 직전 사용자 질문을 붙여 검색한다(응답 `search_query`로 확인).
- 사용자가 겪는 제품 문제를 말하면 비슷한 리뷰 유무·언급 빈도(FACTS)·리뷰에 나온 대처를 답하고,
  안전 관련이면 사용 중지와 판매자·제조사 문의를 권한다.

흐름: MCP 도구 호출(`get_product_report` SQL 리포트, `search_reviews` 상품·저장 월 필터 의미 검색. 기본은 MCP 서버를
별도 프로세스로 띄운 stdio 연결, 설정 `AGENT_TOOL_TRANSPORT`) →
로컬 Ollama `qwen3.5:latest` 답변 생성(JSON schema) → 검증 → 실패 시 1회 재생성.

- 답변이 인용한 `review_id`는 검색 결과 안에 있어야 한다.
- 답변의 `%`·`%p` 수치는 도구가 SQL로 계산한 값과 일치해야 한다(반올림 표기만 허용).
- 리뷰 원문은 `REVIEWS_untrusted_customer_text`로 분리해 전달하며 지시로 따르지 않는다.
- 검증을 끝내 통과하지 못하면 `status=failed`, `answer=null`, `failure_reason`을 반환한다.
- 응답에는 `tool_calls` 실행 기록(`transport`: `mcp_stdio`/`mcp_memory`/`direct`), `generation_attempts`, `model`, `prompt_version`,
  `latency_ms`, 분석 미완료 여부 `is_provisional`이 포함된다.
- 질문 길이 오류 `422`, 없는 상품 `404`, LLM 연결 실패·시간 초과(기본 240초) `503`.
  CPU 환경에서 응답까지 1~4분 걸릴 수 있다.

### 답변 저장(캐시)과 자주 묻는 질문

- 대화 기록(`history`) 없이 들어온 질문은 같은 질문(띄어쓰기·대소문자·끝 문장부호 무시)의 저장 답이 있고
  분석 버전·분석 성공 건수가 그때와 같으면 LLM 없이 즉시 반환한다(`cached=true`, `generated_at`,
  `analyzed_count`). 분석이 더 진행됐으면 새로 생성해 덮어쓴다. 검증 실패 답은 저장하지 않는다.
- 후속 질문(`history` 있음)은 캐시를 쓰지도 저장하지도 않는다.

## GET `/api/v1/products/{product_id}/faq`

상품별 자주 묻는 질문 6개(`summary` AI 리뷰 요약, `durability`, `shipping`, `value`, `usability`,
`safety`)와 미리 생성해 저장한 답(없으면 `answer=null`). 답에는 생성 시점 분석 건수와 `is_stale`
(지금 분석 상태와 다르면 true)이 있다. 생성은 `python -m scripts.generate_faq_answers --demo`.

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

## MCP 도구 (stdio, `python -m backend.app.mcp_server`)

HTTP API와 같은 서비스를 호출하는 읽기 전용 도구다. 서버 안내문(instructions)에 수치 인용 규칙, 잠정·표본 부족
표시, 리뷰 ID 인용, 리뷰 본문 비신뢰 원칙을 담는다.

- `list_products(category?, query?)`: 카테고리는 공식 7개 키만 허용
- `get_product_report(product_id)`: `/insights`와 같은 내용
- `compare_months(product_id, baseline_month, target_month)`: `/comparison`과 같고 근거 ID는 항목당 5개
- `search_reviews(product_id, query, months[], limit=5)`: `months` 필수, `limit` 1~10, 본문 600자
- `get_faq_answers(product_id)`: `/faq`와 같은 내용

없는 상품, 잘못된 카테고리·월, 월 누락, 임베딩 모델 오류는 도구 오류(`isError`)와 한국어 메시지로 반환한다.

## GET `/api/v1/anomalies`

불만 이상징후 탐지. 모든 공식 상품의 인접한 두 달 쌍 전부를 같은 규칙으로 검정한다(기간을 결과로 고르지 않음).

- 지표: 항목별 아쉬워요 리뷰 비율(분모 = 그 달 분석 성공 리뷰, 표본 안)
- 검정: 비율 증가에 대한 한쪽 Fisher 정확 검정 `p_value`, 모든 검정에 Benjamini-Hochberg 보정 `q_value`
- `level=anomaly`: q < 0.10, 증가 10%p 이상, 대상 월 아쉬워요 3건 이상
- `level=watch`: 보정 전 p < 0.05(이상징후 제외)
- 두 달 중 한 달이라도 분석 성공 10건 미만이면 판정하지 않고 `pairs_insufficient`로 센다.
- 결과는 서버에서 2분간 캐시한다. `method_version=anomaly-fisher-bh-v1`

## POST `/api/v1/products/{product_id}/quick-answer`

LLM 없이 1초 안팎으로 답하는 즉시 답변. 본문 `{"question": "..."}`. MCP 도구 `quick_answer`를 같은 프로세스
MCP 연결로 호출한다. 질문 임베딩(bge-m3) 1회로 ① 가까운 FAQ(유사도 0.80 이상, 최신일 때 저장 답 포함) ② 가까운 분석
항목 2개의 SQL 집계(언급·좋아요·아쉬워요 리뷰 수)와 대표 근거 ③ 상품·저장 월로 제한한 pgvector 관련 리뷰 4건을
돌려준다. `answer_text`는 DB 값으로 만든 요약이며 수치를 새로 계산하지 않는다. 없는 상품 404, 질문 길이 422,
임베딩 모델 오류 503. 화면은 질문을 보내면 이 API와 `/questions/stream`을 동시에 호출하고, 이 결과는
'찾는 과정'(분석 수·항목별 언급 수·비슷한 리뷰 수)으로 보여 준다. AI 답이 실패하면 대체 답으로 쓴다.

## POST `/api/v1/products/{product_id}/questions/stream`

빠른 AI 답변(요약본 RAG + 스트리밍). 본문은 `/questions`와 같다(`question`, `history`). 응답은
`application/x-ndjson`이며 한 줄이 이벤트 하나다.

- `{"type":"status","message"}`: 진행 단계(자료 찾기 → 답변 쓰기)
- `{"type":"sources","items":[{"number","rating","label","text","review_id"}]}`: AI가 읽을 근거 리뷰. 자료를 찾은 직후(약 3초) 답보다 먼저 보낸다. 화면은 기다리는 동안 "AI가 읽는 리뷰"로 보여 준다.
- `{"type":"token","text"}`: 생성되는 글자 조각. **검증 전**이므로 화면에 '검증 전'으로 표시한다.
- `{"type":"retry","reason"}`: 검증 실패로 다시 생성한다. 화면은 받은 글자를 지운다.
- `{"type":"done","result","metrics"}`: `result`는 `/questions`와 같은 `AgentAnswerResponse` 형식이다.
  `status=failed`이면 `answer`는 null이다. `metrics`는 Ollama 입력·출력 토큰 수와 시간이다.
- `{"type":"error","message"}`: 모델·도구 오류(스트림 도중이라 HTTP 상태는 200)

자료는 MCP 도구 `quick_answer`와 `get_product_report`(같은 프로세스 MCP 연결)로 모은다. LLM에는 관련 항목의
서버 계산 수치와 근거 문장 한 줄씩만 번호([1]…)를 붙여 준다(약 450토큰). 검증 규칙은 다음과 같다.
- 인용 번호는 자료에 있는 번호여야 한다.
- 질문과 관련된 항목의 근거 문장(label이 '질문과 비슷한 리뷰'가 아닌 자료)이 있으면 인용 번호가 하나 이상 있어야 한다.
  '질문과 비슷한 리뷰'만 있으면 관련 언급이 없다는 답을 번호 없이 허용한다.
- %는 자료 값과 같아야 한다.
- 내부 용어와 이전 답 반복을 금지한다.
- 실패하면 1회 다시 생성한다.

대화 첫 질문이고 같은 질문의 최신 저장 답(FAQ 포함)이 있으면 곧바로 `done`만 보낸다. 없는 상품은 404,
질문 길이 오류는 422다. `prompt_version=review-qa-fast-v2`(지시문은 v1과 같고 위 인용 필수 규칙이 추가됨).
v1으로 미리 만든 FAQ 답도 계속 읽으며, 같은 질문에 새 답이 있으면 최신 답을 쓴다.
화면은 `token`을 보여 주지 않고 진행 단계만 표시한 뒤, `done`의 검증된 답만 대화에 붙인다.
클라이언트가 연결을 끊으면 서버가 0.5초 안에 감지해 Ollama 연결을 끊고 생성을 멈춘다. 새 질문이나 FAQ 일치로
취소하는 경우다. 모델이 읽던 입력 묶음은 끝까지 처리하므로 약 6초가 남을 수 있다.
화면은 질문을 보내면 즉시 답과 이 스트림을 동시에 시작하고, 즉시 답에 최신 FAQ 답이 붙으면 스트림을 취소한다. 기존 `/questions`(리뷰 원문을 읽는 상세 Agent)는
FAQ 생성에 계속 쓴다.
