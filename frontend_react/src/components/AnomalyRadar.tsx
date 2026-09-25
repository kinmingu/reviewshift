// =====================================================================
// [이상징후 레이더] 모든 상품의 인접 두 달을 같은 규칙으로 통계 검정한 결과
// - 이상징후: 보정 후에도 유의(q<0.10)하고 10%p 이상 늘어난 아쉬운 점
// - 주의 관찰: 보정 전에는 유의(p<0.05)하지만 확정하기엔 이른 증가
// 기간을 결과를 보고 고르지 않으며, 표본이 적은 달은 판정하지 않습니다.
// =====================================================================
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchAnomalies } from "../api";
import { categoryName, labelName, monthLabel, percent } from "../lib/format";

export default function AnomalyRadar() {
  const report = useQuery({ queryKey: ["anomalies"], queryFn: fetchAnomalies, staleTime: 120_000 });
  if (report.isError) return null;
  const data = report.data;
  const anomalies = data?.items.filter((item) => item.level === "anomaly") ?? [];
  const watches = data?.items.filter((item) => item.level === "watch") ?? [];

  return (
    <section className="panel radar">
      <div className="panel-head">
        <div>
          <h2>이상징후 레이더</h2>
          <p className="sub">
            모든 상품의 인접한 두 달을 같은 규칙으로 비교해, 우연으로 보기 어려운 불만 증가만 보여 줘요.
            {data &&
              ` · 판정 가능 ${data.products_evaluable}/${data.products_total}개 상품 · 검정 ${data.tests}건`}
          </p>
        </div>
        {data && (
          <div className="tags" style={{ marginTop: 0 }}>
            <span className="badge warn">이상징후 {anomalies.length}</span>
            <span className="badge idle">주의 관찰 {watches.length}</span>
          </div>
        )}
      </div>

      {report.isLoading && <p className="empty">35개 상품을 검정하는 중…</p>}
      {data && data.items.length === 0 && (
        <p className="empty">
          지금은 통계적으로 확인된 불만 증가가 없어요.
          {data.products_evaluable < data.products_total &&
            ` AI 분석이 진행 중이라 아직 ${data.products_total - data.products_evaluable}개 상품은 판정할 표본이 부족해요.`}
        </p>
      )}

      <div className="radar-list">
        {data?.items.slice(0, 8).map((item) => (
          <Link
            key={`${item.product_id}-${item.target_month}-${item.detail_label}`}
            to={`/products/${item.product_id}`}
            className={`radar-item ${item.level}`}
          >
            {item.image_url && <img src={item.image_url} alt="" loading="lazy" />}
            <div>
              <span className={`badge ${item.level === "anomaly" ? "warn" : "idle"}`}>
                {item.level === "anomaly" ? "이상징후" : "주의 관찰"}
                {item.is_provisional && " · 잠정"}
              </span>
              <b>{item.product_name_ko ?? item.product_id}</b>
              <span className="radar-meta">
                {categoryName(item.category)} · {monthLabel(item.baseline_month)} → {monthLabel(item.target_month)}
              </span>
              <span>
                <b style={{ color: "var(--negative)" }}>{labelName(item)}</b> 아쉬워요{" "}
                {percent(item.baseline_rate)} → {percent(item.target_rate)} (+{item.change_pp?.toFixed(1)}%p,{" "}
                {item.baseline_count}/{item.baseline_total} → {item.target_count}/{item.target_total}건)
              </span>
              <span className="radar-meta">
                p={item.p_value.toFixed(3)} · 보정 q={item.q_value.toFixed(3)}
              </span>
            </div>
          </Link>
        ))}
      </div>
      {data && (
        <details className="original" style={{ marginTop: 10 }}>
          <summary>판정 방법 보기</summary>
          {data.method}
        </details>
      )}
    </section>
  );
}
