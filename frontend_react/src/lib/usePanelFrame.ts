// =====================================================================
// [떠 있는 창 위치·크기] 머리 부분을 끌어 옮기고, 모서리를 끌어 크기를 바꿉니다.
// - 위치·크기는 이 브라우저에만 저장(localStorage)해 다음에 열어도 유지합니다.
// - 화면 밖으로 나가지 않게 창 크기에 맞춰 조정하고, 휴대폰 폭에서는 쓰지 않습니다(CSS 전체 폭).
// =====================================================================
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

export type Frame = { x: number; y: number; w: number; h: number };
type Mode = "move" | "resize-br" | "resize-tl";

const STORAGE_KEY = "reviewshift-chat-frame";
const MIN_W = 320;
const MIN_H = 360;
const MARGIN = 8;
export const MOBILE_MAX_WIDTH = 560;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max));

function defaultFrame(): Frame {
  const w = Math.min(420, window.innerWidth - 32);
  const h = Math.min(640, window.innerHeight - 130);
  return { x: window.innerWidth - w - 24, y: window.innerHeight - h - 92, w, h };
}

function fit(frame: Frame): Frame {
  const w = clamp(frame.w, MIN_W, window.innerWidth - MARGIN * 2);
  const h = clamp(frame.h, MIN_H, window.innerHeight - MARGIN * 2);
  return {
    w,
    h,
    x: clamp(frame.x, MARGIN, window.innerWidth - w - MARGIN),
    y: clamp(frame.y, MARGIN, window.innerHeight - h - MARGIN),
  };
}

function load(): Frame {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Frame | null;
    if (saved && [saved.x, saved.y, saved.w, saved.h].every((value) => Number.isFinite(value))) return fit(saved);
  } catch {
    // 저장소를 쓸 수 없으면 기본 위치를 씁니다.
  }
  return defaultFrame();
}

function save(frame: Frame) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(frame));
  } catch {
    // 저장 실패는 무시합니다(이번 화면에서는 그대로 유지).
  }
}

export function usePanelFrame() {
  const [frame, setFrame] = useState<Frame>(load);
  const [mobile, setMobile] = useState(() => window.innerWidth <= MOBILE_MAX_WIDTH);
  const drag = useRef<{ mode: Mode; startX: number; startY: number; start: Frame } | null>(null);

  // 브라우저 창 크기가 바뀌면 화면 안에 들어오게 맞춥니다.
  useEffect(() => {
    const onResize = () => {
      setMobile(window.innerWidth <= MOBILE_MAX_WIDTH);
      setFrame((current) => fit(current));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const begin = useCallback(
    (mode: Mode) => (event: ReactPointerEvent<HTMLElement>) => {
      // 머리 부분의 버튼(닫기 등)을 누른 경우는 옮기지 않습니다.
      if (mode === "move" && (event.target as HTMLElement).closest("button")) return;
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { mode, startX: event.clientX, startY: event.clientY, start: frame };
    },
    [frame],
  );

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const state = drag.current;
    if (!state) return;
    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    const { start } = state;
    if (state.mode === "move") {
      setFrame(fit({ ...start, x: start.x + dx, y: start.y + dy }));
    } else if (state.mode === "resize-br") {
      setFrame(fit({ ...start, w: start.w + dx, h: start.h + dy }));
    } else {
      // 왼쪽 위 모서리: 오른쪽 아래를 고정한 채 크기를 바꿉니다.
      const w = clamp(start.w - dx, MIN_W, start.x + start.w - MARGIN);
      const h = clamp(start.h - dy, MIN_H, start.y + start.h - MARGIN);
      setFrame(fit({ w, h, x: start.x + start.w - w, y: start.y + start.h - h }));
    }
  }, []);

  const end = useCallback(() => {
    if (!drag.current) return;
    drag.current = null;
    setFrame((current) => {
      save(current);
      return current;
    });
  }, []);

  const reset = useCallback(() => {
    const next = defaultFrame();
    save(next);
    setFrame(next);
  }, []);

  const handlers = (mode: Mode) => ({
    onPointerDown: begin(mode),
    onPointerMove,
    onPointerUp: end,
    onPointerCancel: end,
  });

  // 휴대폰 폭에서는 CSS(전체 폭)를 그대로 쓰고 옮기기·크기 조절을 끕니다.
  const style = mobile
    ? undefined
    : { left: frame.x, top: frame.y, width: frame.w, height: frame.h, right: "auto", bottom: "auto" };

  return { style, mobile, handlers, reset };
}
