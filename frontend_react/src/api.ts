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
  analysis_sample_size: number | null;
  positive_review_share: number | null;
  negative_review_share: number | null;
  analysis_status: "not_started" | "in_progress" | "complete" | "partial_failure";
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
    sample_size: number | null;
    stored_reviews: number;
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
    signal_status:
      | "insufficient_data"
      | "insufficient_sample"
      | "analysis_incomplete"
      | "increase_signal"
      | "no_increase_signal";
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
  in_analysis_sample: boolean | null;
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

// === [의미 검색 · AI 질문] ===
export interface SearchResult {
  query: string;
  months: string[];
  embedded_reviews: number;
  total_reviews: number;
  items: { similarity: number; review: Review }[];
}

export interface AgentAnswer {
  question: string;
  search_query: string;
  status: "answered" | "failed";
  answer: string | null;
  citations: { review_id: string; rating: number; date: string; excerpt: string }[];
  tool_calls: { tool: string; ok: boolean; duration_ms: number; summary: string; transport: string }[];
  generation_attempts: number;
  failure_reason: string | null;
  notice: string | null;
  is_provisional: boolean;
  model: string;
  prompt_version: string;
  latency_ms: number;
  cached: boolean;
  generated_at: string | null;
  analyzed_count: number | null;
  is_stale: boolean;
}

// === [자주 묻는 질문] 미리 생성해 저장한 답(없으면 null) ===
export interface FaqItem {
  key: string;
  label: string;
  question: string;
  answer: AgentAnswer | null;
}

export interface FaqResponse {
  analysis_version: string;
  current_analyzed_count: number;
  items: FaqItem[];
}

export const fetchFaq = (id: string) => getJson<FaqResponse>(`/api/v1/products/${id}/faq`);

export async function searchReviews(id: string, query: string, months: string[]): Promise<SearchResult> {
  const params = new URLSearchParams({ q: query, limit: "8" });
  months.forEach((month) => params.append("month", month));
  const response = await fetch(`/api/v1/products/${id}/search?${params}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `검색 실패 (${response.status})`);
  }
  return response.json();
}

export async function askQuestion(
  id: string,
  question: string,
  history: { role: "user" | "assistant"; content: string }[] = [],
): Promise<AgentAnswer> {
  const response = await fetch(`/api/v1/products/${id}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `질문 실패 (${response.status})`);
  }
  return response.json();
}

// === [빠른 AI 답변] 요약본 RAG를 글자가 나오는 대로 받습니다(NDJSON 한 줄 = 이벤트 하나) ===
export type StreamEvent =
  | { type: "status"; message: string }
  | { type: "token"; text: string }
  | { type: "retry"; reason: string }
  | { type: "done"; result: AgentAnswer; metrics: Record<string, number> }
  | { type: "error"; message: string };

export async function askQuestionStream(
  id: string,
  question: string,
  history: { role: "user" | "assistant"; content: string }[],
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/products/${id}/questions/stream`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `질문 실패 (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end = buffer.indexOf("\n");
    while (end >= 0) {
      const line = buffer.slice(0, end).trim();
      buffer = buffer.slice(end + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
      end = buffer.indexOf("\n");
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as StreamEvent);
}

// === [이상징후 탐지] 모든 상품·인접 두 달 통계 검정 결과 ===
export interface AnomalyItem {
  level: "anomaly" | "watch";
  product_id: string;
  product_name_ko: string | null;
  category: string;
  image_url: string | null;
  baseline_month: string;
  target_month: string;
  detail_label: string;
  detail_name_ko: string | null;
  baseline_count: number;
  baseline_total: number;
  target_count: number;
  target_total: number;
  baseline_rate: number | null;
  target_rate: number | null;
  change_pp: number | null;
  p_value: number;
  q_value: number;
  is_provisional: boolean;
}

export interface AnomalyReport {
  method: string;
  products_total: number;
  products_evaluable: number;
  pairs_evaluated: number;
  pairs_insufficient: number;
  tests: number;
  items: AnomalyItem[];
}

export const fetchAnomalies = () => getJson<AnomalyReport>("/api/v1/anomalies");

// === [즉시 답변] LLM 없이 DB 분석 결과·관련 리뷰로 만든 답(MCP 도구 quick_answer) ===
export interface QuickAspect {
  aspect: string;
  detail_label: string;
  name_ko: string;
  similarity: number;
  mention_count: number;
  positive_count: number;
  negative_count: number;
  examples: { review_id: string; polarity: "positive" | "negative"; rating: number; date: string; evidence: string }[];
}

export interface QuickAnswer {
  question: string;
  answer_text: string;
  matched_faq: AgentAnswer | null;
  aspects: QuickAspect[];
  related_reviews: {
    review_id: string;
    similarity: number;
    rating: number;
    date: string;
    title: string;
    text: string;
    text_ko: string | null;
    labels: string[];
  }[];
  analyzed_reviews: number;
  is_small_sample: boolean;
  latency_ms: number;
}

export async function quickAnswer(id: string, question: string): Promise<QuickAnswer> {
  const response = await fetch(`/api/v1/products/${id}/quick-answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `즉시 답변 실패 (${response.status})`);
  }
  return response.json();
}
