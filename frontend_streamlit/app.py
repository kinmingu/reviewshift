from typing import Any

import pandas as pd
import streamlit as st

from frontend_streamlit.api_client import ApiError, ReviewShiftClient

st.set_page_config(page_title="ReviewShift", page_icon="📊", layout="wide")


@st.cache_resource
def get_client() -> ReviewShiftClient:
    return ReviewShiftClient()


client = get_client()
EVALUATION_DATASET_ID = "human-eval-140-v1"

# DB와 API에는 공식 원천 카테고리 키를 그대로 두고, 화면에서만 한국어 이름을 덧붙입니다.
# 이렇게 하면 번역 문구가 바뀌어도 데이터 필터와 재적재 키가 달라지지 않습니다.
CATEGORY_NAMES_KO = {
    "Electronics": "전자제품",
    "Beauty_and_Personal_Care": "뷰티·개인관리",
    "Cell_Phones_and_Accessories": "휴대폰·액세서리",
    "Home_and_Kitchen": "주방·생활용품",
    "Sports_and_Outdoors": "스포츠·아웃도어",
    "Toys_and_Games": "장난감·게임",
    "Health_and_Household": "건강·가정용품",
    "Appliances": "가전제품(기존 수집분)",
}


def category_label(category: str) -> str:
    korean = CATEGORY_NAMES_KO.get(category)
    return f"{korean} ({category})" if korean else category


def source_notice(source_mode: str) -> None:
    if source_mode == "fixture":
        st.warning(
            "합성 테스트 데이터입니다. 실제 Amazon 리뷰나 실제 AI 분석 결과가 아닙니다.",
            icon="⚠️",
        )
    else:
        st.info(
            "McAuley-Lab Amazon Reviews 2023의 실제 공개 배포 데이터입니다. "
            "항목별 LLM 분석은 처리 상태와 버전을 구분해 표시합니다.",
            icon="ℹ️",
        )


