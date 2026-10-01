// =====================================================================
// [리뷰 챗봇 대화] 선택한 제품 하나에 대한 대화 본문 (RAG: 리뷰 검색 + SQL 리포트 → 답변)
// - 화면 오른쪽 아래의 떠 있는 챗봇 창(ChatWidget)이 제품을 고른 뒤 이 컴포넌트를 보여 줍니다.
// - 질문을 보내면 즉시 답(LLM 없이 DB 분석 결과·관련 리뷰, MCP 도구 quick_answer)과
//   빠른 AI 답변(요약본 RAG, 약 30~40초)을 동시에 시작합니다.
// - 즉시 답은 '찾는 과정'으로 한 글자씩 보여 주고(진행 말풍선), AI가 답을 쓰고 검증하는 단계도 표시합니다.
//   서버 검증(인용 번호·수치)을 통과한 최종 답만 대화에 남기고, 진행 말풍선은 한 줄로 접습니다.
// - 근거 리뷰는 기본으로 접어 두고, '근거 보여줘'처럼 물으면 직전 답의 근거 리뷰를 펼쳐 보여 줍니다.
// - 가까운 FAQ 저장 답이 있으면 AI 답은 취소하고 저장 답을 보여 줍니다.
// - AI 답이 실패하면 즉시 답(리뷰 데이터 정리)을 대신 보여 줍니다.
// =====================================================================
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  askQuestionStream,
  fetchFaq,
  quickAnswer,
  type AgentAnswer,
  type FaqItem,
  type QuickAnswer,
  type StreamSource,
} from "../api";
import { dateLabel } from "../lib/format";

type Citation = AgentAnswer["citations"][number];
type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; result: AgentAnswer; createdAt?: number }
  | { role: "quick"; content: string; result: QuickAnswer; createdAt?: number }
  | { role: "evidence"; content: string; citations: Citation[] }
  | { role: "error"; content: string; question?: string };

type Live = {
  question: string;
  status: string;
  text: string;
  retried: boolean;
  sources: StreamSource[];
};

const TYPING_HINT = "이거 샀는데 금방 고장 났어요. 원래 이런 문제가 있나요?";
const TOOL_NAMES: Record<string, string> = {
  quick_answer: "즉시 답(리뷰 데이터)",
  get_product_report: "리뷰 리포트 집계",
  search_reviews: "관련 리뷰 검색",
};
// '근거 보여줘', '출처가 뭐야' 같은 짧은 요청은 AI에게 다시 묻지 않고 직전 답의 근거 리뷰를 보여 줍니다.
const EVIDENCE_REQUEST = /(근거|출처|원문|인용)/;
const SHOW_REQUEST = /(보여|알려|뭐|어디|확인)/;

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

// === [타자 효과] 방금 도착한 글만 한 글자씩 보여 줍니다(새로고침으로 복원한 대화는 바로 표시) ===
// 찾는 과정을 천천히 쓰는 동안 뒤의 AI 답이 준비되므로 기다리는 느낌이 줄어듭니다.
const PROGRESS_CHAR_MS = 40;
const ANSWER_CHAR_MS = 30;

function useTyping(text: string, createdAt: number | undefined, charMs: number) {
  const fresh = createdAt !== undefined && Date.now() - createdAt < 3000;
  const [shown, setShown] = useState(fresh ? 0 : text.length);
  useEffect(() => {
    if (shown >= text.length) return;
    const timer = setTimeout(() => setShown((value) => Math.min(text.length, value + 1)), charMs);
    return () => clearTimeout(timer);
  }, [shown, text, charMs]);
  return { typed: text.slice(0, shown), done: shown >= text.length };
}

const clean = (value: string) => value.replace(/<br\s*\/?>/gi, " ");

// === [찾는 과정 문구] 즉시 답의 DB 값(분석 수·항목별 언급 수)을 그대로 옮깁니다(새로 계산하지 않음) ===
function progressText(result: QuickAnswer): string {
  const lines = [`🔍 분석한 리뷰 ${result.analyzed_reviews}건에서 질문과 관련된 항목을 찾았어요`];
  let mixed = false;
  for (const aspect of result.aspects) {
    if (aspect.mention_count > 0) {
      lines.push(
        `· ${aspect.name_ko}: ${aspect.mention_count}건 언급 (좋아요 ${aspect.positive_count}건, 아쉬워요 ${aspect.negative_count}건)`,
      );
      mixed = mixed || aspect.positive_count + aspect.negative_count > aspect.mention_count;
    } else {
      lines.push(`· ${aspect.name_ko}: 언급한 리뷰 없음`);
    }
  }
  if (mixed) lines.push("(한 리뷰가 좋은 점과 아쉬운 점을 함께 말하면 양쪽에 모두 세어요)");
  if (result.related_reviews.length > 0) lines.push(`📄 질문과 비슷한 실제 리뷰 ${result.related_reviews.length}건을 찾았어요`);
  if (result.is_small_sample) lines.push("분석한 리뷰가 적어 참고용으로 봐 주세요");
  if (result.matched_faq) lines.push("⚡ 미리 검증해 둔 답을 찾았어요");
  return lines.join("\n");
}
const progressMs = (result: QuickAnswer) => progressText(result).length * PROGRESS_CHAR_MS;

