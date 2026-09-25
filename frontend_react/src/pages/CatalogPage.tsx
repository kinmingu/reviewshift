// =====================================================================
// [카테고리 화면] 왼쪽: 7개 카테고리 / 오른쪽: 선택한 카테고리의 상품 카드
// 검색어(?q=)가 있으면 전체 카테고리에서 검색한 결과를 보여 줍니다.
// =====================================================================
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import ProductCard from "../components/ProductCard";
import { CATEGORY_INFO, categoryName } from "../lib/format";

export default function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const selected = params.get("category") ?? categories.data?.items[0] ?? "";

  // 검색 중에는 카테고리 필터 없이 전체에서 찾습니다.
  const products = useQuery({
    queryKey: ["products", query ? "" : selected, query],
    queryFn: () => api.products(query ? { query } : { category: selected }),
    enabled: Boolean(query || selected),
  });

  const selectCategory = (key: string) => setParams({ category: key });

  return (
    <main className="page">
      <div className="catalog">
        {/* === [카테고리 레일] === */}
        <nav className="rail" aria-label="카테고리">
          {(categories.data?.items ?? []).map((key) => (
            <button
              key={key}
              className={`rail-item ${!query && key === selected ? "active" : ""}`}
              onClick={() => selectCategory(key)}
            >
              {categoryName(key)}
              <small>{CATEGORY_INFO[key]?.hint}</small>
            </button>
          ))}
        </nav>

        {/* === [상품 목록] === */}
        <section>
          <div className="section-head">
            <div>
              <h1>{query ? `"${query}" 검색 결과` : categoryName(selected)}</h1>
              <p>
                상품을 누르면 실제 구매자 리뷰를 분석한 리포트를 볼 수 있어요.
                {products.data && ` · ${products.data.total}개 상품`}
              </p>
            </div>
          </div>

          {products.isError && <div className="error">상품을 불러오지 못했어요. API 서버가 켜져 있는지 확인해 주세요.</div>}
          {products.isLoading && (
            <div className="grid">
              {[0, 1].map((index) => (
                <div key={index} className="skeleton" style={{ height: 360 }} />
              ))}
            </div>
          )}
          {products.data && products.data.items.length === 0 && (
            <p className="empty">조건에 맞는 상품이 없어요.</p>
          )}
          <div className="grid">
            {products.data?.items.map((product) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>

          <p className="footer-note">
            데이터 출처: McAuley-Lab Amazon Reviews 2023 공개 데이터(상품별 연속 3개월 리뷰). 가격·구매 기능이 없는
            리뷰 분석 서비스이며, 평점 등록 수는 구매 수가 아닙니다. 좋아요/아쉬워요 비율은 AI 분류가 끝난 리뷰만
            대상으로 서버에서 계산합니다.
          </p>
        </section>
      </div>
    </main>
  );
}
