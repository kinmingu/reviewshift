from backend.app.core.database import SessionLocal
from backend.app.fixtures import seed_fixtures


def main() -> None:
    with SessionLocal() as session:
        counts = seed_fixtures(session)
    print(
        "fixture seed complete: "
        f"products={counts['products']} reviews={counts['reviews']} labels={counts['labels']}"
    )


if __name__ == "__main__":
    main()

