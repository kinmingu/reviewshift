"""합성(fixture) 테스트 데이터를 DB에 넣는 스크립트. 예) python -m scripts.seed_fixtures"""

from backend.app.core.database import SessionLocal
from backend.app.fixtures import seed_fixtures


# 합성 데이터를 넣고 개수를 출력합니다.
def main() -> None:
    with SessionLocal() as session:
        counts = seed_fixtures(session)
    print(
        "fixture seed complete: "
        f"products={counts['products']} reviews={counts['reviews']} labels={counts['labels']}"
    )


if __name__ == "__main__":
    main()

