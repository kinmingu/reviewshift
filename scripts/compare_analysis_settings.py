from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.app.core.database import SessionLocal
from backend.app.models import Review, ReviewAnalysisResult, ReviewLabel

DEFAULT_SAMPLE = Path("config/analysis_dev_14.json")


def _labels(session: Any, run_id: str, review_id: str) -> list[dict[str, str]]:
    values = session.scalars(
        select(ReviewLabel)
        .where(ReviewLabel.run_id == run_id, ReviewLabel.review_id == review_id)
        .order_by(
            ReviewLabel.aspect,
            ReviewLabel.detail_label,
            ReviewLabel.polarity,
            ReviewLabel.evidence_span,
        )
    )
    return [
        {
            "aspect_code": value.aspect,
            "detail_code": value.detail_label,
            "polarity": value.polarity,
            "evidence_span": value.evidence_span,
        }
        for value in values
    ]


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return round(statistics.mean(values), 1) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description="고정 14건의 두 분석 버전을 비교합니다.")
    parser.add_argument("--baseline-run", default="amazon-absa-qwen35-v1")
    parser.add_argument("--improved-run", default="amazon-absa-qwen35-v2")
    parser.add_argument("--sample-file", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output", type=Path, default=Path("data/evaluation"))
    args = parser.parse_args()

    sample = json.loads(args.sample_file.read_text(encoding="utf-8"))
    review_ids = sample["review_ids"]
    rows: list[dict[str, Any]] = []
    with SessionLocal() as session:
        for review_id in review_ids:
            review = session.get(Review, review_id)
            if review is None:
                raise ValueError(f"리뷰가 없습니다: {review_id}")
            results = {
                result.run_id: result
                for result in session.scalars(
                    select(ReviewAnalysisResult).where(
                        ReviewAnalysisResult.review_id == review_id,
                        ReviewAnalysisResult.run_id.in_(
                            [args.baseline_run, args.improved_run]
                        ),
                    )
                )
            }
            baseline = results.get(args.baseline_run)
            improved = results.get(args.improved_run)
            baseline_labels = _labels(session, args.baseline_run, review_id)
            improved_labels = _labels(session, args.improved_run, review_id)
            metrics = improved.model_metrics_json if improved else {}
            rows.append(
                {
                    "review_id": review_id,
                    "title": review.title or "",
                    "input_chars": len(review.title or "") + len(review.text),
                    "baseline_status": baseline.status if baseline else "not_run",
                    "baseline_duration_ms": baseline.duration_ms if baseline else None,
                    "baseline_labels_json": json.dumps(
                        baseline_labels, ensure_ascii=False
                    ),
                    "improved_status": improved.status if improved else "not_run",
                    "improved_duration_ms": improved.duration_ms if improved else None,
                    "improved_load_ms": round(metrics.get("load_duration", 0) / 1e6, 1)
                    if metrics
                    else None,
                    "improved_prompt_ms": round(
                        metrics.get("prompt_eval_duration", 0) / 1e6, 1
                    )
                    if metrics
                    else None,
                    "improved_output_ms": round(
                        metrics.get("eval_duration", 0) / 1e6, 1
                    )
                    if metrics
                    else None,
                    "improved_prompt_tokens": metrics.get("prompt_eval_count"),
                    "improved_output_tokens": metrics.get("eval_count"),
                    "improved_db_write_ms": improved.db_write_ms if improved else None,
                    "improved_labels_json": json.dumps(
                        improved_labels, ensure_ascii=False
                    ),
                    "labels_changed": baseline_labels != improved_labels,
                }
            )

    baseline_completed = [
        row for row in rows if row["baseline_status"] in {"succeeded", "failed"}
    ]
    baseline_succeeded = [
        row for row in rows if row["baseline_status"] == "succeeded"
    ]
    completed = [row for row in rows if row["improved_status"] == "succeeded"]
    summary = {
        "sample_version": sample["version"],
        "development_comparison_only": True,
        "independent_quality_evaluation": False,
        "baseline_run": args.baseline_run,
        "improved_run": args.improved_run,
        "sample_size": len(rows),
        "baseline_succeeded": len(baseline_succeeded),
        "baseline_failed": sum(row["baseline_status"] == "failed" for row in rows),
        "improved_succeeded": len(completed),
        "improved_failed_or_incomplete": len(rows) - len(completed),
        "baseline_mean_duration_all_final_outcomes_ms": _mean(
            baseline_completed, "baseline_duration_ms"
        ),
        "baseline_mean_duration_succeeded_only_ms": _mean(
            baseline_succeeded, "baseline_duration_ms"
        ),
        "improved_mean_duration_ms": _mean(completed, "improved_duration_ms"),
        "improved_mean_load_ms": _mean(completed, "improved_load_ms"),
        "improved_mean_prompt_ms": _mean(completed, "improved_prompt_ms"),
        "improved_mean_output_ms": _mean(completed, "improved_output_ms"),
        "improved_mean_prompt_tokens": _mean(
            completed, "improved_prompt_tokens"
        ),
        "improved_mean_output_tokens": _mean(
            completed, "improved_output_tokens"
        ),
        "improved_mean_db_write_ms": _mean(completed, "improved_db_write_ms"),
        "changed_count": sum(bool(row["labels_changed"]) for row in completed),
        "semantic_accuracy_note": "사람 정답이 없으므로 정확도나 F1을 계산하지 않음",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "dev14_comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    json_path = args.output / "dev14_comparison.json"
    json_path.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"상세 비교: {csv_path.resolve()}")


if __name__ == "__main__":
    main()
