// =====================================================================
// [앱 레이아웃] 상단 헤더(로고·검색) + 페이지 라우팅
//   /                 카테고리 → 상품 목록
//   /products/:id     상품 상세(리뷰 리포트)
//   모든 화면 오른쪽 아래: 리뷰 챗봇(제품 이름·ID로 제품을 고른 뒤 질문)
// =====================================================================
import { useState, type FormEvent } from "react";
import { Link, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";

import ChatWidget from "./components/ChatWidget";
import CatalogPage from "./pages/CatalogPage";
import ProductPage from "./pages/ProductPage";

// === [헤더] 검색어는 주소(?q=)에 담아 뒤로 가기·공유가 되게 합니다 ===
function Header() {
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const navigate = useNavigate();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    navigate(query.trim() ? `/?q=${encodeURIComponent(query.trim())}` : "/");
  };

  return (
    <header className="header">
      <div className="header-inner">
        <Link to="/" className="logo" onClick={() => setQuery("")}>
          <span className="logo-mark" aria-hidden>
            <span />
            <span />
            <span />
          </span>
          ReviewShift
        </Link>
        <form className="search" onSubmit={submit} role="search">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="상품명으로 리뷰 리포트 찾기"
            aria-label="상품 검색"
          />
        </form>
        <span className="header-note">Amazon Reviews 2023 실제 리뷰 · 판매 사이트 아님</span>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<CatalogPage />} />
        <Route path="/products/:productId" element={<ProductPage />} />
      </Routes>
      <ChatWidget />
    </>
  );
}
