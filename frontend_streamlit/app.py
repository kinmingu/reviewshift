from typing import Any

import pandas as pd
import streamlit as st

from frontend_streamlit.api_client import ApiError, ReviewShiftClient

st.set_page_config(page_title="ReviewShift", page_icon="📊", layout="wide")


@st.cache_resource
def get_client() -> ReviewShiftClient:
    return ReviewShiftClient()


client = get_client()


def source_notice(source_mode: str) -> None:
    if source_mode == "fixture":
        st.warning(
            "합성 테스트 데이터입니다. 실제 Amazon 리뷰나 실제 AI 분석 결과가 아닙니다.",
            icon="⚠️",
        )
    else:
        st.info(
            "McAuley-Lab Amazon Reviews 2023의 실제 공개 배포 데이터입니다. "
            "아직 LLM 분류를 실행하지 않았습니다.",
            icon="ℹ️",
        )


def render_review(review: dict[str, Any]) -> None:
    st.markdown(f"**{review.get('title') or '제목 없음'}** · ⭐ {review['rating']}")
    st.caption(f"{review['reviewed_at'][:10]} · 리뷰 ID: {review['id']}")
    st.write(review["text"])
    if not review["labels"]:
        st.caption("항목 분류: 분석 전")
    for label in review["labels"]:
        st.caption(
            f"{label['aspect']} / {label['detail_label']} / {label['polarity']} · "
            f"근거: “{label['evidence_span']}”"
        )


def render_catalog() -> None:
    st.title("ReviewShift")
    st.caption("상품 리뷰의 월별 변화를 원문 근거와 함께 비교합니다.")
    source_label = st.radio(
        "데이터 출처",
        ["실제 Amazon 데이터", "합성 테스트 데이터"],
        horizontal=True,
    )
    source_mode = "real" if source_label.startswith("실제") else "fixture"
    categories_response = client.categories(source_mode)
    source_notice(categories_response["source_mode"])

    search_col, category_col = st.columns([2, 1])
    with search_col:
        query = st.text_input("상품 검색", placeholder="상품명 또는 parent_asin")
    with category_col:
        selected_category = st.selectbox(
            "카테고리", ["전체", *categories_response["items"]]
        )

    response = client.products(
        query=query,
        category="" if selected_category == "전체" else selected_category,
        source_mode=source_mode,
    )
    st.caption(f"검색 결과 {response['total']}개")
    if not response["items"]:
        st.info("조건에 맞는 상품이 없습니다. 실제 데이터를 먼저 적재했는지 확인해 주세요.")
        return

    columns = st.columns(3)
    for index, product in enumerate(response["items"]):
        with columns[index % 3]:
            with st.container(border=True):
                if product.get("image_url"):
                    st.image(product["image_url"], width=180)
                else:
                    st.caption("상품 이미지 없음")
                st.subheader(product["title"])
                st.caption(product["category"])
                st.metric("저장된 리뷰", product["review_count"])
                months = product["available_months"]
                st.caption(
                    f"분석 가능 기간: {months[0]} ~ {months[-1]}"
                    if months
                    else "분석 가능 기간 없음"
                )
                if st.button(
                    "상세 보기", key=f"open-{product['id']}", width="stretch"
                ):
                    st.session_state.selected_product_id = product["id"]
                    st.rerun()


def _render_raw_month(product_id: str, month: str) -> None:
    response = client.reviews(product_id, month)
    st.caption(f"{month}: 원문 리뷰 {response['total']}건 (최대 100건 표시)")
    for review in response["items"]:
        with st.container(border=True):
            render_review(review)


def _render_real_comparison(product: dict[str, Any]) -> None:
    months = product["available_months"]
    if len(months) < 2:
        st.info("비교할 수 있는 완료 월이 두 개 이상 필요합니다.")
        return

    metadata = product["metadata"]
    default_baseline = metadata.get("baseline_month")
    default_target = metadata.get("target_month")
    baseline_index = months.index(default_baseline) if default_baseline in months else len(months) - 2
    target_index = months.index(default_target) if default_target in months else len(months) - 1
    baseline_col, target_col = st.columns(2)
    with baseline_col:
        baseline_month = st.selectbox("비교 월", months, index=baseline_index)
    with target_col:
        target_month = st.selectbox("분석 월", months, index=target_index)

    stats = {item["month"]: item for item in product["monthly_stats"]}
    baseline = stats[baseline_month]
    target = stats[target_month]
    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            f"{baseline_month} 리뷰 / 평균 별점",
            f"{baseline['review_count']}건 / {baseline['average_rating']:.2f}",
        )
    with col2:
        st.metric(
            f"{target_month} 리뷰 / 평균 별점",
            f"{target['review_count']}건 / {target['average_rating']:.2f}",
        )
    st.warning("항목별 불만률: 분석 전 (LLM 분류를 아직 실행하지 않음)")

    old_tab, new_tab = st.tabs([f"비교 월 {baseline_month}", f"분석 월 {target_month}"])
    with old_tab:
        _render_raw_month(product["id"], baseline_month)
    with new_tab:
        _render_raw_month(product["id"], target_month)


