// =====================================================================
// [AI에게 리뷰 물어보기] 하단 고정 바 → 질문 패널
// 서버 Agent가 SQL 리포트와 리뷰 검색 결과로 답하고, 인용 리뷰 ID·수치를 검증한 답만 보여 줍니다.
// CPU에서 로컬 모델을 쓰므로 답변까지 1~4분 걸릴 수 있어 진행 상태를 계속 표시합니다.
// =====================================================================
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { askQuestion } from "../api";

const EXAMPLES = ["금방 고장 나나요?", "배송이나 포장 문제는 없나요?", "가격 대비 괜찮은가요?"];
const TOOL_NAMES: Record<string, string> = {
  get_product_report: "리뷰 리포트 집계 조회",
  search_reviews: "관련 리뷰 검색",
};

function Elapsed({ running }: { running: boolean }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return <>{seconds}초</>;
}

export default function AskPanel({ productId }: { productId: string }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const ask = useMutation({ mutationFn: (value: string) => askQuestion(productId, value) });

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (trimmed.length < 2 || ask.isPending) return;
    setQuestion(trimmed);
    ask.mutate(trimmed);
  };

  return (
    <>
      {open && (
        <div className="ask-sheet" role="dialog" aria-label="AI에게 리뷰 물어보기">
          <div className="ask-sheet-head">
            <b>AI에게 리뷰 물어보기</b>
            <button className="link-btn" onClick={() => setOpen(false)}>
              닫기
            </button>
          </div>
          <p className="sub">실제 리뷰에서 찾은 근거로만 답해요. 숫자는 서버가 계산한 값만 써요.</p>

          {/* === [질문 입력] === */}
          <form
            className="ask-form"
            onSubmit={(event) => {
              event.preventDefault();
              submit(question);
            }}
          >
            <input
              value={question}
              maxLength={500}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="예: 소음이 심한가요?"
              aria-label="질문"
            />
            <button className="ask" disabled={ask.isPending || question.trim().length < 2}>
              {ask.isPending ? "답변 중…" : "질문"}
            </button>
          </form>
          <div className="tags">
            {EXAMPLES.map((example) => (
              <button key={example} className="chip" onClick={() => submit(example)} disabled={ask.isPending}>
                {example}
              </button>
            ))}
          </div>

          {/* === [진행·결과] === */}
          {ask.isPending && (
            <div className="ask-wait">
              <span className="badge ai">
                AI가 리뷰를 읽는 중 · <Elapsed running={ask.isPending} />
              </span>
              <p className="sub">로컬 CPU 모델이라 1~4분 걸릴 수 있어요. 창을 닫지 말아 주세요.</p>
            </div>
          )}
          {ask.isError && <div className="error">{(ask.error as Error).message}</div>}
          {ask.data && (
            <div className="ask-result">
              {ask.data.status === "answered" ? (
                <>
                  {ask.data.is_provisional && <span className="badge ai">일부 리뷰만 분석된 잠정 결과</span>}
                  <p className="ask-answer">{ask.data.answer}</p>
                  {ask.data.citations.length > 0 && <h4>근거 리뷰</h4>}
                  {ask.data.citations.map((citation) => (
                    <blockquote key={citation.review_id} className="quote">
                      {citation.excerpt.replace(/<br\s*\/?>/gi, " ")}
                      <small>
                        ★{citation.rating} · {citation.date} · 리뷰 ID {citation.review_id.slice(0, 18)}…
                      </small>
                    </blockquote>
                  ))}
                </>
              ) : (
                <div className="error">
                  근거를 검증할 수 있는 답변을 만들지 못했어요. 질문을 바꿔 다시 시도해 주세요.
                  <br />
                  <small>{ask.data.failure_reason}</small>
                </div>
              )}
              {ask.data.notice && <p className="sub">{ask.data.notice}</p>}
              <details className="original" style={{ marginTop: 12 }}>
                <summary>
                  AI가 사용한 도구 {ask.data.tool_calls.length}개 · {(ask.data.latency_ms / 1000).toFixed(0)}초 ·{" "}
                  {ask.data.model}
                </summary>
                <ul>
                  {ask.data.tool_calls.map((call, index) => (
                    <li key={index}>
                      {call.ok ? "✓" : "✗"} {TOOL_NAMES[call.tool] ?? call.tool} — {call.summary} ({call.duration_ms}ms)
                    </li>
                  ))}
                  <li>
                    답변 생성 {ask.data.generation_attempts}회 · 프롬프트 {ask.data.prompt_version}
                  </li>
                </ul>
              </details>
            </div>
          )}
        </div>
      )}

      {/* === [하단 고정 바] 구매 버튼 자리에 AI 질문 === */}
      <div className="dock">
        <div className="dock-inner">
          <p>이 상품 리뷰가 궁금하면 AI에게 물어보세요. 답변에는 실제 리뷰가 인용돼요.</p>
          <button className="ask" onClick={() => setOpen(!open)}>
            {open ? "질문 창 닫기" : "AI에게 리뷰 물어보기"}
          </button>
        </div>
      </div>
    </>
  );
}