// === [근거 리뷰 목록] 답변 아래(접힘) 또는 '근거 보여줘' 요청에 씁니다 ===
function CitationList({ citations }: { citations: Citation[] }) {
  return (
    <>
      {citations.map((citation) => (
        <blockquote key={citation.review_id} className="quote">
          {clean(citation.excerpt)}
          <small>
            ★{citation.rating} · {citation.date}
          </small>
        </blockquote>
      ))}
    </>
  );
}

// === [진행 말풍선] 찾는 과정을 한 글자씩 쓰고, AI가 답을 쓰는 단계를 보여 줍니다. 답이 나오면 한 줄로 접힘 ===
function ProgressBubble({
  result,
  createdAt,
  live,
  finished,
  onRetry,
}: {
  result: QuickAnswer;
  createdAt?: number;
  live: Live | null;
  finished: boolean;
  onRetry: () => void;
}) {
  const text = progressText(result);
  const { typed, done } = useTyping(text, createdAt, PROGRESS_CHAR_MS);
  const found = result.aspects.filter((aspect) => aspect.mention_count > 0).length;

  if (finished && done) {
    return (
      <details className="progress-done">
        <summary>
          ✓ 리뷰 {result.analyzed_reviews}건에서 관련 항목 {found}개, 비슷한 리뷰 {result.related_reviews.length}건을
          확인했어요
        </summary>
        <p className="progress-lines">{text}</p>
      </details>
    );
  }

  const reading = live !== null && live.sources.length > 0;
  return (
    <div className="bubble bot progress-bubble">
      <p className="progress-lines">
        {typed}
        {!done && <span className="typing-caret" />}
      </p>
      {done && live && (
        <ul className="progress-steps">
          <li className={reading ? "ok" : "active"}>
            {reading ? `AI가 읽을 근거 리뷰 ${live.sources.length}건을 골랐어요` : `${live.status}…`}
          </li>
          {reading && (
            <li className="active">
              {live.retried
                ? "검증에서 걸러진 답을 고쳐 쓰는 중…"
                : live.text
                  ? "AI가 답을 쓰는 중… 다 쓰면 인용과 숫자를 검증해요"
                  : "AI가 근거 리뷰를 읽는 중…"}{" "}
              · <Elapsed />
            </li>
          )}
        </ul>
      )}
      {done && !live && !finished && !result.matched_faq && (
        <div className="progress-steps">
          <small className="bubble-meta">새 질문으로 넘어가 이 질문의 AI 답은 멈췄어요.</small>
          <button className="chip" style={{ marginTop: 6 }} onClick={onRetry}>
            ✦ 이 질문 다시 묻기 (약 30~40초)
          </button>
        </div>
      )}
    </div>
  );
}

// === [답변 말풍선] 검증된 최종 답. 근거 리뷰·도구 기록은 접어 둡니다 ===
function AnswerBubble({
  result,
  createdAt,
  fallback,
}: {
  result: AgentAnswer;
  createdAt?: number;
  fallback?: QuickAnswer;
}) {
  const { typed, done } = useTyping(result.answer ?? "", createdAt, ANSWER_CHAR_MS);
  if (result.status !== "answered") {
    return <FallbackBubble fallback={fallback} reason={result.failure_reason ?? undefined} />;
  }
  return (
    <div className="bubble bot">
      {(result.cached || result.is_stale || result.is_provisional) && (
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
      )}
      <p className="ask-answer">
        {typed}
        {!done && <span className="typing-caret" />}
      </p>
      {done && (
        <>
          {result.notice && <small className="bubble-meta">{result.notice}</small>}
          {result.citations.length > 0 && (
            <details>
              <summary className="bubble-meta">근거 리뷰 {result.citations.length}건 보기</summary>
              <CitationList citations={result.citations} />
            </details>
          )}
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
        </>
      )}
    </div>
  );
}