def _render_fixture_comparison(product: dict[str, Any]) -> None:
    months = product["available_months"]
    if len(months) < 2:
        st.info("비교할 수 있는 완료 월이 두 개 이상 필요합니다.")
        return

    baseline_col, target_col = st.columns(2)
    with baseline_col:
        baseline_month = st.selectbox("비교 월", months, index=len(months) - 2)
    with target_col:
        target_month = st.selectbox("분석 월", months, index=len(months) - 1)

    comparison = client.comparison(product["id"], target_month, baseline_month)
    coverage = comparison["coverage"]
    st.caption(
        f"분류 처리율 · 비교 월 {coverage['baseline_labeled']}/{coverage['baseline_total']}, "
        f"분석 월 {coverage['target_labeled']}/{coverage['target_total']}"
    )
    if comparison["status"] != "ok":
        st.info("원자료가 없거나 분류가 완료되지 않아 항목 비교를 표시하지 않습니다.")
        return

    st.subheader("주요 변화")
    issues = comparison["issues"]
    display_rows = [
        {
            "항목": item["aspect"],
            "세부 내용": item["detail_label"],
            "평가": item["polarity"],
            f"{baseline_month} 건수": item["baseline_count"],
            f"{baseline_month} 비율": f"{item['baseline_rate']:.1%}",
            f"{target_month} 건수": item["target_count"],
            f"{target_month} 비율": f"{item['target_rate']:.1%}",
            "변화(%p)": round(item["change_pp"], 1),
        }
        for item in issues
    ]
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")

    st.subheader("근거 리뷰")
    issue_labels = [
        f"{item['aspect']} · {item['detail_label']} · {item['polarity']}"
        for item in issues
    ]
    selected_label = st.selectbox("확인할 변화", issue_labels)
    selected_issue = issues[issue_labels.index(selected_label)]
    evidence_ids = set(selected_issue["evidence_review_ids"])
    old_tab, new_tab = st.tabs([f"비교 월 {baseline_month}", f"분석 월 {target_month}"])
    for tab, month in ((old_tab, baseline_month), (new_tab, target_month)):
        with tab:
            review_response = client.reviews(
                product["id"], month, selected_issue["aspect"], selected_issue["polarity"]
            )
            matching = [
                review for review in review_response["items"] if review["id"] in evidence_ids
            ]
            if not matching:
                st.info("이 기간에는 해당 근거 리뷰가 없습니다.")
            for review in matching:
                with st.container(border=True):
                    render_review(review)


def render_detail(product_id: str) -> None:
    if st.button("← 상품 목록"):
        st.session_state.selected_product_id = None
        st.rerun()

    product = client.product(product_id)
    source_notice(product["source_mode"])
    st.title(product["title"])
    st.caption(f"{product['category']} · parent_asin: {product['parent_asin']}")
    if product.get("image_url"):
        st.image(product["image_url"], width=260)
    else:
        st.caption("상품 이미지 없음")
    description = product["metadata"].get("description")
    st.write(description or "상품 설명이 원천 메타데이터에 없습니다.")
    st.metric("저장된 리뷰", product["review_count"])

    st.subheader("월별 리뷰 현황")
    rows = [
        {
            "월": item["month"],
            "리뷰 수": item["review_count"],
            "평균 별점": round(item["average_rating"], 2),
        }
        for item in product["monthly_stats"]
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    if product["source_mode"] == "real":
        _render_real_comparison(product)
    else:
        _render_fixture_comparison(product)

    st.subheader("AI 질문")
    st.info("AI 질문은 아직 구현하지 않았습니다. RAG·Agent 단계에서 실제 근거 연결 후 제공합니다.")
    st.text_input("질문", disabled=True, placeholder="현재 단계에서는 사용할 수 없습니다.")
    st.button("질문 보내기", disabled=True)


def main() -> None:
    try:
        health = client.health()
        if health["database"] != "connected":
            st.error("데이터베이스 연결이 준비되지 않았습니다.")
            return
        selected_product_id = st.session_state.get("selected_product_id")
        if selected_product_id:
            render_detail(selected_product_id)
        else:
            render_catalog()
    except ApiError as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
