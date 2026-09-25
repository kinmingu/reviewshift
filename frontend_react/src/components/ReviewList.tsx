// =====================================================================
// [리뷰 원문 목록] 의미 검색 · 월 탭 · 좋아요/아쉬워요 필터 · 항목 필터 · 근거 문장 강조
// 근거 강조는 서버가 원문에서 검증한 구간(evidence_span)만 표시합니다.
// =====================================================================
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, searchReviews, type AspectInsight, type Review, type ReviewLabel } from "../api";
import { POLARITY_LABEL, dateLabel, labelName, monthLabel } from "../lib/format";

// Amazon 원문에는 <br /> 태그가 글자로 들어 있어, 위치 계산이 끝난 조각을 표시할 때만 줄바꿈으로 바꿉니다.
const display = (value: string) => value.replace(/<br\s*\/?>/gi, "\n");

// === [근거 강조] 원문에서 근거 구간을 찾아 극성 색으로 표시합니다(겹치면 앞의 것 우선) ===
function highlight(text: string, labels: ReviewLabel[]): ReactNode[] {
  const ranges = labels
    .map((label) => ({ start: text.indexOf(label.evidence_span), label }))
    .filter((item) => item.start >= 0)
    .map((item) => ({ ...item, end: item.start + item.label.evidence_span.length }))
    .sort((a, b) => a.start - b.start);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(({ start, end, label }, index) => {
    if (start < cursor) return;
    nodes.push(display(text.slice(cursor, start)));
    nodes.push(
      <mark key={index} className={label.polarity} title={`${labelName(label)} · ${POLARITY_LABEL[label.polarity]}`}>
        {display(text.slice(start, end))}
      </mark>,
    );
    cursor = end;
  });
  nodes.push(display(text.slice(cursor)));
  return nodes;
}

const STATUS_TEXT: Record<Review["analysis_status"], string> = {
  not_started: "AI 분석 전",
  pending: "AI 분석 대기",
  running: "AI 분석 중",
  succeeded: "분석 완료 · 평가 항목 없음",
  failed: "AI 분석 실패",
};

// === [리뷰 한 건] 영어 원문 기본, 번역이 캐시된 리뷰만 한국어 보기 제공 ===
function ReviewItem({ review }: { review: Review }) {
  const [korean, setKorean] = useState(false);
  const showKorean = korean && Boolean(review.text_ko);
  const title = showKorean ? review.title_ko : review.title;
  return (
    <article className="review" id={`review-${review.id}`}>
      <div className="review-head">
        <span className="star">{"★".repeat(review.rating)}</span>
        <span style={{ color: "var(--line)" }}>{"★".repeat(5 - review.rating)}</span>
        <span>{dateLabel(review.reviewed_at)}</span>
        {review.text_ko && (
          <button className="link-btn" onClick={() => setKorean(!korean)}>
            {showKorean ? "영어 원문 보기" : "자동 번역 보기"}
          </button>
        )}
      </div>
      {title && (
        <div className="review-title">{showKorean ? title : highlight(title, review.labels)}</div>
      )}
      <div className="review-text">
        {showKorean ? display(review.text_ko ?? "") : highlight(review.text, review.labels)}
      </div>
      {showKorean && <p className="sentiment-empty">자동 번역입니다. 정확한 근거는 영어 원문 기준이에요.</p>}
      <div className="tags">
        {review.labels.length === 0 && <span className="tag">{STATUS_TEXT[review.analysis_status]}</span>}
        {review.labels.map((label, index) => (
          <span key={index} className={`tag ${label.polarity}`}>
            {labelName(label)} · {POLARITY_LABEL[label.polarity]}
          </span>
        ))}
      </div>
    </article>
  );
}

interface Props {
  productId: string;
  months: string[];
  aspects: AspectInsight[];
}