// === [대체 답] AI 답을 만들거나 검증하지 못했을 때, 즉시 답(리뷰 데이터 정리)을 대신 보여 줍니다 ===
function FallbackBubble({ fallback, reason }: { fallback?: QuickAnswer; reason?: string }) {
  return (
    <div className="bubble bot">
      {fallback ? (
        <>
          <span className="badge done">리뷰 데이터 기준 답</span>
          <p className="ask-answer">
            AI 답을 검증하지 못해, 리뷰 데이터로 정리한 내용을 보여 드려요.{"\n"}
            {progressText(fallback)}
          </p>
          {fallback.related_reviews.length > 0 && (
            <details>
              <summary className="bubble-meta">질문과 비슷한 실제 리뷰 {fallback.related_reviews.length}건 보기</summary>
              {fallback.related_reviews.map((review) => (
                <blockquote key={review.review_id} className="quote">
                  {clean(review.text_ko ?? review.text)}
                  <small>
                    ★{review.rating} · {review.date}
                    {review.text_ko ? " · 자동 번역" : ""}
                  </small>
                </blockquote>
              ))}
            </details>
          )}
        </>
      ) : (
        <>근거를 확인할 수 있는 답변을 만들지 못했어요. 질문을 조금 바꿔서 다시 물어봐 주세요.</>
      )}
      {reason && <small className="bubble-meta">{reason}</small>}
    </div>
  );
}

export function clearChat(productId: string) {
  try {
    sessionStorage.removeItem(storageKey(productId));
  } catch {
    // 저장소를 쓸 수 없는 브라우저에서는 대화가 화면에만 남습니다.
  }
}

