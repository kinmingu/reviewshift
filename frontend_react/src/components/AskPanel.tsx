// =====================================================================
// [리뷰 챗봇] 하단 고정 바 → 대화 창 (RAG: 리뷰 검색 + SQL 리포트 → 답변)
// - 질문마다 서버 Agent(LangGraph)가 MCP 도구로 리포트·관련 리뷰를 조회해 답하고, 인용 리뷰 ID·수치를 검증한 답만 보여 줍니다.
// - 이전 대화는 문맥으로만 함께 보냅니다(숫자·근거는 매번 새로 조회).
// - 자주 묻는 질문은 미리 만들어 저장한 답을 즉시 보여 주고, 처음 보는 질문만 실시간으로 답합니다.
// - 실시간 답변은 CPU 로컬 모델이라 1~4분 걸릴 수 있어 경과 시간을 표시합니다.
// =====================================================================
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { askQuestion, fetchFaq, type AgentAnswer, type FaqItem } from "../api";
import { dateLabel } from "../lib/format";

type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; result: AgentAnswer }
  | { role: "error"; content: string };

const TYPING_HINT = "이거 샀는데 금방 고장 났어요. 원래 이런 문제가 있나요?";
const TOOL_NAMES: Record<string, string> = {
  get_product_report: "리뷰 리포트 집계",
  search_reviews: "관련 리뷰 검색",
};

// === [대화 보관] 같은 브라우저 탭에서는 새로고침해도 대화를 유지합니다 ===
const storageKey = (productId: string) => `reviewshift-chat-${productId}`;
function loadMessages(productId: string): Message[] {
  try {
    return JSON.parse(sessionStorage.getItem(storageKey(productId)) ?? "[]") as Message[];
  } catch {
    return [];
  }
}

function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{seconds}초</>;
}

// === [답변 말풍선] 답변 · 근거 리뷰 · 도구 기록 ===
function AnswerBubble({ result }: { result: AgentAnswer }) {
  if (result.status !== "answered") {
    return (
      <div className="bubble bot">
        근거를 확인할 수 있는 답변을 만들지 못했어요. 질문을 조금 바꿔서 다시 물어봐 주세요.
        <small className="bubble-meta">{result.failure_reason}</small>
      </div>
    );
  }
  return (
    <div className="bubble bot">
      <div className="tags" style={{ marginTop: 0 }}>
        {result.cached && (
          <span className="badge done">
            저장된 답변{result.analyzed_count !== null && ` · 리뷰 ${result.analyzed_count}건 분석 기준`}
            {result.generated_at && ` · ${dateLabel(result.generated_at)}`}
          </span>
        )}
        {result.is_stale && <span className="badge warn">이후 분석이 더 진행됨 · 갱신 예정</span>}
        {result.is_provisional && <span className="badge ai">일부 리뷰만 분석된 잠정 결과</span>}
      </div>
      <p className="ask-answer">{result.answer}</p>
      {result.citations.length > 0 && (
        <details open>
          <summary className="bubble-meta">근거 리뷰 {result.citations.length}건</summary>
          {result.citations.map((citation) => (
            <blockquote key={citation.review_id} className="quote">
              {citation.excerpt.replace(/<br\s*\/?>/gi, " ")}
              <small>
                ★{citation.rating} · {citation.date}
              </small>
            </blockquote>
          ))}
        </details>
      )}
      {result.notice && <small className="bubble-meta">{result.notice}</small>}
      <details>
        <summary className="bubble-meta">
          도구 {result.tool_calls.length}개 · {result.cached ? "생성 당시 " : ""}
          {(result.latency_ms / 1000).toFixed(0)}초 · {result.model}
        </summary>
        <ul className="tool-log">
          {result.tool_calls.map((call, index) => (
            <li key={index}>
              {call.ok ? "✓" : "✗"} {call.transport?.startsWith("mcp") ? "[MCP] " : ""}
              {TOOL_NAMES[call.tool] ?? call.tool} — {call.summary}
            </li>
          ))}
          <li>
            답변 생성 {result.generation_attempts}회 · {result.prompt_version}
          </li>
        </ul>
      </details>
    </div>
  );
}

