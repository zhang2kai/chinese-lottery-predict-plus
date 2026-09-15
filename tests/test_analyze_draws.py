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
        "verification": {
            "status": "single-official-source",
            "note": "仅用于单元测试的合成数据，不用于实际选号",
        },
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
    def test_mathematical_probabilities_cover_all_outcomes(self) -> None:
        for lottery, total, categories in [("SSQ", 17721088, 14), ("DLT", 21425712, 18)]:
            with self.subTest(lottery=lottery):
                models = analyze_dataset(make_dataset(lottery), window=5, count=5)["mathematical_models"]
                combinations = models["combinatorics"]
                rows = combinations["match_distribution"]
                self.assertEqual(combinations["total_combinations"], total)
                self.assertEqual(len(rows), categories)
                self.assertEqual(sum(row["favorable_outcomes"] for row in rows), total)
                self.assertAlmostEqual(sum(row["probability"] for row in rows), 1)
                self.assertEqual(rows[-1]["favorable_outcomes"], 1)
                self.assertEqual(combinations["single_ticket_jackpot_probability"], 1 / total)
                self.assertEqual(combinations["distinct_tickets_jackpot_probability"], 5 / total)
                # Marginal expected matches for two fixed-size uniform subsets: k²/n.
                n, k = (33, 6) if lottery == "SSQ" else (35, 5)
                self.assertAlmostEqual(sum(int(row["matches"].split("+")[0]) * row["probability"] for row in rows), k * k / n)

    def test_frequency_baseline_and_missing_ev(self) -> None:
        models = analyze_dataset(make_dataset(), window=5)["mathematical_models"]
        primary = models["law_of_large_numbers"]["areas"]["primary"]
        self.assertEqual(primary["per_draw_probability"], 6 / 33)
        self.assertAlmostEqual(primary["expected_count"], 5 * 6 / 33)
        self.assertAlmostEqual(primary["count_standard_deviation"] ** 2, 5 * (6 / 33) * (27 / 33))
        self.assertAlmostEqual(primary["frequency_standard_error"] ** 2, (6 / 33) * (27 / 33) / 5)
        self.assertEqual(primary["observed_rates"]["01"], 1)
        self.assertEqual(primary["observed_rates"]["33"], 0)
        self.assertEqual(models["expected_value"]["status"], "unavailable")
        self.assertIsNone(models["expected_value"]["net_ev_yuan"])

    def test_ev_scenarios(self) -> None:
        for lottery, k, s, total in [("SSQ", 6, 1, 17721088), ("DLT", 5, 2, 21425712)]:
            amounts = {f"{r}+{b}": 0 for r in range(k + 1) for b in range(s + 1)}
            scenario = {"lottery": lottery, "note": "合成测试情景，并非真实奖金", "amounts": amounts}
            for jackpot, expected_net in [(0, -2), (total, -1), (2 * total, 0)]:
                amounts[f"{k}+{s}"] = jackpot
                ev = analyze_dataset(make_dataset(lottery), window=5, payouts=scenario)["mathematical_models"]["expected_value"]
                self.assertEqual(ev["status"], "scenario")
                self.assertAlmostEqual(ev["net_ev_yuan"], expected_net)
                self.assertAlmostEqual(ev["gross_expected_payout_yuan"], expected_net + 2)

    def test_invalid_payout_scenarios_are_rejected(self) -> None:
        amounts = {f"{r}+{b}": 0 for r in range(7) for b in range(2)}
        base = {"lottery": "SSQ", "note": "测试情景", "amounts": amounts}
        bad_scenarios = [
            [], {**base, "lottery": "DLT"}, {**base, "note": ""},
            {**base, "amounts": {"6+1": 100}},
            {**base, "amounts": {**amounts, "7+0": 0}},
        ]
        for value in [-1, True, "100", float("inf"), float("nan")]:
            bad_scenarios.append({**base, "amounts": {**amounts, "6+1": value}})
        for scenario in bad_scenarios:
            with self.subTest(scenario=scenario), self.assertRaises(DataValidationError):
                analyze_dataset(make_dataset(), window=5, payouts=scenario)

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
