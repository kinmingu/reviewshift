// =====================================================================
// [상품 상세 = 리뷰 리포트]
//   1. 상품 정보(이미지·이름·평점)       2. 한눈에 보는 리뷰 + AI 리뷰 요약(미리 생성)
//   3. 사람들이 말하는 포인트(항목별)     4. 자주 나오는 아쉬운 점 TOP 3(근거 인용)
//   5. 최근 두 달 변화                    6. 별점 분포 · 월별 흐름
//   7. 리뷰 원문(의미 검색 포함)          8. 하단 고정 바(리뷰 챗봇)
// 모든 수치는 서버 SQL 집계값이며 화면에서 새로 계산하지 않습니다.
// =====================================================================
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { api, fetchFaq, type FaqResponse, type ProductDetail, type ProductInsights } from "../api";
import AskPanel from "../components/AskPanel";
import { AnalysisBadge } from "../components/ProductCard";
import ReviewList from "../components/ReviewList";
import { categoryName, dateLabel, labelName, monthLabel, percent } from "../lib/format";

// === [1. 상품 정보] ===
function Hero({ product, insights }: { product: ProductDetail; insights: ProductInsights }) {
  const description = product.metadata.description_ko as string | undefined;
  return (
    <section className="hero">
      <div className="hero-media">
        {product.image_url ? <img src={product.image_url} alt={product.title_ko ?? product.title} /> : "이미지 없음"}
      </div>
      <div>
        <div className="crumb">{categoryName(product.category)}</div>
        <h1>{product.title_ko ?? product.title}</h1>
        <details className="original">
          <summary>원문 상품명 보기</summary>
          {product.title}
        </details>
        {description && <p className="hero-desc">{description}</p>}
        <dl className="facts">
          <div className="fact">
            <dt>분석 리뷰 평점</dt>
            <dd>
              <span className="star">★</span> {insights.average_rating?.toFixed(2) ?? "–"}{" "}
              <small>
                저장 리뷰 {insights.review_count.toLocaleString()}건 · {product.available_months.map(monthLabel).join(", ")}
              </small>
            </dd>
          </div>
          <div className="fact">
            <dt>Amazon 전체 평점</dt>
            <dd>
              {product.source_average_rating?.toFixed(1) ?? "–"}{" "}
              <small>평점 등록 {product.source_rating_count?.toLocaleString() ?? "–"}건 (구매 수 아님)</small>
            </dd>
          </div>
          <div className="fact">
            <dt>AI 분석</dt>
            <dd>
              <AnalysisBadge analyzed={insights.analysis.succeeded} total={insights.analysis.total} />{" "}
              <small>
                {insights.analysis.succeeded}/{insights.analysis.total}건
                {insights.analysis.failed > 0 && ` · 실패 ${insights.analysis.failed}건`}
              </small>
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

// === [2. 한눈에 보는 리뷰] ===
function SummaryPanel({ insights }: { insights: ProductInsights }) {
  const { analysis } = insights;
  const provisional = analysis.status !== "complete";
  return (
    <section className="panel summary-panel">
      <div className="panel-head">
        <div>
          <h2>한눈에 보는 리뷰</h2>
          <p className="sub">AI가 분류한 리뷰 {analysis.succeeded.toLocaleString()}건을 서버에서 집계했어요</p>
        </div>
        {provisional && <span className="badge ai">잠정 결과</span>}
      </div>
      {analysis.succeeded === 0 ? (
        <p className="notice">
          아직 AI 분석 전인 상품이에요. 별점 분포와 리뷰 원문은 아래에서 볼 수 있어요. 분석되지 않은 리뷰를 "불만
          없음"으로 계산하지 않아요.
        </p>
      ) : (
        <div className="summary-stats">
          <div className="stat pos">
            <b>{percent(insights.positive_review_share)}</b>
            <span>👍 좋은 점을 말한 리뷰</span>
          </div>
          <div className="stat neg">
            <b>{percent(insights.negative_review_share)}</b>
            <span>👎 아쉬운 점을 말한 리뷰</span>
          </div>
          <div className="stat">
            <b>{percent(analysis.processing_rate)}</b>
            <span>AI 분석 진행률</span>
            <div className="progress">
              <span style={{ width: `${(analysis.processing_rate ?? 0) * 100}%` }} />
            </div>
          </div>
        </div>
      )}
      {provisional && analysis.succeeded > 0 && (
        <p className="notice">
          전체 {analysis.total}건 중 {analysis.succeeded}건만 분석된 잠정 결과예요. 분석이 끝나면 비율이 달라질 수
          있어요.
        </p>
      )}
    </section>
  );
}

// === [2-1. AI 리뷰 요약] 미리 생성해 저장한 요약(검증 통과 답변)을 바로 보여 줍니다 ===
function AiSummaryPanel({ faq }: { faq: FaqResponse | undefined }) {
  const summary = faq?.items.find((item) => item.key === "summary")?.answer;
  return (
    <section className="panel ai-summary">
      <div className="panel-head">
        <div>
          <h2>AI 리뷰 요약</h2>
          <p className="sub">
            {summary
              ? `리뷰 ${summary.analyzed_count ?? 0}건 분석 기준 · ${summary.generated_at ? dateLabel(summary.generated_at) : ""} 생성 · 인용 ${summary.citations.length}건`
              : "아직 요약을 만들지 않았어요. 아래 챗봇에 물어보면 실시간으로 답해 드려요."}
          </p>
        </div>
        <div className="tags" style={{ marginTop: 0 }}>
          {summary?.is_stale && <span className="badge warn">이후 분석이 더 진행됨 · 갱신 예정</span>}
          {summary?.is_provisional && <span className="badge ai">잠정</span>}
        </div>
      </div>
      {summary && <p className="ask-answer">{summary.answer}</p>}
      {summary && summary.citations.length > 0 && (
        <details>
          <summary className="bubble-meta">근거 리뷰 보기</summary>
          {summary.citations.map((citation) => (
            <blockquote key={citation.review_id} className="quote">
              {citation.excerpt.replace(/<br\s*\/?>/gi, " ")}
              <small>
                ★{citation.rating} · {citation.date}
              </small>
            </blockquote>
          ))}
        </details>
      )}
    </section>
  );
}

// === [3. 사람들이 말하는 포인트] 항목별 좋아요(왼쪽)·아쉬워요(오른쪽) 리뷰 수 ===
function AspectPanel({ insights }: { insights: ProductInsights }) {
  const rows = insights.aspects.slice(0, 8);
  const max = Math.max(1, ...rows.map((row) => Math.max(row.positive_count, row.negative_count)));
  return (
    <section className="panel half">
      <h2>사람들이 말하는 포인트</h2>
      <p className="sub">많이 언급된 순 · 막대 = 리뷰 수</p>
      {rows.length === 0 && <p className="empty">분석된 평가 항목이 아직 없어요.</p>}
      <div className="aspect-list">
        {rows.map((row) => (
          <div key={`${row.aspect}.${row.detail_label}`} className="aspect-row">
            <div className="aspect-name">
              {labelName(row)}
              <small>{row.mention_count}건 언급</small>
            </div>
            <div>
              <div className="half-bar left">
                <span className="pos" style={{ width: `${(row.positive_count / max) * 100}%` }} />
              </div>
              <div className="aspect-count">
                <span style={{ color: "var(--positive)" }}>👍 {row.positive_count}</span>
              </div>
            </div>
            <div>
              <div className="half-bar">
                <span className="neg" style={{ width: `${(row.negative_count / max) * 100}%` }} />
              </div>
              <div className="aspect-count">
                <span />
                <span style={{ color: "var(--negative)" }}>{row.negative_count} 👎</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// === [4. 자주 나오는 아쉬운 점 TOP 3] 실제 리뷰 원문 근거를 함께 보여 줍니다 ===
function ComplaintPanel({ insights }: { insights: ProductInsights }) {
  return (
    <section className="panel half">
      <h2>자주 나오는 아쉬운 점</h2>
      <p className="sub">아쉬운 점을 말한 리뷰가 많은 순 · 인용은 리뷰 원문 그대로</p>
      {insights.top_complaints.length === 0 && (
        <p className="empty">
          {insights.analysis.succeeded ? "분석된 리뷰에서 아쉬운 점이 아직 나오지 않았어요." : "AI 분석 전이에요."}
        </p>
      )}
      <div className="complaints">
        {insights.top_complaints.map((item, index) => (
          <div key={`${item.aspect}.${item.detail_label}`} className="complaint">
            <div className="complaint-head">
              <span className="rank">{index + 1}</span>
              <b>{labelName(item)}</b>
              <span>
                {item.negative_count}건 · {percent(item.negative_rate, 1)}
              </span>
            </div>
            {item.examples.map((example) => (
              <blockquote key={example.review_id} className="quote">
                “{example.evidence_span.replace(/<br\s*\/?>/gi, " ")}”
                <small>
                  ★{example.rating} · {dateLabel(example.reviewed_at)}
                </small>
              </blockquote>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

// === [5. 최근 두 달 변화] 기간은 항상 인접한 마지막 두 달(결과를 보고 고르지 않음) ===
const SIGNAL_TEXT = {
  increase_signal: { text: "아쉬운 점 증가 신호", className: "warn" },
  no_increase_signal: { text: "뚜렷한 증가 없음", className: "good" },
  analysis_incomplete: { text: "분석 진행 중 · 잠정", className: "ai" },
  insufficient_data: { text: "비교할 데이터 부족", className: "idle" },
} as const;

function ChangePanel({ insights }: { insights: ProductInsights }) {
  const change = insights.latest_change;
  if (!change) return null;
  const signal = SIGNAL_TEXT[change.signal_status];
  return (
    <section className="panel half">
      <div className="panel-head">
        <div>
          <h2>최근 두 달, 늘어난 아쉬운 점</h2>
          <p className="sub">
            {monthLabel(change.baseline_month)} → {monthLabel(change.target_month)} · 분석된 리뷰 중 비율
          </p>
        </div>
        <span className={`badge ${signal.className}`}>{signal.text}</span>
      </div>
      {change.top_negative_changes.length === 0 && <p className="empty">늘어난 아쉬운 점이 없어요.</p>}
      <div className="change-list">
        {change.top_negative_changes.map((issue) => (
          <div key={`${issue.aspect}.${issue.detail_label}`} className="change">
            <span>
              {labelName(issue)} <small style={{ color: "var(--muted)" }}>
                {percent(issue.baseline_rate, 1)} → {percent(issue.target_rate, 1)} ({issue.baseline_count}→
                {issue.target_count}건)
              </small>
            </span>
            <b>+{issue.change_pp?.toFixed(1)}%p</b>
          </div>
        ))}
      </div>
      <p className="footer-note" style={{ marginTop: 12 }}>
        증가 신호는 분석 30건 이상·아쉬움 5건 이상·10%p 이상 증가일 때만 표시해요. 통계적 유의성 검정은 아니에요.
      </p>
    </section>
  );
}

// === [6. 별점 분포 · 월별 흐름] ===
function RatingPanel({ insights }: { insights: ProductInsights }) {
  const total = insights.review_count || 1;
  return (
    <section className="panel half">
      <h2>별점 분포</h2>
      <div className="rating-big" style={{ marginTop: 12 }}>
        <b>{insights.average_rating?.toFixed(2) ?? "–"}</b>
        <span className="star">★★★★★</span>
        <span className="sentiment-empty">리뷰 {insights.review_count}건</span>
      </div>
      {[5, 4, 3, 2, 1].map((star) => {
        const count = insights.rating_distribution[String(star)] ?? 0;
        return (
          <div key={star} className="rating-row">
            <span>{star}점</span>
            <div className="rating-track">
              <span style={{ width: `${(count / total) * 100}%` }} />
            </div>
            <span style={{ textAlign: "right", color: "var(--muted)" }}>{count}</span>
          </div>
        );
      })}
    </section>
  );
}

function MonthlyPanel({ insights }: { insights: ProductInsights }) {
  return (
    <section className="panel">
      <h2>월별 흐름</h2>
      <p className="sub">리뷰 수와 평균 별점은 전체, 좋아요/아쉬워요는 분석된 리뷰 기준</p>
      <div className="months">
        {insights.monthly.map((month) => (
          <div key={month.month} className="month">
            <b>{monthLabel(month.month)}</b>
            <span>
              리뷰 {month.review_count}건 · <span className="star">★</span> {month.average_rating.toFixed(2)}
            </span>
            <span style={{ color: "var(--muted)" }}>분석 {month.analyzed_count}건</span>
            {month.analyzed_count > 0 ? (
              <>
                <span style={{ color: "var(--positive)" }}>👍 {percent(month.positive_review_share)}</span>
                <span style={{ color: "var(--negative)" }}>👎 {percent(month.negative_review_share)}</span>
              </>
            ) : (
              <span className="sentiment-empty">분석 전</span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// === [페이지] ===
export default function ProductPage() {
  const { productId = "" } = useParams();
  const navigate = useNavigate();
  const product = useQuery({ queryKey: ["product", productId], queryFn: () => api.product(productId) });
  const insights = useQuery({ queryKey: ["insights", productId], queryFn: () => api.insights(productId) });
  const faq = useQuery({ queryKey: ["faq", productId], queryFn: () => fetchFaq(productId) });

  if (product.isError || insights.isError) {
    return (
      <main className="page">
        <div className="error">상품 리포트를 불러오지 못했어요.</div>
      </main>
    );
  }
  if (!product.data || !insights.data) {
    return (
      <main className="page">
        <div className="skeleton" style={{ height: 420 }} />
      </main>
    );
  }

  return (
    <main className="page">
      <button className="back" onClick={() => navigate(-1)}>
        ← 목록으로
      </button>
      <Hero product={product.data} insights={insights.data} />
      <div className="report">
        <SummaryPanel insights={insights.data} />
        <AiSummaryPanel faq={faq.data} />
        <AspectPanel insights={insights.data} />
        <ComplaintPanel insights={insights.data} />
        <ChangePanel insights={insights.data} />
        <RatingPanel insights={insights.data} />
        <MonthlyPanel insights={insights.data} />
        <section className="panel">
          <h2>리뷰 원문</h2>
          <p className="sub">색칠된 문장이 AI가 판단 근거로 쓴 원문 구간이에요 (파랑 = 좋아요, 주홍 = 아쉬워요)</p>
          <ReviewList productId={productId} months={product.data.available_months} aspects={insights.data.aspects} />
        </section>
      </div>
      <p className="footer-note">
        분석 버전 {insights.data.analysis.analysis_version} · 모델 {insights.data.analysis.model ?? "–"} · 프롬프트{" "}
        {insights.data.analysis.prompt_version ?? "–"} · 데이터 {insights.data.data_version}
      </p>

      {/* === [8. 하단 고정 바] 구매 버튼 대신 AI 질문(근거 인용형 Agent) === */}
      <AskPanel productId={productId} productName={product.data.title_ko ?? product.data.title} />
    </main>
  );
}
