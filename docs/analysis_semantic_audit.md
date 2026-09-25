# 분류 의미 오류 점검

이 문서는 `amazon-absa-qwen35-v1` 70건 시험의 의심 사례를 Codex가 정성 점검한
개발 기록이다. 구조화 출력 검증, 원문 부분 문자열 일치, 의미적 정확성은 서로 다른 기준이다.
v1의 68/70은 앞의 두 자동 검증을 최종 통과한 건수이지 분류 정확도가 아니다. 사람 정답이
아직 없으므로 정확도·F1을 계산하지 않는다.

## 지정 사례

### 풍량 표현

- 리뷰 ID: `amazon-01696d3e4be9d2347b61bcb534bca9a0c3f4f98d`
- 제목: `Low fan is too strong`
- 본문: `Low fan setting is actually quite strong.`
- v1 결과: `performance/core_performance`, 부정, 본문 문장을 근거로 저장
- 점검: 제목의 `too strong`까지 보면 불만으로 해석할 근거가 있지만, 본문의 `quite strong`
  자체는 속성 강도만 말해 단독으로 부정을 확정하기 어렵다. 근거 문자열 자체가 항목과 감성을
  함께 뒷받침해야 한다.
- 수정: 강도 단어만으로 극성을 결정하지 않고 작성자의 평가·선호·`too` 같은 문맥을 보며,
  모호하면 `uncertain`을 사용하도록 프롬프트에 명시했다.

### 잘못 조합된 `performance/inflation`

- 리뷰 ID: `amazon-663da392d8ef8b470ba05a4dff20e5f2f4a444a5`
- 제목: `NO PUMP INCLUDED!!`
- 본문에는 포장이 좋고 배송이 빨랐지만 광고된 펌프가 없다는 내용이 모두 있다.
- v1 결과: 연속 공백을 한 칸으로 바꾼 배송 근거 오류 뒤, 허용되지 않은
  `performance/inflation`을 반복해 최종 실패
- 점검: 기대되는 후보는 포장 긍정, 배송 긍정, `sports_use/inflation` 부정이다.
- 수정: 상위·세부 항목을 독립 enum으로 생성하지 않고 `sports_use.inflation`처럼 검증된 조합
  하나만 선택하게 했다. 잘못된 조합을 임의 치환해 성공으로 바꾸지는 않는다.

### 리뷰에 없는 `Multicolor`

- 리뷰 ID: `amazon-a634157ce545e5fed9bff5d58b5f481c5ab90c05`
- 제목: `Grandson really enjoy this toy and it's safe and easy to use.`
- 본문: `I gave to my grandson as a Christmas gift.`
- v1 결과: 리뷰에 없는 `Multicolor`를 근거로 반복해 원문 검증 실패
- 원인: 상품명 메타데이터가 모델 입력에 함께 있었고 상품명 끝의 `Multicolor`를 리뷰 근거처럼
  사용했다.
- 수정: 상품명과 상품 메타데이터를 분류 요청에서 제거했다. 리뷰 제목과 본문만 인용 근거가
  될 수 있다. 제목에서 흥미·안전·사용성 긍정 후보를 읽을 수 있으나 최종 정답은 사람 검토가
  필요하다.

### v1 정상 완료 빈 라벨 3건

| 리뷰 ID | 원문 요약 | Codex 개발 점검 |
|---|---|---|
| `amazon-db44c140702afd0fe0f00cd0c8abe40839544919` | `Amazin!!! / Love it!!!!` | 구체 항목 없는 일반 호감이라 빈 라벨이 가능하지만, 정책에 따라 핵심 성능 긍정으로 볼 여지도 있어 사람 검토 필요 |
| `amazon-41ef353292e53740e7a2b694202321c9c25f1743` | `Not cat proof / Apparently not cat proof...` | 소재·내구 관련 부정 누락 의심 |
| `amazon-a617fe98de73ab71a396efe64d8f2f73113f11f1` | `Super awesomeness / works great 5 stars` | 명시적인 핵심 성능 긍정 누락 의심 |

빈 라벨은 모델 호출 실패와 별도로 저장한다. 위 판단은 프롬프트 개발에 사용한 Codex 점검이며
독립된 사람 정답이 아니다.

## v3 변경 원칙

- 프롬프트 버전: `absa-prompt-v3`
- 분류 체계 버전: `review-taxonomy-v1`(코드와 의미는 유지)
- 리뷰 제목·본문만 모델 입력 근거로 사용
- 별점 미사용, 상품 메타데이터 미사용
- 유효한 `상위.세부` 조합만 구조화 출력 schema에서 허용
- 감성의 근거가 부족하면 강제 긍정·부정 대신 `uncertain`
- `works great` 같은 일반 작동 평가는 `performance.core_performance` 후보로 명시
- 모델 응답의 근거가 원문에 실제 존재하는지는 계속 엄격히 검사하며, 실패를 임의 치환하지 않음

프롬프트 조정에 사용한 14건은 `config/analysis_dev_14.json`에 고정했으며 기존 70건에서 뽑은
개발 집합이다. 140건 블라인드 집합과는 중복되지 않지만, 이 14건의 결과를 독립 평가 품질로
보고하지 않는다.

## v3 실제 재시험 결과

- 풍량 리뷰: `usability.controls_operation` 부정으로 바뀌었지만 근거는 여전히 본문의
  `Low fan setting is actually quite strong`만 선택했다. 제목의 `too strong` 없이 본문 근거만으로
  부정을 확정하기에는 모호하므로 의미 오류 의심 상태를 유지한다.
- 펌프 누락 리뷰: 구조·근거 검증은 성공했고 포장 긍정, 배송 긍정을 추출했다. 다만 펌프 누락을
  `sports_use.inflation`이 아니라 `performance.core_performance` 부정으로 선택해, 잘못된 코드
  조합 생성 문제는 막았지만 항목 선택의 의미 오류 가능성은 해결되지 않았다.
- `Multicolor` 리뷰: 상품 메타데이터를 근거로 쓰지 않고 리뷰 제목에서 흥미·안전·사용성 긍정
  세 항목의 실제 구간을 인용해 성공했다.
- v1 빈 라벨 3건: v3는 각각 일반 성능 긍정, 소재 부정, 일반 성능 긍정을 반환했다. 고양이
  내구와 `works great` 사례는 v1 누락을 보완한 것으로 보이지만, `Love it!!!!`을 구체적 성능
  긍정으로 볼지는 사람 검토가 필요하다.

따라서 v3의 14/14는 구조화 응답과 원문 근거 검증의 최종 통과율이다. 의미적 분류 정확도는
여전히 측정하지 않았다.
