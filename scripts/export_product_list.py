"""상품 확인용 목록을 만듭니다(DB 읽기 전용).

- docs/products.md: 35개 상품의 ID·한국어/원문 이름·기간·리뷰 수·AI 표본·Amazon 링크(Git 추적)
- data/reports/products.html: 사진까지 한눈에 보는 확인용 페이지(브라우저로 열기, Git 제외)
"""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import func, select

from backend.app.core.categories import REAL_CATEGORY_KEYS, REAL_CATEGORY_NAMES_KO
from backend.app.core.database import SessionLocal
from backend.app.models import Product, Review
from backend.app.services.analysis_sample import build_sample_plan

MD_PATH = Path("docs/products.md")
HTML_PATH = Path("data/reports/products.html")


def amazon_url(parent_asin: str) -> str:
    return f"https://www.amazon.com/dp/{parent_asin}"


def archive_url(parent_asin: str) -> str:
    """단종·삭제된 상품은 현재 Amazon 주소가 없어서, 2023년 무렵 보관본을 봅니다(Wayback Machine)."""
    return f"https://web.archive.org/web/2023/https://www.amazon.com/dp/{parent_asin}"


def search_url(title: str) -> str:
    return "https://www.amazon.com/s?k=" + quote_plus(title[:80])


def load_rows() -> list[dict]:
    rows = []
    with SessionLocal() as session:
        products = session.scalars(
            select(Product)
            .where(Product.source_mode == "real", Product.category.in_(REAL_CATEGORY_KEYS))
            .order_by(Product.category, Product.id)
        ).all()
        for product in products:
            meta = product.metadata_json
            count = session.scalar(
                select(func.count(Review.id)).where(
                    Review.product_id == product.id, Review.eligible.is_(True)
                )
            )
            plan = build_sample_plan(session, product)
            months = meta.get("analysis_months") or []
            rows.append(
                {
                    "category": product.category,
                    "category_ko": REAL_CATEGORY_NAMES_KO[product.category],
                    "asin": product.parent_asin,
                    "title_ko": meta.get("title_ko") or "",
                    "title": product.title,
                    "store": meta.get("store") or "",
                    "period": f"{months[0]} ~ {months[-1]}" if months else "",
                    "reviews": int(count or 0),
                    "sample": len(plan.members) if plan else None,
                    "sample_target": meta.get("analysis_sample_size"),
                    "rating": meta.get("source_average_rating"),
                    "rating_count": meta.get("source_rating_number"),
                    "name_source": "Claude 초안" if meta.get("title_ko_source") == "claude-draft" else "사람 작성",
                    "image": product.image_url or "",
                }
            )
    return rows


def write_markdown(rows: list[dict]) -> None:
    lines = [
        "# ReviewShift 분석 대상 상품 목록",
        "",
        "`python -m scripts.export_product_list`로 DB에서 생성한 목록입니다. 원문 이름·사진·리뷰는 같은",
        "parent_asin의 Amazon Reviews 2023 공식 메타데이터·리뷰에서 가져왔습니다. Amazon 링크는 현재 판매",
        "페이지라 단종·삭제된 상품은 'Sorry' 페이지가 뜹니다. 그때는 2023년 무렵 웹 보관본이나 상품명 검색으로",
        "확인하세요(데이터셋은 2023년에 수집됨). 평점 등록 수는 구매 수가 아닙니다.",
        "",
        f"- 상품 {len(rows)}개, 저장 리뷰 {sum(r['reviews'] for r in rows):,}건, "
        f"AI 분석 표본 {sum(r['sample'] or 0 for r in rows):,}건",
        "",
        "| 카테고리 | 한국어 이름 (작성) | 원문 상품명 · 판매자 | parent_asin | 확인 링크 | 분석 기간 | 저장 리뷰 | AI 표본 | Amazon 평점 (등록 수) |",
        "|---|---|---|---|---|---|---:|---:|---|",
    ]
    for r in rows:
        title = r["title"] if len(r["title"]) <= 70 else r["title"][:70] + "…"
        rating = f"{r['rating']} ({r['rating_count']:,})" if r["rating"] and r["rating_count"] else "-"
        lines.append(
            f"| {r['category_ko']} | {r['title_ko']} ({r['name_source']}) | {title.replace('|', '/')} · {r['store']} "
            f"| [{r['asin']}]({amazon_url(r['asin'])}) "
            f"| [2023 보관본]({archive_url(r['asin'])}) · [검색]({search_url(r['title'])}) "
            f"| {r['period']} | {r['reviews']} "
            f"| {r['sample']} (목표 {r['sample_target']}) | {rating} |"
        )
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(rows: list[dict]) -> None:
    cards = []
    for r in rows:
        cards.append(
            f"""<div class="card"><img src="{html.escape(r['image'])}" alt="" loading="lazy">
<div class="body"><div class="cat">{html.escape(r['category_ko'])}</div>
<b>{html.escape(r['title_ko'])}</b><div class="en">{html.escape(r['title'])}</div>
<div class="meta">ID <code>{r['asin']}</code> · {html.escape(r['period'])}<br>
저장 리뷰 {r['reviews']}건 · AI 표본 {r['sample']}건 · 이름 {r['name_source']}</div>
<a href="{amazon_url(r['asin'])}" target="_blank" rel="noopener">Amazon 현재 페이지 ↗</a><br>
<a href="{archive_url(r['asin'])}" target="_blank" rel="noopener">2023년 무렵 보관본 ↗</a> ·
<a href="{html.escape(search_url(r['title']))}" target="_blank" rel="noopener">상품명 검색 ↗</a></div></div>"""
        )
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>ReviewShift 상품 확인</title>
<style>body{{font-family:'Malgun Gothic',sans-serif;background:#faf8f5;color:#1f2a44;margin:24px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}}
.card{{background:#fff;border:1px solid #e7e2d9;border-radius:14px;overflow:hidden}}
.card img{{width:100%;height:180px;object-fit:contain;background:#f1ede6}}
.body{{padding:12px;font-size:13px;line-height:1.5}}.cat{{color:#7c5cff;font-weight:700}}
.en{{color:#8a8f98;font-size:12px;margin:4px 0}}.meta{{color:#4b5670;font-size:12px}}code{{font-size:12px}}
a{{color:#2f6feb;font-weight:700;text-decoration:none}}</style></head><body>
<h1>ReviewShift 분석 대상 상품 {len(rows)}개</h1><p>사진·한국어 이름·원문 이름·ID가 같은 상품인지 확인하는 페이지입니다. 오래된 상품은 Amazon 현재 페이지가
삭제되어 'Sorry'가 뜰 수 있습니다(데이터는 2023년 수집). 그때는 '2023년 무렵 보관본'이나 '상품명 검색'으로 확인하세요.</p>
<div class="grid">{''.join(cards)}</div></body></html>"""
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(page, encoding="utf-8")


def main() -> None:
    rows = load_rows()
    write_markdown(rows)
    write_html(rows)
    print(f"{MD_PATH} / {HTML_PATH.resolve()} ({len(rows)}개)")


if __name__ == "__main__":
    main()
