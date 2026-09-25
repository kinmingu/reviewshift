import json

import pytest

from scripts.import_amazon_category import load_selection, validate_selected_counts


def test_load_selection_requires_two_products_and_three_consecutive_months(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "categories": {
                    "Electronics": {
                        "products": [
                            {
                                "parent_asin": "PARENT-1",
                                "months": ["2022-11", "2022-12", "2023-01"],
                            },
                            {
                                "parent_asin": "PARENT-2",
                                "months": ["2023-01", "2023-02", "2023-03"],
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    selected = load_selection(path, "Electronics")
    assert set(selected) == {"PARENT-1", "PARENT-2"}


def test_load_selection_rejects_non_consecutive_months(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "categories": {
                    "Electronics": {
                        "products": [
                            {
                                "parent_asin": "PARENT-1",
                                "months": ["2023-01", "2023-03", "2023-04"],
                            },
                            {
                                "parent_asin": "PARENT-2",
                                "months": ["2023-01", "2023-02", "2023-03"],
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="연속된 3개월"):
        load_selection(path, "Electronics")


def test_validate_selected_counts_enforces_each_month_and_total():
    selected = {
        "PARENT-1": {"months": ["2023-01", "2023-02", "2023-03"]},
        "PARENT-2": {"months": ["2023-01", "2023-02", "2023-03"]},
    }
    monthly = {
        "PARENT-1": {"2023-01": 50, "2023-02": 60, "2023-03": 70},
        "PARENT-2": {"2023-01": 80, "2023-02": 90, "2023-03": 100},
    }
    validate_selected_counts(selected, monthly)

    monthly["PARENT-2"]["2023-02"] = 29
    with pytest.raises(ValueError, match="30건 미만"):
        validate_selected_counts(selected, monthly)
