// =====================================================================
// [좋아요/아쉬워요 막대] 분석 성공 리뷰 중 긍정·부정 라벨이 있는 리뷰 비율
// 한 리뷰에 좋은 점과 아쉬운 점이 함께 있을 수 있어 두 값의 합은 100%가 아닐 수 있습니다.
// =====================================================================
import { percent } from "../lib/format";

interface Props {
  positive: number | null;
  negative: number | null;
  analyzed: number;
}

export default function SentimentBar({ positive, negative, analyzed }: Props) {
  if (!analyzed || positive === null || negative === null) {
    return <p className="sentiment-empty">리뷰 분석 전 · 별점과 원문만 볼 수 있어요</p>;
  }
  return (
    <div className="sentiment" title={`분석된 리뷰 ${analyzed}건 기준`}>
      <div className="sentiment-bar" aria-hidden>
        <span className="pos" style={{ width: `${positive * 100}%` }} />
        <span className="neg" style={{ width: `${negative * 100}%` }} />
      </div>
      <div className="sentiment-legend">
        <span className="pos">👍 좋아요 {percent(positive)}</span>
        <span className="neg">아쉬워요 {percent(negative)} 👎</span>
      </div>
    </div>
  );
}