export default function AskPanel({ productId, productName }: { productId: string; productName: string }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>(() => loadMessages(productId));
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const faq = useQuery({ queryKey: ["faq", productId], queryFn: () => fetchFaq(productId) });

  useEffect(() => {
    sessionStorage.setItem(storageKey(productId), JSON.stringify(messages));
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, productId]);

  const ask = useMutation({
    mutationFn: ({ question, history }: { question: string; history: { role: "user" | "assistant"; content: string }[] }) =>
      askQuestion(productId, question, history),
    onSuccess: (result) => {
      setMessages((previous) => [...previous, { role: "assistant", content: result.answer ?? "", result }]);
      // 새로 저장된 답이 FAQ 목록에도 반영되도록 다시 불러옵니다.
      queryClient.invalidateQueries({ queryKey: ["faq", productId] });
    },
    onError: (error) => setMessages((previous) => [...previous, { role: "error", content: (error as Error).message }]),
  });

  const send = (value: string) => {
    const question = value.trim();
    if (question.length < 2 || ask.isPending) return;
    // 검증을 통과한 답변과 사용자 질문만 문맥으로 보냅니다(최근 6개).
    const history = messages
      .filter((message) => message.role === "user" || (message.role === "assistant" && message.result.status === "answered"))
      .map((message) => ({ role: message.role as "user" | "assistant", content: message.content }))
      .slice(-6);
    setMessages((previous) => [...previous, { role: "user", content: question }]);
    setInput("");
    ask.mutate({ question, history });
  };

  // === [자주 묻는 질문 선택] 저장된 최신 답이 있으면 즉시, 없으면 실시간으로 묻습니다 ===
  const pickFaq = (item: FaqItem) => {
    if (ask.isPending) return;
    if (item.answer && !item.answer.is_stale) {
      const answer = item.answer;
      setMessages((previous) => [
        ...previous,
        { role: "user", content: item.question },
        { role: "assistant", content: answer.answer ?? "", result: answer },
      ]);
      return;
    }
    send(item.question);
  };

  const faqButtons = (faq.data?.items ?? []).filter((item) => item.key !== "summary");

  return (
    <>
      {open && (
        <div className="ask-sheet chat" role="dialog" aria-label="리뷰 챗봇">
          {/* === [헤더] === */}
          <div className="ask-sheet-head">
            <div>
              <b>리뷰 챗봇</b>
              <small className="bubble-meta">{productName} · 실제 리뷰 근거로만 답해요</small>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              {messages.length > 0 && !ask.isPending && (
                <button className="link-btn" onClick={() => setMessages([])}>
                  새 대화
                </button>
              )}
              <button className="link-btn" onClick={() => setOpen(false)}>
                닫기
              </button>
            </div>
          </div>

          {/* === [대화 내용] === */}
          <div className="chat-log">
            {messages.length === 0 && (
              <div className="bubble bot">
                산 제품에 문제가 있거나 사기 전에 궁금한 점을 물어보세요. 다른 구매자 리뷰를 찾아서 비슷한 사례가
                있는지, 얼마나 자주 나오는지 알려 드려요.
                <small className="bubble-meta">⚡ 표시는 미리 준비된 답이라 바로 나와요.</small>
              </div>
            )}
            {messages.map((message, index) =>
              message.role === "user" ? (
                <div key={index} className="bubble me">
                  {message.content}
                </div>
              ) : message.role === "assistant" ? (
                <AnswerBubble key={index} result={message.result} />
              ) : (
                <div key={index} className="bubble bot error-bubble">
                  답변을 받지 못했어요: {message.content}
                </div>
              ),
            )}
            {ask.isPending && (
              <div className="bubble bot">
                <span className="badge ai">
                  리뷰를 찾아 읽는 중 · <Elapsed />
                </span>
                <small className="bubble-meta">로컬 CPU 모델이라 1~4분 걸릴 수 있어요.</small>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* === [자주 묻는 질문 버튼] 입력창 바로 위, 대화 중에도 언제든 누를 수 있습니다 === */}
          {faqButtons.length > 0 && (
            <div className="tags faq-row">
              {faqButtons.map((item) => (
                <button key={item.key} className="chip" onClick={() => pickFaq(item)} disabled={ask.isPending}>
                  {item.answer && !item.answer.is_stale ? "⚡ " : ""}
                  {item.label}
                </button>
              ))}
            </div>
          )}

          {/* === [입력창] === */}
          <form
            className="ask-form"
            onSubmit={(event) => {
              event.preventDefault();
              send(input);
            }}
          >
            <input
              value={input}
              maxLength={500}
              onChange={(event) => setInput(event.target.value)}
              placeholder={ask.isPending ? "답변을 기다리는 중이에요" : `예: ${TYPING_HINT}`}
              aria-label="질문"
              disabled={ask.isPending}
            />
            <button className="ask" disabled={ask.isPending || input.trim().length < 2}>
              보내기
            </button>
          </form>
        </div>
      )}

      {/* === [하단 고정 바] 구매 버튼 자리에 리뷰 챗봇 === */}
      <div className="dock">
        <div className="dock-inner">
          <p>이 제품 샀는데 문제가 있나요? 다른 구매자 리뷰를 근거로 AI가 답해 드려요.</p>
          <button className="ask" onClick={() => setOpen(!open)}>
            {open ? "챗봇 닫기" : `리뷰 챗봇에게 물어보기${messages.length ? ` (${messages.filter((m) => m.role === "user").length})` : ""}`}
          </button>
        </div>
      </div>
    </>
  );
}
