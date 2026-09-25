# 정리 기록

## 삭제한 과거 코드 (M0, 2026-09-25)

7개 카테고리 수집 도구(`scripts/*_amazon_category.py`)로 대체된 초기 Appliances 전용 코드를
삭제했다. 커밋 `4105d10`에서 복구할 수 있다.

| 파일 | 역할 |
|---|---|
| `scripts/download_amazon_appliances.py` | Appliances Parquet 3개 다운로드 |
| `scripts/profile_amazon_appliances.py` | Appliances 전체 프로파일링 |
| `scripts/import_amazon_appliances.py` | Appliances 상품 3개·12개월 적재 |
| `scripts/amazon_reviews_source.py` | Appliances 원천 파일 목록 |
| `scripts/inspect_amazon_sample.py` | Range 요청 소량 표본 조사 |
| `config/amazon_appliances_selection.json` | Appliances 선정 파일 |
| `tests/test_amazon_importer.py` | 위 적재기 테스트. 공통 규칙 테스트는 `tests/test_amazon_category_importer.py`로 이동 |

`scripts/select_two_month_candidate.py`는 README의 두 달 분석 후보 선정 근거라 유지한다.

## 보존한 DB 데이터

개발 DB의 Appliances 상품 3개와 리뷰 7,801건은 삭제하지 않았다. 기본 상품 목록과 분석에서는 이미
제외되어 있으며(`REAL_CATEGORY_KEYS` 필터), `category=Appliances`로 명시할 때만 조회된다.

삭제가 필요하면 먼저 백업한 뒤 아래 SQL을 실행한다. 리뷰·분석 결과·평가는 외래 키
`ON DELETE CASCADE`로 함께 삭제된다. 이 SQL은 아직 실행하지 않았다.

```sql
-- 백업: docker compose exec db pg_dump -U reviewshift reviewshift > backup_before_cleanup.sql
BEGIN;
SELECT count(*) FROM reviews WHERE product_id IN (
  SELECT id FROM products WHERE source_mode = 'real' AND category = 'Appliances'
);  -- 7801 예상
DELETE FROM products WHERE source_mode = 'real' AND category = 'Appliances';
COMMIT;
```

삭제 후에는 `tests/test_api.py::test_real_products_are_separate_and_unclassified`가 Appliances
상품을 찾지 못해 실패하므로, 그 테스트도 함께 정리해야 한다.
