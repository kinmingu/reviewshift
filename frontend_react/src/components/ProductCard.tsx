// =====================================================================
// [상품 카드] 이미지 · 분석 상태 배지 · 한국어 상품명 · 평점 · 좋아요/아쉬워요 막대
// =====================================================================
import { Link } from "react-router-dom";

import type { ProductSummary } from "../api";
import SentimentBar from "./SentimentBar";

// 분석 진행 상태를 카드 배지로 표시합니다(분석 전 리뷰를 불만 없음으로 보이지 않게).
export function AnalysisBadge({ analyzed, total }: { analyzed: number; total: number }) {
  if (!analyzed) return <span className="badge idle">분석 전</span>;
  if (analyzed >= total) return <span className="badge done">리뷰 분석 완료</span>;
  return <span className="badge ai">분석 중 {Math.floor((analyzed / total) * 100)}%</span>;
}

export default function ProductCard({ product }: { product: ProductSummary }) {
  return (
    <Link to={`/products/${product.id}`} className="card">
      <div className="card-media">
        <AnalysisBadge analyzed={product.analyzed_review_count} total={product.review_count} />
        {product.image_url ? (
          <img src={product.image_url} alt="" loading="lazy" />
        ) : (
          <span className="sentiment-empty">이미지 없음</span>
        )}
      </div>
      <div className="card-body">
        <div className="card-title">{product.title_ko ?? product.title}</div>
        <div className="meta">
          {product.source_average_rating !== null && (
            <>
              <span className="star">★</span>
              <b>{product.source_average_rating.toFixed(1)}</b>
              {product.source_rating_count !== null && (
                <span>({product.source_rating_count.toLocaleString()})</span>
              )}
              <span className="dot">|</span>
            </>
          )}
          <span>리뷰 {product.review_count.toLocaleString()}건</span>
        </div>
        <SentimentBar
          positive={product.positive_review_share}
          negative={product.negative_review_share}
          analyzed={product.analyzed_review_count}
        />
      </div>
    </Link>
  );
}
