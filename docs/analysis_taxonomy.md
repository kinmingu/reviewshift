# 리뷰 항목별 감성 분류 체계 v1

기계 판독 원본은 `config/review_analysis_taxonomy.json`이며 버전은
`review-taxonomy-v1`이다. 모델은 이 목록에 있는 코드만 반환할 수 있다. 화면에는 한국어
이름을 표시하고 DB에는 변경에 안전한 영문 코드를 저장한다.

## 공통 판정 규칙

- 영어 리뷰 제목과 본문만 분류 입력으로 사용한다. 별점은 모델 입력에 넣지 않는다.
- 리뷰에 명시적으로 언급된 항목만 만든다. 언급되지 않은 항목을 중립으로 채우지 않는다.
- 한 리뷰에서 여러 항목을 허용한다. 같은 항목에 긍정과 부정이 함께 있으면 각각의 원문
  근거를 별도 라벨로 보존한다.
- `positive`, `negative`, `neutral`, `uncertain`만 허용한다. `neutral`은 명시적 사실 언급에
  평가가 없을 때, `uncertain`은 표현은 있지만 감성 판단이 불가능할 때 사용한다.
- “has not broken”, “no problem”처럼 고장을 부정한 문장은 고장 불만으로 분류하지 않는다.
- 제품 품질과 `shipping`, `packaging`, `seller_service`를 분리한다.
- 건강 관련 문장은 사용자가 경험했다고 쓴 내용만 분류하며 의학적 사실로 확정하지 않는다.
- `evidence_span`은 제목 또는 본문에서 그대로 복사한 대소문자 구분 부분 문자열이어야 한다.
  원문 존재 검사는 형식적 근거 검증이며 의미적 정확성을 증명하지 않는다.
- 모델 confidence는 저장하거나 정확도로 표시하지 않는다.

## 공통 상위·세부 항목

| 상위 코드 | 세부 코드 | 의미 | 주요 제외 기준 |
|---|---|---|---|
| performance | core_performance | 제품의 핵심 기능 수행 | 배송·판매자 서비스 |
| performance | reliability | 고장·누수·오작동·지속성 | 고장이 없다는 부정 표현 |
| performance | compatibility | 명시 기기·용도 호환 | 단순 크기 취향 |
| usability | setup_installation | 조립·부착·연결·초기 설정 | 배송 중 파손 |
| usability | controls_operation | 버튼·앱·사용 절차 | 핵심 성능 결과 |
| usability | cleaning_maintenance | 제품의 세척·관리·보관 | 세정제 자체 세정력 |
| design | build_material | 내구감·재질·마감 | 배송 포장재 |
| design | size_fit | 크기·무게·착용감·맞음새 | 기술적 호환 |
| design | appearance | 색상·모양·시각 디자인 | 성능 |
| value | price_value | 가격·가성비·돈 낭비 | 환불 응대 |
| service | shipping | 배송 속도·배송 과정 | 제품 성능 |
| service | packaging | 포장 상태·운송 중 포장 손상 | 제품 소재 |
| service | seller_service | 환불·교환·판매자 응대 | 제품 조작 편의 |

## 카테고리별 항목

| 카테고리 | 상위 코드 | 허용 세부 코드 |
|---|---|---|
| 전자제품 | audio_video | sound_quality, noise_control, camera_video |
| 전자제품 | power_connection | battery_runtime, connectivity |
| 뷰티·개인관리 | beauty_use | shave_performance, hair_drying, skin_comfort, heat_temperature |
| 휴대폰·액세서리 | mobile_accessory | charging, cable, screen_protection, fit_alignment |
| 주방·생활용품 | home_use | cleaning_effectiveness, fabric_fit, material_comfort |
| 스포츠·아웃도어 | sports_use | lighting_visibility, stability_support, inflation |
| 장난감·게임 | toy_use | engagement, learning, sound_recording, child_safety |
| 건강·가정용품 | household_use | absorbency_softness, detergent_cleaning, skin_sensitivity, scent |

각 세부 항목의 포함·제외 기준과 예시는 JSON 원본에 기록돼 있다. 분류 체계를 바꾸면 새
`label_schema_version`과 분석 실행을 만들며, 이전 실행의 라벨과 같은 집계에 섞지 않는다.

## 집계 규칙

- 분모는 선택 월의 `succeeded` 리뷰 수다. 정상 빈 라벨 리뷰도 성공 분모에 포함한다.
- 동일 리뷰의 동일 `(항목, 세부 항목, 감성)`은 근거가 여러 개여도 건수에서 한 번 센다.
- 긍정과 부정을 모두 언급한 리뷰는 각 감성 건수에 한 번씩 들어간다. 따라서 감성별 비율의
  합계가 100%일 필요는 없다.
- `failed`, `pending`, `running`, 미처리 리뷰는 불만 없는 리뷰로 보지 않는다.
- 두 월이 모두 100% 성공했을 때만 변화 신호를 확정한다. 부분 결과의 비율과 변화폭은
  `잠정`으로 표시한다.
- 기본 증가 신호 기준은 월별 성공 리뷰 30건 이상, 분석 월 부정 5건 이상, 부정 비율
  10%p 이상 증가다. 이는 설정 기준이며 통계적 유의성을 뜻하지 않는다.