def render_review(review: dict[str, Any]) -> None:
    has_translation = bool(review.get("text_ko"))
    display_title = (
        review.get("title_ko") if has_translation else review.get("title")
    ) or "제목 없음"
    st.markdown(f"**{display_title}** · ⭐ {review['rating']}")
    st.caption(f"{review['reviewed_at'][:10]} · 리뷰 ID: {review['id']}")
    if has_translation:
        st.caption(
            f"자동 번역 · {review.get('translation_model') or '모델 정보 없음'} · "
            "정확한 인용은 영어 원문 기준"
        )
        st.write(review["text_ko"])
        with st.expander("영어 원문 보기"):
            st.markdown(f"**{review.get('title') or '제목 없음'}**")
            st.write(review["text"])
    else:
        if review["source_mode"] == "real":
            st.caption("자동 번역 대기 중 · 아래 내용은 리뷰 영어 원문")
        st.write(review["text"])
    analysis_status = review.get("analysis_status", "not_started")
    if not review["labels"]:
        status_text = {
            "not_started": "항목 분류: 분석 전",
            "pending": "항목 분류: 대기 중",
            "running": "항목 분류: 진행 중",
            "succeeded": "항목 분류 완료: 명시적으로 분류할 항목 없음",
            "failed": "항목 분류: 모델 처리 실패",
        }.get(analysis_status, "항목 분류 상태 확인 필요")
        st.caption(status_text)
    polarity_names = {
        "positive": "긍정",
        "negative": "부정",
        "neutral": "중립",
        "uncertain": "판단 불가",
    }
    for label in review["labels"]:
        st.caption(
            f"{label.get('aspect_name_ko') or label['aspect']} / "
            f"{label.get('detail_name_ko') or label['detail_label']} / "
            f"{polarity_names.get(label['polarity'], label['polarity'])} · "
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
            "카테고리",
            ["전체", *categories_response["items"]],
            format_func=lambda value: (
                "전체" if value == "전체" else category_label(value)
            ),
        )

    response = client.products(
        query=query,
        category="" if selected_category == "전체" else selected_category,
        source_mode=source_mode,
    )
    st.caption(f"검색 결과 {response['total']}개")
    if not response["items"]:
        if source_mode == "real" and selected_category != "전체":
            st.info(
                f"{category_label(selected_category)} 카테고리는 아직 데이터 준비 중입니다. "
                "다른 카테고리의 상품을 대신 표시하지 않습니다."
            )
        else:
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
                if product.get("title_ko"):
                    st.subheader(product["title_ko"])
                    with st.expander("원문 상품명 보기"):
                        st.caption(product["title"])
                else:
                    st.subheader(product["title"])
                st.caption(category_label(product["category"]))
                st.metric("제품별 저장 리뷰 수", f"{product['review_count']:,}건")
                if product.get("source_average_rating") is not None:
                    st.metric(
                        "원천 전체 평균 평점",
                        f"⭐ {product['source_average_rating']:.1f} / 5",
                    )
                if product.get("source_rating_count") is not None:
                    st.caption(
                        f"원천 평점 등록 수: {product['source_rating_count']:,}건 "
                        "(구매 수가 아님)"
                    )
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

    comparison = client.comparison(product["id"], target_month, baseline_month)
    coverage = comparison["coverage"]
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
    state_names = {
        "not_started": "분석 전",
        "in_progress": "진행 중",
        "complete": "완료",
        "partial_failure": "일부 실패",
    }
    state = comparison["analysis_status"]
    state_text = state_names[state]
    version_text = (
        f"분석 버전 {comparison['analysis_version']} · 모델 {comparison.get('model')}"
        if comparison["analysis_version"] != "not-analyzed"
        else "활성 분석 버전 없음"
    )
    if state == "complete":
        st.success(f"항목별 분석 상태: {state_text} · {version_text}")
    elif state == "partial_failure":
        st.warning(f"항목별 분석 상태: {state_text} · {version_text}")
    elif state == "in_progress":
        st.info(f"항목별 분석 상태: {state_text} · {version_text}")
    else:
        st.warning(f"항목별 분석 상태: {state_text} · {version_text}")

    coverage_rows = [
        {
            "기간": f"비교 월 {baseline_month}",
            "대상": coverage["baseline_total"],
            "성공": coverage["baseline_succeeded"],
            "실패": coverage["baseline_failed"],
            "진행 중": coverage["baseline_in_progress"],
            "미처리": coverage["baseline_unprocessed"],
            "처리율": (
                f"{coverage['baseline_processing_rate']:.1%}"
                if coverage["baseline_processing_rate"] is not None
                else "데이터 없음"
            ),
        },
        {
            "기간": f"분석 월 {target_month}",
            "대상": coverage["target_total"],
            "성공": coverage["target_succeeded"],
            "실패": coverage["target_failed"],
            "진행 중": coverage["target_in_progress"],
            "미처리": coverage["target_unprocessed"],
            "처리율": (
                f"{coverage['target_processing_rate']:.1%}"
                if coverage["target_processing_rate"] is not None
                else "데이터 없음"
            ),
        },
    ]
    st.dataframe(pd.DataFrame(coverage_rows), hide_index=True, width="stretch")

    if comparison["is_provisional"]:
        st.warning(
            "아래 비율은 분류에 성공한 리뷰만 분모로 사용한 잠정 결과입니다. "
            "미처리·실패 리뷰를 불만 없는 리뷰로 계산하지 않습니다."
        )
    elif comparison["signal_status"] == "increase_signal":
        st.warning(
            "설정된 최소 건수·불만 건수·증가 폭 기준을 충족한 증가 신호가 있습니다. "
            "통계적 유의성을 의미하지 않습니다."
        )
    elif comparison["signal_status"] == "no_increase_signal":
        st.success("설정 기준을 충족하는 증가 신호 없음")

    issues = comparison["issues"]
    if issues:
        st.subheader("항목별 변화" + (" (잠정)" if comparison["is_provisional"] else ""))
        polarity_names = {
            "positive": "긍정",
            "negative": "부정",
            "neutral": "중립",
            "uncertain": "판단 불가",
        }
        display_rows = [
            {
                "상위 항목": item.get("aspect_name_ko") or item["aspect"],
                "세부 항목": item.get("detail_name_ko") or item["detail_label"],
                "감성": polarity_names.get(item["polarity"], item["polarity"]),
                f"{baseline_month} 건수": item["baseline_count"],
                f"{baseline_month} 비율": (
                    f"{item['baseline_rate']:.1%}"
                    if item["baseline_rate"] is not None
                    else "분모 없음"
                ),
                f"{target_month} 건수": item["target_count"],
                f"{target_month} 비율": (
                    f"{item['target_rate']:.1%}"
                    if item["target_rate"] is not None
                    else "분모 없음"
                ),
                "변화(%p)": (
                    round(item["change_pp"], 1)
                    if item["change_pp"] is not None
                    else "계산 불가"
                ),
            }
            for item in issues
        ]
        st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")

        st.subheader("분류 근거 원문 리뷰")
        issue_labels = [
            f"{item.get('detail_name_ko') or item['detail_label']} · "
            f"{polarity_names.get(item['polarity'], item['polarity'])}"
            for item in issues
        ]
        selected_label = st.selectbox("확인할 항목 변화", issue_labels)
        selected_issue = issues[issue_labels.index(selected_label)]
        evidence_ids = set(selected_issue["evidence_review_ids"])
        old_tab, new_tab = st.tabs(
            [f"비교 월 {baseline_month}", f"분석 월 {target_month}"]
        )
        for tab, month in ((old_tab, baseline_month), (new_tab, target_month)):
            with tab:
                review_response = client.reviews(
                    product["id"],
                    month,
                    selected_issue["aspect"],
                    selected_issue["polarity"],
                )
                matching = [
                    review
                    for review in review_response["items"]
                    if review["id"] in evidence_ids
                ]
                if not matching:
                    st.info("이 기간에는 해당 근거 리뷰가 없습니다.")
                for review in matching:
                    with st.container(border=True):
                        render_review(review)
    else:
        st.info("현재 선택한 두 기간에는 표시할 항목별 분류 결과가 없습니다.")

    with st.expander("월별 원문 리뷰 보기"):
        old_tab, new_tab = st.tabs(
            [f"비교 월 {baseline_month}", f"분석 월 {target_month}"]
        )
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
        f"분류 성공 · 비교 월 {coverage['baseline_succeeded']}/{coverage['baseline_total']}, "
        f"분석 월 {coverage['target_succeeded']}/{coverage['target_total']}"
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
    st.title(product.get("title_ko") or product["title"])
    if product.get("title_ko"):
        with st.expander("원문 상품명 보기"):
            st.caption(product["title"])
    st.caption(
        f"{category_label(product['category'])} · parent_asin: {product['parent_asin']}"
    )
    if product.get("image_url"):
        st.image(product["image_url"], width=260)
    else:
        st.caption("상품 이미지 없음")
    description_ko = product["metadata"].get("description_ko")
    description = product["metadata"].get("description")
    if description_ko:
        st.write(description_ko)
    elif description:
        st.info("한국어 상품 설명은 아직 준비 중입니다.")
        with st.expander("원문 상품 설명 보기"):
            st.write(description)
    else:
        st.write("상품 설명이 원천 메타데이터에 없습니다.")
    count_col, rating_col, rating_count_col = st.columns(3)
    with count_col:
        st.metric("저장된 분석 대상 리뷰 수", f"{product['review_count']:,}건")
    with rating_col:
        source_average = product.get("source_average_rating")
        st.metric(
            "원천 전체 평균 평점",
            f"⭐ {source_average:.1f} / 5" if source_average is not None else "정보 없음",
        )
    with rating_count_col:
        source_rating_count = product.get("source_rating_count")
        st.metric(
            "원천 평점 등록 수",
            f"{source_rating_count:,}건" if source_rating_count is not None else "정보 없음",
            help="Amazon 원천 메타데이터의 rating_number이며 실제 구매 수가 아닙니다.",
        )
    st.caption("평점 등록 수는 실제 구매 수 또는 판매량을 의미하지 않습니다.")

    if product["source_mode"] == "real":
        st.info(
            "상품명과 요약 설명은 한국어로 표시합니다. 캐시된 리뷰 번역은 `자동 번역`으로 "
            "표시하고 영어 원문을 함께 제공합니다. 아직 번역되지 않은 리뷰는 `자동 번역 대기 중`입니다."
        )

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