export default function ProductChat({
  productId,
  initialQuestion,
  intro,
}: {
  productId: string;
  initialQuestion?: string | null;
  intro?: ReactNode;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>(() => loadMessages(productId));
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const faq = useQuery({ queryKey: ["faq", productId], queryFn: () => fetchFaq(productId) });

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey(productId), JSON.stringify(messages));
    } catch {
      // 저장 실패는 무시합니다(대화는 화면에 그대로 있음).
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, productId]);

  // === [빠른 AI 답변] 요약본 RAG. 진행 단계만 보여 주고, 서버 검증을 통과한 최종 답을 대화에 붙입니다 ===
  const [live, setLive] = useState<Live | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const runRef = useRef(0);
  // 찾는 과정이 다 써질 때까지 AI 답을 붙이지 않기 위한 약속(저장된 AI 답은 즉시 답보다 먼저 올 수 있음).
  const quickRef = useRef<Promise<{ question: string; showUntil: number } | null>>(Promise.resolve(null));
  const ask = useMutation({
    mutationFn: async ({ question, history }: { question: string; history: { role: "user" | "assistant"; content: string }[] }) => {
      // 새 질문이 오면 진행 중인 이전 AI 답은 취소합니다(CPU를 새 질문에 씀).
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const run = ++runRef.current;
      const update = (change: (current: Live) => Live) =>
        setLive((current) => (current && run === runRef.current ? change(current) : current));
      const received: { final: AgentAnswer | null } = { final: null };
      setLive({ question, status: "관련 리뷰와 통계를 찾는 중", text: "", retried: false, sources: [] });
      try {
        await askQuestionStream(
          productId,
          question,
          history,
          (event) => {
            if (event.type === "status") update((current) => ({ ...current, status: event.message }));
            if (event.type === "sources") update((current) => ({ ...current, sources: event.items }));
            if (event.type === "token") update((current) => ({ ...current, text: current.text + event.text }));
            // 검증에서 걸러진 답은 지우고 다시 씁니다.
            if (event.type === "retry") update((current) => ({ ...current, text: "", retried: true }));
            if (event.type === "done") received.final = event.result;
            if (event.type === "error") throw new Error(event.message);
          },
          controller.signal,
        );
        // 화면 순서를 '찾는 과정 → 최종 답'으로 지킵니다: 같은 질문의 찾는 과정이 다 써진 뒤에 답을 붙입니다.
        const shown = await quickRef.current;
        if (shown && shown.question === question) {
          await new Promise((resolve) => setTimeout(resolve, Math.max(0, shown.showUntil - Date.now())));
        }
        if (controller.signal.aborted) throw new DOMException("aborted", "AbortError");
      } finally {
        if (run === runRef.current) setLive(null);
      }
      if (!received.final) throw new Error("답변을 끝까지 받지 못했어요.");
      return received.final;
    },
    onSuccess: (result) => {
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: result.answer ?? "", result, createdAt: Date.now() },
      ]);
      // 새로 저장된 답이 FAQ 목록에도 반영되도록 다시 불러옵니다.
      queryClient.invalidateQueries({ queryKey: ["faq", productId] });
    },
    onError: (error, variables) => {
      // 사용자가 새 질문을 보냈거나 FAQ 답으로 충분해 취소한 경우는 오류로 보이지 않습니다.
      if ((error as Error).name === "AbortError") return;
      setMessages((previous) => [
        ...previous,
        { role: "error", content: (error as Error).message, question: variables.question },
      ]);
    },
  });

  // === [AI 답 요청] 이번 질문 앞의 대화만 문맥으로 보냅니다 ===
  const deep = (question: string) => {
    const lastIndex = messages.map((message) => message.content).lastIndexOf(question);
    const before = lastIndex >= 0 ? messages.slice(0, lastIndex) : messages;
    const history = before
      .filter((message) => message.role === "user" || (message.role === "assistant" && message.result.status === "answered"))
      .map((message) => ({ role: message.role as "user" | "assistant", content: message.content }))
      .slice(-6);
    ask.mutate({ question, history });
  };

  // === [질문 보내기] 즉시 답(찾는 과정)과 AI 답(약 30~40초)을 동시에 시작합니다 ===
  const quick = useMutation({
    mutationFn: (question: string) => quickAnswer(productId, question),
    onSuccess: (result) => {
      setMessages((previous) => [
        ...previous,
        { role: "quick" as const, content: result.answer_text, result, createdAt: Date.now() },
      ]);
      // 미리 만든 FAQ 답(AI RAG 답)이 맞으면 같은 내용을 또 만들지 않도록 AI 답을 취소하고,
      // 찾는 과정이 다 써진 뒤 그 아래에 FAQ 답을 붙입니다.
      const faqAnswer = result.matched_faq;
      if (faqAnswer) {
        abortRef.current?.abort();
        setTimeout(
          () =>
            setMessages((previous) => [
              ...previous,
              { role: "assistant", content: faqAnswer.answer ?? "", result: faqAnswer, createdAt: Date.now() },
            ]),
          progressMs(result),
        );
      }
    },
    onError: (error, question) => {
      // 즉시 답이 실패해도 AI 답은 계속 진행합니다(진행 말풍선 없이 답만 붙음).
      console.warn("quick answer failed", question, error);
    },
  });

  const lastCitations = (): Citation[] | null => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "assistant" && message.result.status === "answered") return message.result.citations;
    }
    return null;
  };

  const send = (value: string) => {
    const question = value.trim();
    if (question.length < 2 || quick.isPending) return;
    setInput("");
    // '근거 보여줘' 같은 요청은 직전 답의 근거 리뷰를 바로 보여 줍니다(AI를 다시 부르지 않음).
    const citations = lastCitations();
    if (question.length <= 30 && EVIDENCE_REQUEST.test(question) && SHOW_REQUEST.test(question) && citations) {
      setMessages((previous) => [
        ...previous,
        { role: "user", content: question },
        { role: "evidence", content: question, citations },
      ]);
      return;
    }
    setMessages((previous) => [...previous, { role: "user", content: question }]);
    quickRef.current = quick
      .mutateAsync(question)
      .then((result) => ({ question, showUntil: Date.now() + progressMs(result) }))
      .catch(() => null);
    deep(question);
  };

  // === [자주 묻는 질문 선택] 저장된 최신 답이 있으면 즉시, 없으면 실시간으로 묻습니다 ===
  const pickFaq = (item: FaqItem) => {
    if (item.answer && !item.answer.is_stale) {
      const answer = item.answer;
      setMessages((previous) => [
        ...previous,
        { role: "user", content: item.question },
        { role: "assistant", content: answer.answer ?? "", result: answer, createdAt: Date.now() },
      ]);
      return;
    }
    send(item.question);
  };

  // === [첫 질문] 제품 이름과 함께 입력한 질문은 제품을 고르자마자 바로 보냅니다 ===
  const sentInitial = useRef(false);
  useEffect(() => {
    if (initialQuestion && !sentInitial.current) {
      sentInitial.current = true;
      send(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  const faqButtons = (faq.data?.items ?? []).filter((item) => item.key !== "summary");
  const lastMessage = messages[messages.length - 1];
  const liveInBubble = lastMessage?.role === "quick" && lastMessage.result.question === live?.question;
  // 같은 질문의 즉시 답(대체 답에 씀)
  const quickFor = (question: string, before: number) =>
    messages
      .slice(0, before)
      .reverse()
      .find((message): message is Extract<Message, { role: "quick" }> => message.role === "quick" && message.result.question === question)
      ?.result;

  return (
    <>
      {/* === [대화 내용] === */}
      <div className="chat-log">
        {intro}
        {messages.length === 0 && (
          <div className="bubble bot">
            산 제품에 문제가 있거나 사기 전에 궁금한 점을 물어보세요. 다른 구매자 리뷰를 찾아서 비슷한 사례가
            있는지, 얼마나 자주 나오는지 알려 드려요.
            <small className="bubble-meta">
              관련 리뷰를 찾는 과정을 보여 드리고, 인용과 숫자를 검증한 답만 드려요. 어떤 리뷰를 근거로 했는지
              궁금하면 "근거 보여줘"라고 물어보세요. ⚡ 표시는 미리 준비된 답이에요.
            </small>
          </div>
        )}
        {messages.map((message, index) => {
          if (message.role === "user") {
            return (
              <div key={index} className="bubble me">
                {message.content}
              </div>
            );
          }
          if (message.role === "quick") {
            const question = message.result.question;
            const later = messages.slice(index + 1);
            // 이 질문의 최종 답(또는 실패)이 나왔으면 진행 말풍선을 접습니다(다시 묻기로 나중에 붙은 답 포함).
            const finished =
              (later[0] !== undefined && later[0].role !== "user") ||
              later.some(
                (other) =>
                  (other.role === "assistant" && other.result.question === question) ||
                  (other.role === "error" && other.question === question),
              );
            return (
              <ProgressBubble
                key={index}
                result={message.result}
                createdAt={message.createdAt}
                live={live?.question === question && later.length === 0 ? live : null}
                finished={finished}
                onRetry={() => deep(message.result.question)}
              />
            );
          }
          if (message.role === "assistant") {
            return (
              <AnswerBubble
                key={index}
                result={message.result}
                createdAt={message.createdAt}
                fallback={quickFor(message.result.question, index)}
              />
            );
          }
          if (message.role === "evidence") {
            return (
              <div key={index} className="bubble bot">
                {message.citations.length > 0 ? (
                  <>
                    <small className="bubble-meta">직전 답의 근거 리뷰 {message.citations.length}건이에요. [번호]는 답 속 인용 번호예요.</small>
                    <CitationList citations={message.citations} />
                  </>
                ) : (
                  <>직전 답은 리뷰 문장을 따로 인용하지 않고 분석 통계로 답했어요.</>
                )}
              </div>
            );
          }
          const fallback = message.question ? quickFor(message.question, index) : undefined;
          return fallback ? (
            <FallbackBubble key={index} fallback={fallback} reason={message.content} />
          ) : (
            <div key={index} className="bubble bot error-bubble">
              답변을 받지 못했어요: {message.content}
            </div>
          );
        })}
        {quick.isPending && (
          <div className="bubble bot progress-bubble">
            <p className="progress-lines">
              🔍 리뷰 데이터에서 찾는 중<span className="typing-caret" />
            </p>
          </div>
        )}
        {/* 진행 말풍선이 없는 AI 답(다시 묻기, 즉시 답 실패)은 대화 끝에 진행 단계만 보여 줍니다 */}
        {live && !quick.isPending && !liveInBubble && (
          <div className="bubble bot progress-bubble">
            <ul className="progress-steps" style={{ marginTop: 0 }}>
              <li className="active">
                {live.retried
                  ? "검증에서 걸러진 답을 고쳐 쓰는 중…"
                  : live.sources.length > 0
                    ? `AI가 근거 리뷰 ${live.sources.length}건을 읽고 답을 쓰는 중…`
                    : `${live.status}…`}{" "}
                · <Elapsed />
              </li>
            </ul>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* === [자주 묻는 질문 버튼] 입력창 바로 위, 대화 중에도 언제든 누를 수 있습니다 === */}
      {faqButtons.length > 0 && (
        <div className="tags faq-row">
          {faqButtons.map((item) => (
            <button key={item.key} className="chip" onClick={() => pickFaq(item)} disabled={quick.isPending}>
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
          placeholder={ask.isPending ? "AI 답을 준비하는 중에도 새 질문을 할 수 있어요" : `예: ${TYPING_HINT}`}
          aria-label="질문"
        />
        <button className="ask" disabled={quick.isPending || input.trim().length < 2}>
          보내기
        </button>
      </form>
    </>
  );
}