// === [리뷰에서 찾기] 한국어로 입력해도 영어 리뷰를 의미로 찾습니다(상품의 저장 월 전체 대상) ===
function SemanticSearch({ productId, months }: { productId: string; months: string[] }) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const result = useQuery({
    queryKey: ["search", productId, query],
    queryFn: () => searchReviews(productId, query, months),
    enabled: query.length > 0,
  });
  return (
    <>
      <form
        className="semantic"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(input.trim());
        }}
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="리뷰에서 찾기 · 예: 너무 뜨거워요, 금방 고장, 소음"
          maxLength={300}
          aria-label="리뷰 의미 검색"
        />
        <button>찾기</button>
        {query && (
          <button
            type="button"
            style={{ background: "var(--paper-deep)", color: "var(--ink-soft)" }}
            onClick={() => {
              setQuery("");
              setInput("");
            }}
          >
            해제
          </button>
        )}
      </form>
      {query && (
        <div style={{ marginBottom: 20 }}>
          {result.isLoading && <p className="sub">의미가 비슷한 리뷰를 찾는 중…</p>}
          {result.isError && <div className="error">{(result.error as Error).message}</div>}
          {result.data && (
            <>
              <p className="sub">
                “{result.data.query}”와 의미가 가까운 리뷰 {result.data.items.length}건
                {result.data.embedded_reviews < result.data.total_reviews &&
                  ` · 검색 준비된 리뷰 ${result.data.embedded_reviews}/${result.data.total_reviews}건 대상`}
              </p>
              {result.data.items.map((item) => (
                <div key={item.review.id}>
                  <span className="similarity">유사도 {(item.similarity * 100).toFixed(0)}</span>
                  <ReviewItem review={item.review} />
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </>
  );
}

export default function ReviewList({ productId, months, aspects }: Props) {
  const [month, setMonth] = useState(months[months.length - 1]);
  const [polarity, setPolarity] = useState<"" | "positive" | "negative">("");
  const [aspect, setAspect] = useState("");

  const reviews = useInfiniteQuery({
    queryKey: ["reviews", productId, month, polarity, aspect],
    queryFn: ({ pageParam }) =>
      api.reviews(productId, { month, polarity: polarity || undefined, aspect: aspect || undefined, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (pages.length * 20 < last.total ? pages.length + 1 : undefined),
  });
  const items = reviews.data?.pages.flatMap((page) => page.items) ?? [];
  const total = reviews.data?.pages[0]?.total ?? 0;
  // 서버 필터는 상위 항목(aspect) 단위이므로 같은 상위 항목은 한 번만 보여 줍니다.
  const aspectOptions = Array.from(
    new Map(aspects.map((item) => [item.aspect, item.aspect_name_ko ?? item.aspect])).entries(),
  );

  return (
    <>
      <SemanticSearch productId={productId} months={months} />
      <div className="toolbar">
        {months.map((value) => (
          <button key={value} className={`chip ${value === month ? "active" : ""}`} onClick={() => setMonth(value)}>
            {monthLabel(value)}
          </button>
        ))}
        <span style={{ width: 8 }} />
        <button className={`chip ${polarity === "" ? "active" : ""}`} onClick={() => setPolarity("")}>
          전체
        </button>
        <button className={`chip pos ${polarity === "positive" ? "active" : ""}`} onClick={() => setPolarity("positive")}>
          👍 좋아요
        </button>
        <button className={`chip neg ${polarity === "negative" ? "active" : ""}`} onClick={() => setPolarity("negative")}>
          👎 아쉬워요
        </button>
        {aspectOptions.length > 0 && (
          <select className="chip" value={aspect} onChange={(event) => setAspect(event.target.value)} aria-label="평가 항목">
            <option value="">모든 항목</option>
            {aspectOptions.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="sub">
        {monthLabel(month)} 리뷰 {total}건
        {(polarity || aspect) && " · 필터는 AI 분석이 끝난 리뷰에만 적용돼요"}
      </p>
      {reviews.isError && <div className="error">리뷰를 불러오지 못했어요.</div>}
      {items.map((review) => (
        <ReviewItem key={review.id} review={review} />
      ))}
      {!reviews.isLoading && items.length === 0 && <p className="empty">조건에 맞는 리뷰가 없어요.</p>}
      {reviews.hasNextPage && (
        <button className="more" onClick={() => reviews.fetchNextPage()} disabled={reviews.isFetchingNextPage}>
          {reviews.isFetchingNextPage ? "불러오는 중…" : "리뷰 더 보기"}
        </button>
      )}
    </>
  );
}
