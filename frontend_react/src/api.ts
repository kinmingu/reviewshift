// =====================================================================
// [API 클라이언트] FastAPI 응답 타입과 호출 함수
// 화면은 계산을 하지 않고, 서버가 SQL로 집계한 값을 그대로 보여 줍니다.
// =====================================================================

export type Polarity = "positive" | "negative" | "neutral" | "uncertain";
export type AnalysisStatus = "not_started" | "in_progress" | "complete" | "partial_failure";

// === [상품 목록·요약] ===
export interface ProductSummary {
  id: string;
  title: string;
  title_ko: string | null;
  category: string;
  image_url: string | null;
  review_count: number;
  source_average_rating: number | null;
  source_rating_count: number | null;
  available_months: string[];
  source_mode: "fixture" | "real";
  analyzed_review_count: number;
  positive_review_share: number | null;
  negative_review_share: number | null;
}

export interface ProductDetail extends ProductSummary {
  source: string;
  parent_asin: string;
  metadata: Record<string, unknown>;
  monthly_stats: { month: string; review_count: number; average_rating: number }[];
}

// === [리뷰 리포트] GET /api/v1/products/{id}/insights ===
export interface AspectInsight {
  aspect: string;
  aspect_name_ko: string | null;
  detail_label: string;
  detail_name_ko: string | null;
  mention_count: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  uncertain_count: number;
  mention_rate: number | null;
  positive_rate: number | null;
  negative_rate: number | null;
}

export interface EvidenceExample {
  review_id: string;
  rating: number;
  reviewed_at: string;
  evidence_span: string;
}

export interface ComplaintInsight {
  aspect: string;
  aspect_name_ko: string | null;
  detail_label: string;
  detail_name_ko: string | null;
  negative_count: number;
  negative_rate: number | null;
  examples: EvidenceExample[];
}

export interface ComparisonIssue {
  aspect: string;
  aspect_name_ko: string | null;
  detail_label: string;
  detail_name_ko: string | null;
  polarity: Polarity;
  target_count: number;
  target_total: number;
  target_rate: number | null;
  baseline_count: number;
  baseline_total: number;
  baseline_rate: number | null;
  change_pp: number | null;
  meets_increase_threshold: boolean | null;
  evidence_review_ids: string[];
}

export interface ProductInsights {
  product_id: string;
  review_count: number;
  average_rating: number | null;
  rating_distribution: Record<string, number>;
  analysis: {
    total: number;
    succeeded: number;
    failed: number;
    in_progress: number;
    unprocessed: number;
    processing_rate: number | null;
    status: AnalysisStatus;
    analysis_version: string;
    model: string | null;
    prompt_version: string | null;
  };
  positive_review_share: number | null;
  negative_review_share: number | null;
  aspects: AspectInsight[];
  top_complaints: ComplaintInsight[];
  monthly: {
    month: string;
    review_count: number;
    average_rating: number;
    analyzed_count: number;
    positive_review_share: number | null;
    negative_review_share: number | null;
  }[];
  latest_change: {
    baseline_month: string;
    target_month: string;
    signal_status: "insufficient_data" | "analysis_incomplete" | "increase_signal" | "no_increase_signal";
    is_provisional: boolean;
    top_negative_changes: ComparisonIssue[];
  } | null;
  data_version: string;
}

// === [리뷰 원문] ===
export interface ReviewLabel {
  aspect: string;
  aspect_name_ko: string | null;
  detail_label: string;
  detail_name_ko: string | null;
  polarity: Polarity;
  evidence_span: string;
}

export interface Review {
  id: string;
  title: string | null;
  text: string;
  title_ko: string | null;
  text_ko: string | null;
  translation_model: string | null;
  rating: number;
  reviewed_at: string;
  labels: ReviewLabel[];
  analysis_status: "not_started" | "pending" | "running" | "succeeded" | "failed";
}

// === [호출 함수] ===
async function getJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  const url = query.toString() ? `${path}?${query}` : path;
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `요청 실패 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  categories: () =>
    getJson<{ items: string[] }>("/api/v1/categories", { source_mode: "real" }),
  products: (params: { category?: string; query?: string }) =>
    getJson<{ items: ProductSummary[]; total: number }>("/api/v1/products", {
      source_mode: "real",
      page_size: 100,
      ...params,
    }),
  product: (id: string) => getJson<ProductDetail>(`/api/v1/products/${id}`),
  insights: (id: string) => getJson<ProductInsights>(`/api/v1/products/${id}/insights`),
  reviews: (id: string, params: { month: string; aspect?: string; polarity?: string; page?: number }) =>
    getJson<{ items: Review[]; total: number }>(`/api/v1/products/${id}/reviews`, {
      page_size: 20,
      ...params,
    }),
};
