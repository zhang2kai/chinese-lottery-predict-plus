from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_draws import DataValidationError, analyze_dataset, validate_dataset


def make_dataset(lottery: str = "SSQ", draw_count: int = 5) -> dict:
    if lottery == "SSQ":
        primary = [1, 2, 3, 4, 5, 6]
        secondary = [7]
    else:
        primary = [1, 2, 3, 4, 5]
        secondary = [6, 7]

    return {
        "lottery": lottery,
        "sources": [
            {
                "name": "测试来源",
                "url": "https://example.com/draws",
                "retrieved_at": "2026-09-11T10:30:00+08:00",
            }
        ],
        "draws": [
            {
                "issue": f"2026{index + 1:03d}",
                "date": f"2026-01-{index + 1:02d}",
                "primary": primary,
                "secondary": secondary,
            }
            for index in range(draw_count)
        ],
    }


class ValidateDatasetTests(unittest.TestCase):
    def test_accepts_valid_ssq_data(self) -> None:
        result = validate_dataset(make_dataset("SSQ"))
        self.assertEqual(result["lottery"], "SSQ")
        self.assertEqual(len(result["draws"]), 5)

    def test_accepts_valid_dlt_data(self) -> None:
        result = validate_dataset(make_dataset("DLT"))
        self.assertEqual(result["lottery"], "DLT")

    def test_rejects_duplicate_number(self) -> None:
        data = make_dataset()
        data["draws"][0]["primary"] = [1, 1, 2, 3, 4, 5]
        with self.assertRaisesRegex(DataValidationError, "重复号码"):
            validate_dataset(data)

    def test_rejects_out_of_range_number(self) -> None:
        data = make_dataset("DLT")
        data["draws"][0]["secondary"] = [6, 13]
        with self.assertRaisesRegex(DataValidationError, "01–12"):
            validate_dataset(data)

    def test_rejects_duplicate_issue(self) -> None:
        data = make_dataset()
        data["draws"][1]["issue"] = data["draws"][0]["issue"]
        with self.assertRaisesRegex(DataValidationError, "期号重复"):
            validate_dataset(data)

    def test_requires_timezone_in_retrieval_time(self) -> None:
        data = make_dataset()
        data["sources"][0]["retrieved_at"] = "2026-09-11T10:30:00"
        with self.assertRaisesRegex(DataValidationError, "必须包含时区"):
            validate_dataset(data)


class AnalyzeDatasetTests(unittest.TestCase):
    def test_rejects_short_window(self) -> None:
        with self.assertRaisesRegex(DataValidationError, "少于请求窗口"):
            analyze_dataset(make_dataset(draw_count=3), window=4)

    def test_seed_makes_recommendations_reproducible(self) -> None:
        data = make_dataset(draw_count=5)
        first = analyze_dataset(data, window=5, count=5, seed=42)
        second = analyze_dataset(data, window=5, count=5, seed=42)
        self.assertEqual(first["recommendations"], second["recommendations"])

    def test_generated_ssq_combinations_are_valid_and_unique(self) -> None:
        result = analyze_dataset(make_dataset("SSQ"), window=5, count=5, seed=7)
        combinations = set()
        for item in result["recommendations"]:
            self.assertEqual(len(item["primary"]), 6)
            self.assertEqual(len(item["secondary"]), 1)
            self.assertEqual(item["primary"], sorted(item["primary"]))
            combinations.add((tuple(item["primary"]), tuple(item["secondary"])))
        self.assertEqual(len(combinations), 5)

    def test_limits_recommendation_count(self) -> None:
        with self.assertRaisesRegex(DataValidationError, "1–20"):
            analyze_dataset(make_dataset(), window=5, count=21)


if __name__ == "__main__":
    unittest.main()

