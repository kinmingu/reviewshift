// Vite 개발 서버 설정: /api와 /health 요청을 FastAPI로 전달합니다.
// 기본 대상은 127.0.0.1:8000이며, 다른 포트의 API를 쓰려면 API_TARGET 환경 변수로 바꿉니다.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
});