def _saved_annotation_maps(item: dict[str, Any]) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    selected_codes: list[str] = []
    sentiments: dict[str, list[str]] = {}
    evidence: dict[str, str] = {}
    for label in item["annotation"]["gold_labels"]:
        code = f"{label['aspect_code']}.{label['detail_code']}"
        if code not in selected_codes:
            selected_codes.append(code)
        sentiments.setdefault(code, []).append(label["polarity"])
        evidence[f"{code}:{label['polarity']}"] = label["evidence_span"]
    return selected_codes, sentiments, evidence


def render_evaluation() -> None:
    """일반 상품 화면과 분리된 사람 정답 작성용 개발 화면입니다."""
    st.title("리뷰 분류 사람 검토")
    st.warning(
        "이 화면은 개발·평가 전용입니다. 모델 예측은 사람이 정답을 완료 저장한 뒤에만 표시됩니다."
    )
    progress = client.evaluation_progress(EVALUATION_DATASET_ID)
    st.progress(progress["completed"] / progress["total"])
    st.caption(
        f"완료 {progress['completed']} / {progress['total']} · "
        f"미완료 {progress['pending']} · 중단 후 같은 위치에서 재개 가능"
    )
    if not progress["independent_evaluation"]:
        st.warning("프롬프트 조정에 사용된 항목이 포함되어 독립 평가로 볼 수 없습니다.")

    default_position = st.session_state.get(
        "evaluation_position", progress["next_pending_position"] or 1
    )
    position = int(
        st.number_input(
            "검토 번호",
            min_value=1,
            max_value=progress["total"],
            value=int(default_position),
            step=1,
        )
    )
    st.session_state.evaluation_position = position
    item = client.evaluation_item(EVALUATION_DATASET_ID, position)
    review = item["review"]
    product_name = item.get("product_name_ko") or item["product_name"]
    st.subheader(product_name)
    st.caption(
        f"{category_label(item['category'])} · 리뷰 ID: {review['id']} · "
        f"평가 분할: {item['split']}"
    )
    st.markdown(f"**{review.get('title') or '제목 없음'}**")
    st.write(review["text"])

    if review.get("text_ko"):
        with st.expander("자동 번역 참고본 보기"):
            st.caption("자동 번역은 정답이 아니며 영어 원문을 기준으로 검토합니다.")
            st.markdown(f"**{review.get('title_ko') or '제목 없음'}**")
            st.write(review["text_ko"])
    elif st.button("이 리뷰만 자동 번역", key=f"translate-{review['id']}"):
        with st.spinner("번역 중입니다..."):
            client.translate_review(review["id"])
        st.rerun()

    saved_codes, saved_sentiments, saved_evidence = _saved_annotation_maps(item)
    option_by_code = {
        f"{option['aspect_code']}.{option['detail_code']}": option
        for option in item["taxonomy"]
    }
    selected_codes = st.multiselect(
        "언급된 평가 항목(복수 선택)",
        options=list(option_by_code),
        default=saved_codes,
        format_func=lambda code: (
            f"{option_by_code[code]['aspect_name_ko']} / "
            f"{option_by_code[code]['detail_name_ko']} ({code})"
        ),
        key=f"codes-{review['id']}",
    )
    polarity_names = {
        "positive": "긍정",
        "negative": "부정",
        "neutral": "중립",
        "uncertain": "판단 보류",
    }
    labels: list[dict[str, str]] = []
    for code in selected_codes:
        option = option_by_code[code]
        selected_polarities = st.multiselect(
            f"{option['detail_name_ko']} 감성(긍정·부정 동시 선택 가능)",
            options=list(polarity_names),
            default=saved_sentiments.get(code, []),
            format_func=lambda value: polarity_names[value],
            key=f"polarities-{review['id']}-{code}",
        )
        for polarity in selected_polarities:
            evidence_key = f"{code}:{polarity}"
            evidence_span = st.text_input(
                f"{option['detail_name_ko']} · {polarity_names[polarity]} 원문 근거",
                value=saved_evidence.get(evidence_key, ""),
                help="리뷰 제목이나 본문에 실제로 연속해 존재하는 영어 구간을 붙여 넣으세요.",
                key=f"evidence-{review['id']}-{evidence_key}",
            )
            if evidence_span.strip():
                labels.append(
                    {
                        "aspect_code": option["aspect_code"],
                        "detail_code": option["detail_code"],
                        "polarity": polarity,
                        "evidence_span": evidence_span.strip(),
                    }
                )

    normal_empty = st.checkbox(
        "정상 빈 라벨(정의된 항목에 해당하는 명시적 의견 없음)",
        value=item["annotation"]["is_normal_empty"],
        key=f"empty-{review['id']}",
    )
    reviewer = st.text_input(
        "검토자",
        value=item["annotation"].get("reviewer") or "",
        key=f"reviewer-{review['id']}",
    )
    notes = st.text_area(
        "오류·모호함 메모",
        value=item["annotation"].get("notes") or "",
        key=f"notes-{review['id']}",
    )

    def save(status_value: str) -> None:
        client.save_evaluation(
            EVALUATION_DATASET_ID,
            position,
            {
                "reviewer": reviewer,
                "status": status_value,
                "is_normal_empty": normal_empty,
                "gold_labels": labels,
                "notes": notes,
            },
        )

    pending_col, complete_col = st.columns(2)
    with pending_col:
        if st.button("진행 중으로 저장", width="stretch"):
            save("pending")
            st.success("현재 입력을 저장했습니다.")
    with complete_col:
        if st.button("검토 완료 저장 후 다음", type="primary", width="stretch"):
            save("completed")
            st.session_state.evaluation_position = min(position + 1, progress["total"])
            st.rerun()

    if item["prediction_revealed"]:
        st.subheader("정답 저장 후 모델 예측 비교")
        prediction = item.get("prediction") or {"status": "not_run", "labels": []}
        st.caption(
            f"상태: {prediction['status']} · 분석 버전: "
            f"{prediction.get('analysis_version') or '없음'}"
        )
        if prediction.get("labels"):
            st.dataframe(pd.DataFrame(prediction["labels"]), hide_index=True, width="stretch")
        else:
            st.info("이 리뷰의 모델 예측이 아직 없습니다.")

    st.download_button(
        "현재 평가 CSV 내보내기",
        data=client.evaluation_export(EVALUATION_DATASET_ID),
        file_name=f"{EVALUATION_DATASET_ID}.csv",
        mime="text/csv",
    )


def main() -> None:
    try:
        health = client.health()
        if health["database"] != "connected":
            st.error("데이터베이스 연결이 준비되지 않았습니다.")
            return
        evaluation_mode = st.sidebar.toggle("개발·평가 화면", value=False)
        if evaluation_mode:
            render_evaluation()
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
