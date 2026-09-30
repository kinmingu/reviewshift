// =====================================================================
// [떠 있는 리뷰 챗봇] 모든 화면 오른쪽 아래 버튼 → 대화 창
// 1. 제품 이름(한글·영문 일부)이나 제품 ID(ASIN)를 입력하면 제품을 찾습니다.
//    - 한 제품으로 좁혀지면 바로 고르고, 비슷한 제품이 여럿이면 후보를 보여 줍니다.
//    - "알로 카메라 배터리 오래가?"처럼 질문을 함께 쓰면 제품을 고른 뒤 그 질문을 바로 보냅니다.
// 2. 제품을 고른 뒤에는 ProductChat(즉시 답 → AI에게 자세히 묻기)으로 대화합니다.
// 제품 찾기는 화면에서 상품 목록(56개) 이름을 비교할 뿐, 수치·답변은 모두 서버 결과입니다.
// =====================================================================
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { api, type ProductSummary } from "../api";
import { categoryName } from "../lib/format";
import { usePanelFrame } from "../lib/usePanelFrame";
import ProductChat, { clearChat } from "./AskPanel";

type PickerMessage =
  | { role: "user"; content: string }
  | { role: "bot"; content: string; candidates?: ProductSummary[] };

const SELECTED_KEY = "reviewshift-chat-product";
// 제품 이름이 아닌 흔한 말(질문에 남아도 질문으로 보지 않음)
const FILLER = new Set(["제품", "상품", "이거", "그거", "이제품", "관련", "대해", "대해서"]);
const PARTICLES = /(은|는|이|가|을|를|의|도|에|로|으로|에서|이랑|랑|하고)$/;

const normalize = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^0-9a-z가-힣]+/g, " ")
    .trim();

const productName = (product: ProductSummary) => product.title_ko ?? product.title;

