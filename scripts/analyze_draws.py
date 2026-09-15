#!/usr/bin/env python3
"""Validate lottery draw data, summarize frequencies, and generate combinations."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
from math import comb, isfinite, sqrt
from pathlib import Path
import random
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


RULES = {
    "SSQ": {
        "primary": {"count": 6, "minimum": 1, "maximum": 33},
        "secondary": {"count": 1, "minimum": 1, "maximum": 16},
    },
    "DLT": {
        "primary": {"count": 5, "minimum": 1, "maximum": 35},
        "secondary": {"count": 2, "minimum": 1, "maximum": 12},
    },
}

STYLE_LABELS = {
    "hot": "热频风格",
    "cold": "低频风格",
    "uniform": "均匀随机",
}

DISCLAIMER = (
    "彩票开奖是随机事件，历史频次不能预测未来结果。以上号码仅供娱乐，"
    "不保证中奖，也不构成投资或财务建议。"
)

VERIFICATION_STATUSES = {
    "cross-checked",
    "single-official-source",
    "official-source-with-disclosed-conflict",
}


class DataValidationError(ValueError):
    """Raised when source draw data does not satisfy the documented schema."""


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{field} 必须是非空字符串")
    return value.strip()


def _validate_retrieved_at(value: Any, field: str) -> str:
    text = _require_non_empty_string(value, field)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DataValidationError(f"{field} 必须是 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise DataValidationError(f"{field} 必须包含时区")
    return text


def _validate_url(value: Any, field: str) -> str:
    text = _require_non_empty_string(value, field)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DataValidationError(f"{field} 必须是 HTTP(S) URL")
    return text


def _validate_numbers(
    values: Any,
    rule: Mapping[str, int],
    field: str,
) -> tuple[int, ...]:
    if not isinstance(values, list):
        raise DataValidationError(f"{field} 必须是数组")
    if len(values) != rule["count"]:
        raise DataValidationError(f"{field} 必须包含 {rule['count']} 个号码")
    if any(not isinstance(number, int) or isinstance(number, bool) for number in values):
        raise DataValidationError(f"{field} 只能包含整数")
    if len(set(values)) != len(values):
        raise DataValidationError(f"{field} 不能包含重复号码")
    if any(number < rule["minimum"] or number > rule["maximum"] for number in values):
        raise DataValidationError(
            f"{field} 的号码范围必须是 {rule['minimum']:02d}–{rule['maximum']:02d}"
        )
    return tuple(sorted(values))


def validate_dataset(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DataValidationError("输入根节点必须是对象")

    lottery = _require_non_empty_string(data.get("lottery"), "lottery").upper()
    if lottery not in RULES:
        raise DataValidationError("lottery 只能是 SSQ 或 DLT")

    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise DataValidationError("sources 至少包含一个来源")

    sources = []
    for index, source in enumerate(raw_sources):
        if not isinstance(source, dict):
            raise DataValidationError(f"sources[{index}] 必须是对象")
        sources.append(
            {
                "name": _require_non_empty_string(source.get("name"), f"sources[{index}].name"),
                "url": _validate_url(source.get("url"), f"sources[{index}].url"),
                "retrieved_at": _validate_retrieved_at(
                    source.get("retrieved_at"), f"sources[{index}].retrieved_at"
                ),
            }
        )

    raw_verification = data.get("verification")
    if not isinstance(raw_verification, dict):
        raise DataValidationError("verification 必须是对象")
    verification_status = _require_non_empty_string(
        raw_verification.get("status"), "verification.status"
    )
    if verification_status not in VERIFICATION_STATUSES:
        allowed = "、".join(sorted(VERIFICATION_STATUSES))
        raise DataValidationError(f"verification.status 只能是：{allowed}")
    verification = {
        "status": verification_status,
        "note": _require_non_empty_string(
            raw_verification.get("note"), "verification.note"
        ),
    }

    raw_draws = data.get("draws")
    if not isinstance(raw_draws, list) or not raw_draws:
        raise DataValidationError("draws 至少包含一期开奖数据")

    seen_issues: set[str] = set()
    draws = []
    rules = RULES[lottery]
    for index, draw in enumerate(raw_draws):
        if not isinstance(draw, dict):
            raise DataValidationError(f"draws[{index}] 必须是对象")
        issue = _require_non_empty_string(draw.get("issue"), f"draws[{index}].issue")
        if issue in seen_issues:
            raise DataValidationError(f"期号重复：{issue}")
        seen_issues.add(issue)

        draw_date_text = _require_non_empty_string(draw.get("date"), f"draws[{index}].date")
        try:
            draw_date = date.fromisoformat(draw_date_text)
        except ValueError as exc:
            raise DataValidationError(f"draws[{index}].date 必须是 YYYY-MM-DD") from exc
        if draw_date > date.today():
            raise DataValidationError(f"draws[{index}].date 不能晚于今天")

        draws.append(
            {
                "issue": issue,
                "date": draw_date,
                "primary": _validate_numbers(
                    draw.get("primary"), rules["primary"], f"draws[{index}].primary"
                ),
                "secondary": _validate_numbers(
                    draw.get("secondary"), rules["secondary"], f"draws[{index}].secondary"
                ),
            }
        )

    draws.sort(key=lambda item: (item["date"], item["issue"]), reverse=True)
    return {
        "lottery": lottery,
        "sources": sources,
        "verification": verification,
        "draws": draws,
    }


def _frequency(draws: Sequence[Mapping[str, Any]], area: str, maximum: int) -> Counter[int]:
    counts: Counter[int] = Counter({number: 0 for number in range(1, maximum + 1)})
    for draw in draws:
        counts.update(draw[area])
    return counts


def _weights(counts: Mapping[int, int], style: str) -> list[float]:
    maximum = max(counts.values())
    if style == "hot":
        return [counts[number] + 1 for number in counts]
    if style == "cold":
        return [maximum - counts[number] + 1 for number in counts]
    return [1.0 for _ in counts]


def _weighted_sample_without_replacement(
    population: Sequence[int],
    weights: Sequence[float],
    count: int,
    rng: random.Random,
) -> tuple[int, ...]:
    available = list(population)
    available_weights = list(weights)
    selected = []
    for _ in range(count):
        chosen = rng.choices(available, weights=available_weights, k=1)[0]
        index = available.index(chosen)
        selected.append(chosen)
        available.pop(index)
        available_weights.pop(index)
    return tuple(sorted(selected))


def _format_numbers(numbers: Sequence[int]) -> list[str]:
    return [f"{number:02d}" for number in numbers]


def _frequency_summary(counts: Mapping[int, int], limit: int = 5) -> dict[str, Any]:
    numbers = list(counts)
    hot = sorted(numbers, key=lambda number: (-counts[number], number))[:limit]
    cold = sorted(numbers, key=lambda number: (counts[number], number))[:limit]
    return {
        "hot": [{"number": f"{number:02d}", "count": counts[number]} for number in hot],
        "cold": [{"number": f"{number:02d}", "count": counts[number]} for number in cold],
    }


def mathematical_models(
    lottery: str,
    area_counts: Mapping[str, Mapping[int, int]],
    window: int,
    ticket_count: int,
    payouts: Any = None,
) -> dict[str, Any]:
    """Fair, independent draws; payouts are an explicit pre-tax scenario."""
    rules = RULES[lottery]
    total = 1
    ways = {}
    frequency_baseline = {}
    for area, rule in rules.items():
        n, k = rule["maximum"], rule["count"]
        total *= comb(n, k)
        ways[area] = [comb(k, hits) * comb(n - k, k - hits) for hits in range(k + 1)]
        p = k / n
        frequency_baseline[area] = {
            "per_draw_probability": p,
            "expected_count": window * p,
            "count_standard_deviation": sqrt(window * p * (1 - p)),
            "frequency_standard_error": sqrt(p * (1 - p) / window),
            "observed_rates": {
                f"{number:02d}": value / window
                for number, value in area_counts[area].items()
            },
        }

    outcomes = [
        {
            "matches": f"{primary}+{secondary}",
            "favorable_outcomes": primary_ways * secondary_ways,
            "probability": primary_ways * secondary_ways / total,
        }
        for primary, primary_ways in enumerate(ways["primary"])
        for secondary, secondary_ways in enumerate(ways["secondary"])
    ]
    ev = {
        "status": "unavailable",
        "ticket_cost_yuan": 2,
        "formula": "EV = sum(P(matches) * E[payout_yuan | matches]) - 2",
        "gross_expected_payout_yuan": None,
        "net_ev_yuan": None,
        "reason": "缺少完整的各命中类别条件期望奖金，不能计算数值 EV。",
    }
    if payouts is not None:
        if not isinstance(payouts, dict) or payouts.get("lottery") != lottery:
            raise DataValidationError("payouts.lottery 必须与开奖数据一致")
        note = _require_non_empty_string(payouts.get("note"), "payouts.note")
        amounts = payouts.get("amounts")
        if not isinstance(amounts, dict) or set(amounts) != {row["matches"] for row in outcomes}:
            raise DataValidationError("payouts.amounts 必须完整覆盖所有命中类别，未中奖类别也须显式填 0")
        for amount in amounts.values():
            if (
                isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or amount < 0
                or amount > sys.float_info.max
                or not isfinite(amount)
            ):
                raise DataValidationError("奖金必须是有限的非负数，单位为元")
        gross = sum(row["probability"] * amounts[row["matches"]] for row in outcomes)
        ev.update({
            "status": "scenario",
            "reason": None,
            "note": note,
            "basis": "税前情景值；不代表实际收益预测",
            "amounts": amounts,
            "gross_expected_payout_yuan": gross,
            "net_ev_yuan": gross - 2,
        })

    return {
        "assumption": "每期公平、独立开奖，各区均匀且独立抽取，号码规则在窗口内不变。",
        "combinatorics": {
            "total_combinations": total,
            "single_ticket_jackpot_probability": 1 / total,
            "distinct_tickets_same_draw": ticket_count,
            "distinct_tickets_jackpot_probability": ticket_count / total,
            "match_distribution": outcomes,
        },
        "law_of_large_numbers": {
            "areas": frequency_baseline,
            "interpretation": "长期相对频次趋近理论概率，不保证短期补偿；各号码计数并非相互独立。",
        },
        "expected_value": ev,
    }


def analyze_dataset(
    data: Any,
    *,
    window: int = 100,
    count: int = 5,
    seed: int | None = None,
    payouts: Any = None,
) -> dict[str, Any]:
    if window <= 0:
        raise DataValidationError("window 必须大于 0")
    if count <= 0 or count > 20:
        raise DataValidationError("count 必须位于 1–20")

    dataset = validate_dataset(data)
    draws = dataset["draws"]
    if len(draws) < window:
        raise DataValidationError(f"有效开奖数据只有 {len(draws)} 期，少于请求窗口 {window} 期")

    selected = draws[:window]
    rules = RULES[dataset["lottery"]]
    primary_counts = _frequency(selected, "primary", rules["primary"]["maximum"])
    secondary_counts = _frequency(selected, "secondary", rules["secondary"]["maximum"])
    models = mathematical_models(
        dataset["lottery"], {"primary": primary_counts, "secondary": secondary_counts},
        window, count, payouts,
    )

    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    primary_population = list(primary_counts)
    secondary_population = list(secondary_counts)
    styles = ("hot", "cold", "uniform")
    recommendations = []
    seen: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()

    attempts = 0
    while len(recommendations) < count and attempts < count * 100:
        style = styles[len(recommendations) % len(styles)]
        primary = _weighted_sample_without_replacement(
            primary_population,
            _weights(primary_counts, style),
            rules["primary"]["count"],
            rng,
        )
        secondary = _weighted_sample_without_replacement(
            secondary_population,
            _weights(secondary_counts, style),
            rules["secondary"]["count"],
            rng,
        )
        combination = (primary, secondary)
        attempts += 1
        if combination in seen:
            continue
        seen.add(combination)
        recommendations.append(
            {
                "style": style,
                "style_label": STYLE_LABELS[style],
                "primary": _format_numbers(primary),
                "secondary": _format_numbers(secondary),
            }
        )

    if len(recommendations) != count:
        raise RuntimeError("无法生成足够的不重复号码组合")

    newest = selected[0]
    oldest = selected[-1]
    return {
        "lottery": dataset["lottery"],
        "sources": dataset["sources"],
        "verification": dataset["verification"],
        "window": {
            "size": window,
            "start_issue": oldest["issue"],
            "start_date": oldest["date"].isoformat(),
            "end_issue": newest["issue"],
            "end_date": newest["date"].isoformat(),
        },
        "frequency_summary": {
            "primary": _frequency_summary(primary_counts),
            "secondary": _frequency_summary(secondary_counts),
        },
        "recommendations": recommendations,
        "mathematical_models": models,
        "seed": seed,
        "disclaimer": DISCLAIMER,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验真实历史开奖数据，统计频次并生成娱乐型合法号码组合。"
    )
    parser.add_argument("input", type=Path, help="UTF-8 JSON 数据文件")
    parser.add_argument("--window", type=int, default=100, help="统计期数，默认 100")
    parser.add_argument("--count", type=int, default=5, help="生成注数，范围 1–20，默认 5")
    parser.add_argument("--seed", type=int, help="可选随机种子，用于复现结果")
    parser.add_argument("--payouts", type=Path, help="可选的完整税前奖金情景 JSON，格式见 references/mathematical-models.md")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        payouts = json.loads(args.payouts.read_text(encoding="utf-8")) if args.payouts else None
        result = analyze_dataset(data, window=args.window, count=args.count, seed=args.seed, payouts=payouts)
    except (OSError, json.JSONDecodeError, DataValidationError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
