// Vite 개발 서버 설정: /api와 /health 요청을 FastAPI로 전달합니다.
// 기본 대상은 127.0.0.1:8000이며, 다른 포트의 API를 쓰려면 API_TARGET 환경 변수로 바꿉니다.
// Vite는 IP 주소로 들어오는 접속을 기본 허용합니다(호스트 이름 접속은 allowedHosts 필요).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // 기본은 이 PC 전용. 같은 와이파이에 공개하려면 WEB_HOST=0.0.0.0 (API·Ollama는 계속 PC 전용)
    host: process.env.WEB_HOST ?? "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
});
