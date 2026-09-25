import csv
import io

from fastapi.testclient import TestClient

DATASET = "human-eval-140-v1"


def test_evaluation_progress_and_prediction_are_blind(client: TestClient) -> None:
    progress = client.get(f"/api/v1/evaluation/datasets/{DATASET}/progress")
    assert progress.status_code == 200
    assert progress.json()["total"] == 140
    assert progress.json()["independent_evaluation"] is True

    item = client.get(f"/api/v1/evaluation/datasets/{DATASET}/items/1")
    assert item.status_code == 200
    assert item.json()["prediction_revealed"] is False
    assert item.json()["prediction"] is None


def test_evaluation_save_resume_mixed_labels_and_export(client: TestClient) -> None:
    path = f"/api/v1/evaluation/datasets/{DATASET}/items/1"
    payload = {
        "reviewer": "pytest-reviewer",
        "status": "completed",
        "is_normal_empty": False,
        "gold_labels": [
            {
                "aspect_code": "performance",
                "detail_code": "reliability",
                "polarity": "positive",
                "evidence_span": "absolutely loved this hairdryer",
            },
            {
                "aspect_code": "performance",
                "detail_code": "reliability",
                "polarity": "negative",
                "evidence_span": "exploded in my hands",
            },
            {
                "aspect_code": "beauty_use",
                "detail_code": "hair_drying",
                "polarity": "uncertain",
                "evidence_span": "hairdryer",
            },
        ],
        "notes": "혼합 감성·판단 보류 저장 시험",
    }
    saved = client.put(path, json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert body["annotation"]["status"] == "completed"
    assert len(body["annotation"]["gold_labels"]) == 3
    assert body["prediction_revealed"] is True

    resumed = client.get(path).json()
    assert resumed["annotation"]["reviewer"] == "pytest-reviewer"
    exported = client.get(f"/api/v1/evaluation/datasets/{DATASET}/export")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["review_status"] == "completed"
    assert "reliability" in rows[0]["gold_labels_json"]

    # 다른 테스트와 실제 사용자 검토 시작 상태를 보존합니다.
    reset = client.put(
        path,
        json={
            "reviewer": None,
            "status": "pending",
            "is_normal_empty": False,
            "gold_labels": [],
            "notes": None,
        },
    )
    assert reset.status_code == 200


def test_completed_empty_label_requires_explicit_normal_empty(client: TestClient) -> None:
    path = f"/api/v1/evaluation/datasets/{DATASET}/items/2"
    invalid = client.put(
        path,
        json={
            "reviewer": "pytest-reviewer",
            "status": "completed",
            "is_normal_empty": False,
            "gold_labels": [],
        },
    )
    assert invalid.status_code == 422

    valid = client.put(
        path,
        json={
            "reviewer": "pytest-reviewer",
            "status": "completed",
            "is_normal_empty": True,
            "gold_labels": [],
        },
    )
    assert valid.status_code == 200
    assert valid.json()["annotation"]["is_normal_empty"] is True

    client.put(
        path,
        json={
            "reviewer": None,
            "status": "pending",
            "is_normal_empty": False,
            "gold_labels": [],
        },
    )


def test_evidence_must_be_in_original_review(client: TestClient) -> None:
    response = client.put(
        f"/api/v1/evaluation/datasets/{DATASET}/items/1",
        json={
            "reviewer": "pytest-reviewer",
            "status": "completed",
            "is_normal_empty": False,
            "gold_labels": [
                {
                    "aspect_code": "performance",
                    "detail_code": "reliability",
                    "polarity": "negative",
                    "evidence_span": "text that is not in this review",
                }
            ],
        },
    )
    assert response.status_code == 422
