// =====================================================================
// [표시 형식] 카테고리 한국어 이름, 비율·날짜·극성 표기
// =====================================================================

// 공식 원천 카테고리 키(DB·API) → 화면용 한국어 이름과 짧은 설명
export const CATEGORY_INFO: Record<string, { name: string; hint: string }> = {
  Electronics: { name: "전자제품", hint: "헤드폰 · 카메라 · 스피커 · 전자책 · 키보드" },
  Beauty_and_Personal_Care: { name: "뷰티", hint: "면도기 · 드라이어 · 고데기 · 스킨 · 향수" },
  Cell_Phones_and_Accessories: { name: "휴대폰 액세서리", hint: "충전기 · 케이스 · 헤드셋 · 셀카봉" },
  Home_and_Kitchen: { name: "주방·생활", hint: "청소기 · 주전자 · 밥솥 · 침구" },
  Sports_and_Outdoors: { name: "스포츠", hint: "자전거 용품 · 랜턴 · 운동 기구" },
  Toys_and_Games: { name: "장난감", hint: "유아 놀이 · 드론 · 카드 게임 · 퍼즐" },
  Health_and_Household: { name: "건강·생활용품", hint: "화장지 · 세제 · 구강용품 · 보충제" },
};

export const categoryName = (key: string) => CATEGORY_INFO[key]?.name ?? key;

export const POLARITY_LABEL: Record<string, string> = {
  positive: "좋아요",
  negative: "아쉬워요",
  neutral: "중립",
  uncertain: "판단 보류",
};

export const percent = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? "–" : `${(value * 100).toFixed(digits)}%`;

export const monthLabel = (month: string) => {
  const [year, value] = month.split("-");
  return `${year}년 ${Number(value)}월`;
};

export const dateLabel = (iso: string) => {
  const date = new Date(iso);
  return `${date.getUTCFullYear()}.${String(date.getUTCMonth() + 1).padStart(2, "0")}.${String(
    date.getUTCDate(),
  ).padStart(2, "0")}`;
};

export const labelName = (item: { detail_name_ko: string | null; detail_label: string }) =>
  item.detail_name_ko ?? item.detail_label;