function readSelected(): string | null {
  try {
    return sessionStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

function writeSelected(id: string | null) {
  try {
    if (id) sessionStorage.setItem(SELECTED_KEY, id);
    else sessionStorage.removeItem(SELECTED_KEY);
  } catch {
    // 저장소를 쓸 수 없어도 이번 화면에서는 선택이 유지됩니다.
  }
}

// === [제품 찾기] ASIN 일치 → 이름 단어 일치 점수. 남은 단어가 있으면 질문으로 봅니다 ===
function findProducts(message: string, products: ProductSummary[]) {
  const asin = message.match(/(?:amazon-)?\b([a-z0-9]{10})\b/i)?.[1]?.toUpperCase();
  if (asin) {
    const exact = products.find((product) => product.id.toUpperCase() === `AMAZON-${asin}`);
    if (exact) {
      const rest = normalize(message.replace(/(?:amazon-)?[a-z0-9]{10}/i, ""));
      return { matches: [exact], leftover: rest.split(" ").filter((word) => word.length >= 2 && !FILLER.has(word)) };
    }
  }
  const words = normalize(message)
    .split(" ")
    .filter((word) => word.length >= 2);
  const scored = products
    .map((product) => {
      const haystack = normalize(`${product.title_ko ?? ""} ${product.title}`);
      const matched = new Set<string>();
      let score = 0;
      for (const word of words) {
        const stem = word.replace(PARTICLES, "");
        const hit = haystack.includes(word) ? word : stem.length >= 2 && haystack.includes(stem) ? stem : null;
        if (hit) {
          matched.add(word);
          score += hit.length;
        }
      }
      return { product, score, matched };
    })
    .filter((item) => item.score >= 2)
    .sort((a, b) => b.score - a.score);
  if (scored.length === 0) return { matches: [], leftover: [] };
  const top = scored[0];
  const tied = scored.filter((item) => item.score === top.score);
  const leftover = words.filter((word) => !top.matched.has(word) && !FILLER.has(word));
  return { matches: (tied.length > 1 ? tied : [top]).slice(0, 5).map((item) => item.product), leftover };
}

function ProductCardMini({ product }: { product: ProductSummary }) {
  return (
    <span className="chat-product">
      {product.image_url ? <img src={product.image_url} alt="" /> : <span className="chat-product-img" />}
      <span>
        <b>{productName(product)}</b>
        <small>
          {categoryName(product.category)} · 리뷰 {product.review_count}건 · AI 분석 {product.analyzed_review_count}건
        </small>
      </span>
    </span>
  );
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(readSelected);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [pickerInput, setPickerInput] = useState("");
  const [pickerLog, setPickerLog] = useState<PickerMessage[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const frame = usePanelFrame();

  const products = useQuery({ queryKey: ["products", "chat-all"], queryFn: () => api.products({}), enabled: open });
  const items = products.data?.items ?? [];
  const selected = items.find((product) => product.id === selectedId) ?? null;
  const viewingId = location.pathname.match(/^\/products\/([^/]+)/)?.[1] ?? null;
  const viewing = items.find((product) => product.id === viewingId) ?? null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [pickerLog]);

  const choose = (product: ProductSummary, question: string | null = null) => {
    writeSelected(product.id);
    setSelectedId(product.id);
    setPendingQuestion(question);
    setPickerLog([]);
    setChatKey((value) => value + 1);
  };

  const changeProduct = () => {
    writeSelected(null);
    setSelectedId(null);
    setPendingQuestion(null);
  };

  const newChat = () => {
    if (selectedId) clearChat(selectedId);
    setPendingQuestion(null);
    setChatKey((value) => value + 1);
  };

  // === [제품 찾기 입력] ===
  const submitPicker = () => {
    const message = pickerInput.trim();
    if (message.length < 2 || items.length === 0) return;
    setPickerInput("");
    const { matches, leftover } = findProducts(message, items);
    if (matches.length === 1) {
      choose(matches[0], leftover.length > 0 ? message : null);
      return;
    }
    setPickerLog((previous) => [
      ...previous,
      { role: "user", content: message },
      matches.length === 0
        ? {
            role: "bot",
            content:
              "그 이름의 제품을 찾지 못했어요. 제품 이름 일부(예: 알로 카메라, 킨들)나 제품 ID(예: B09M8N7YML)로 다시 입력해 주세요.",
          }
        : { role: "bot", content: "비슷한 제품이 여러 개 있어요. 어떤 제품인가요?", candidates: matches },
    ]);
  };

  return (
    <>
      {open && (
        <div className="chat-panel" role="dialog" aria-label="AI 리뷰 챗봇" style={frame.style}>
          {/* === [크기 조절 손잡이] 왼쪽 위·오른쪽 아래 모서리를 끌어 크기를 바꿉니다 === */}
          {!frame.mobile && (
            <>
              <span className="chat-resize tl" title="끌어서 크기 조절" {...frame.handlers("resize-tl")} />
              <span className="chat-resize br" title="끌어서 크기 조절" {...frame.handlers("resize-br")} />
            </>
          )}
          {/* === [헤더] 끌어서 창 옮기기(두 번 클릭하면 원래 자리) · 제품 바꾸기 · 새 대화 · 닫기 === */}
          <div
            className={`chat-panel-head ${frame.mobile ? "" : "movable"}`}
            {...(frame.mobile ? {} : frame.handlers("move"))}
            onDoubleClick={frame.mobile ? undefined : frame.reset}
            title={frame.mobile ? undefined : "끌어서 옮기기 · 두 번 클릭하면 원래 위치와 크기로"}
          >
            <div style={{ minWidth: 0 }}>
              <b>AI 리뷰 챗봇</b>
              <small className="bubble-meta" style={{ cursor: "default" }}>
                {selected ? productName(selected) : "제품을 먼저 알려 주세요"} · 실제 리뷰 근거로만 답해요
              </small>
            </div>
            <div className="chat-panel-actions">
              {selected && (
                <>
                  <button className="link-btn" onClick={changeProduct}>
                    제품 바꾸기
                  </button>
                  <button className="link-btn" onClick={newChat}>
                    새 대화
                  </button>
                </>
              )}
              <button className="link-btn" onClick={() => setOpen(false)} aria-label="챗봇 닫기">
                닫기
              </button>
            </div>
          </div>

          {selectedId && !selected && products.isLoading && (
            <div className="chat-log">
              <div className="bubble bot">제품 정보를 불러오는 중이에요…</div>
            </div>
          )}

          {selected ? (
            <ProductChat
              key={`${selected.id}-${chatKey}`}
              productId={selected.id}
              initialQuestion={pendingQuestion}
              intro={
                <div className="bubble bot">
                  이 제품의 리뷰로 답해 드릴게요.
                  <ProductCardMini product={selected} />
                </div>
              }
            />
          ) : (
            !(selectedId && products.isLoading) && (
              <>
                {/* === [제품 고르기] === */}
                <div className="chat-log">
                  <div className="bubble bot">
                    안녕하세요! 어떤 제품이 궁금하세요?
                    <br />
                    <b>제품 이름</b>이나 <b>제품 ID</b>를 입력해 주세요. 질문을 같이 써도 돼요.
                    <small className="bubble-meta" style={{ cursor: "default" }}>
                      예: "킨들", "B09M8N7YML", "알로 카메라 배터리 오래가요?"
                    </small>
                  </div>
                  {viewing && (
                    <div className="bubble bot">
                      지금 보고 있는 제품에 대해 물어볼까요?
                      <button className="chat-candidate" onClick={() => choose(viewing)}>
                        <ProductCardMini product={viewing} />
                      </button>
                    </div>
                  )}
                  {products.isError && (
                    <div className="bubble bot error-bubble">상품 목록을 불러오지 못했어요. API 서버를 확인해 주세요.</div>
                  )}
                  {pickerLog.map((message, index) =>
                    message.role === "user" ? (
                      <div key={index} className="bubble me">
                        {message.content}
                      </div>
                    ) : (
                      <div key={index} className="bubble bot">
                        {message.content}
                        {message.candidates?.map((product) => (
                          <button key={product.id} className="chat-candidate" onClick={() => choose(product)}>
                            <ProductCardMini product={product} />
                          </button>
                        ))}
                      </div>
                    ),
                  )}
                  <div ref={bottomRef} />
                </div>
                <form
                  className="ask-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitPicker();
                  }}
                >
                  <input
                    value={pickerInput}
                    maxLength={300}
                    onChange={(event) => setPickerInput(event.target.value)}
                    placeholder="제품 이름 또는 제품 ID"
                    aria-label="제품 이름 또는 제품 ID"
                    autoFocus
                  />
                  <button className="ask" disabled={pickerInput.trim().length < 2 || items.length === 0}>
                    찾기
                  </button>
                </form>
              </>
            )
          )}
        </div>
      )}

      {/* === [떠 있는 버튼] === */}
      <button
        className={`chat-fab ${open ? "open" : ""}`}
        onClick={() => setOpen(!open)}
        aria-label={open ? "챗봇 닫기" : "AI 리뷰 챗봇 열기"}
      >
        {open ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        ) : (
          <>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4A1.5 1.5 0 0 1 4 14.5z" />
              <path d="M12 6.5l.9 2 2 .9-2 .9-.9 2-.9-2-2-.9 2-.9z" fill="currentColor" stroke="none" />
            </svg>
            <span>AI 리뷰 챗봇</span>
          </>
        )}
      </button>
    </>
  );
}
