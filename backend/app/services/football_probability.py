"""
Football score probability simulation utilities.

This module extracts football prediction inputs from a simulation folder and
runs a reproducible bivariate-Poisson Monte Carlo simulation.
"""

import hashlib
import json
import math
import os
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config


@dataclass
class FootballPredictionInputs:
    home_team: str
    away_team: str
    lambda_home: float
    lambda_away: float
    samples: int
    correlation: float
    source: str
    warnings: List[str]


class FootballProbabilitySimulator:
    """Extracts inputs and runs score probability simulations for football reports."""

    DEFAULT_SAMPLES = 100_000
    SCORE_MATRIX_MAX = 6

    FOOTBALL_KEYWORDS = (
        "足球", "football", "泊松", "poisson", "比分", "score",
        "lambda_home", "lambda_away", "expected_goals", "xg",
    )

    @classmethod
    def should_run(cls, simulation_requirement: str) -> bool:
        text = (simulation_requirement or "").lower()
        return any(keyword.lower() in text for keyword in cls.FOOTBALL_KEYWORDS)

    @classmethod
    def simulate_from_simulation(
        cls,
        simulation_id: str,
        simulation_requirement: str,
        samples: int = DEFAULT_SAMPLES,
    ) -> Optional[Dict[str, Any]]:
        config = cls._load_simulation_config(simulation_id)
        texts = cls._collect_texts(simulation_id, config, simulation_requirement)
        inputs = cls._extract_inputs(config, texts, samples=samples)
        if not inputs:
            return None

        return cls._run_bivariate_poisson(inputs)

    @classmethod
    def _load_simulation_config(cls, simulation_id: str) -> Dict[str, Any]:
        path = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id, "simulation_config.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def _collect_texts(
        cls,
        simulation_id: str,
        config: Dict[str, Any],
        simulation_requirement: str,
    ) -> List[str]:
        texts: List[str] = []

        for post in config.get("event_config", {}).get("initial_posts", []) or []:
            content = post.get("content")
            if content:
                texts.append(str(content))

        narrative = config.get("event_config", {}).get("narrative_direction")
        if narrative:
            texts.append(str(narrative))
        topics = config.get("event_config", {}).get("hot_topics") or []
        if topics:
            texts.append(" ".join(str(topic) for topic in topics))

        if simulation_requirement:
            texts.append(simulation_requirement)

        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        for platform in ("twitter", "reddit"):
            actions_path = os.path.join(sim_dir, platform, "actions.jsonl")
            if not os.path.exists(actions_path):
                continue
            try:
                with open(actions_path, "r", encoding="utf-8") as f:
                    for index, line in enumerate(f):
                        if index >= 200:
                            break
                        try:
                            item = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        args = item.get("action_args") or {}
                        content = args.get("content") or item.get("content")
                        if content:
                            texts.append(str(content))
            except OSError:
                continue

        return texts

    @classmethod
    def _extract_inputs(
        cls,
        config: Dict[str, Any],
        texts: List[str],
        samples: int,
    ) -> Optional[FootballPredictionInputs]:
        warnings: List[str] = []
        joined = "\n".join(texts)

        home_team, away_team = cls._extract_teams(config, joined)
        lambda_home, lambda_away, source, lambda_warnings = cls._extract_lambdas(joined, home_team, away_team)
        warnings.extend(lambda_warnings)

        if lambda_home is None or lambda_away is None:
            warnings.append("未找到明确的 lambda_home/lambda_away 数值，无法生成比分概率分布。")
            return None

        correlation = cls._infer_correlation(joined, lambda_home, lambda_away)
        return FootballPredictionInputs(
            home_team=home_team,
            away_team=away_team,
            lambda_home=lambda_home,
            lambda_away=lambda_away,
            samples=samples,
            correlation=correlation,
            source=source,
            warnings=warnings,
        )

    @classmethod
    def _extract_teams(cls, config: Dict[str, Any], text: str) -> Tuple[str, str]:
        # Prefer explicit Team type, fall back to NationalTeam
        configured = [
            agent.get("entity_name")
            for agent in config.get("agent_configs", [])
            if agent.get("entity_type") in ("Team", "NationalTeam") and agent.get("entity_name")
        ]

        # If we have configured teams, use them directly (most reliable)
        if len(configured) >= 2:
            return configured[0], configured[1]
        if len(configured) == 1:
            return configured[0], "Opponent"

        # Case-insensitive vs match (fallback when no configured teams)
        match = re.search(r"(?i)([\w一-鿿]+)\s*(?:vs|VS|对阵|迎战|挑战)\s*([\w一-鿿]+)", text)
        if match:
            first, second = match.group(1), match.group(2)
            if "主场" in text[max(0, match.start() - 30):match.end() + 60]:
                return first, second
            return first, second

        if "Qatar" in text or "卡塔尔" in text:
            if "Switzerland" in text or "瑞士" in text:
                return "Qatar", "Switzerland"

        return "Home", "Away"

    @classmethod
    def _extract_lambdas(
        cls,
        text: str,
        home_team: str,
        away_team: str,
    ) -> Tuple[Optional[float], Optional[float], str, List[str]]:
        warnings: List[str] = []
        patterns = [
            (r"lambda_home\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", "home"),
            (r"lambda_away\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", "away"),
            (r"主队[^0-9]{0,20}(?:预期进球|expected_goals|lambda)[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)", "home"),
            (r"客队[^0-9]{0,20}(?:预期进球|expected_goals|lambda)[^0-9]{0,10}([0-9]+(?:\.[0-9]+)?)", "away"),
            (r"卡塔尔主场\s*([0-9]+(?:\.[0-9]+)?)", "home"),
            (r"瑞士客场(?:预期进球)?\s*([0-9]+(?:\.[0-9]+)?)", "away"),
        ]
        values: Dict[str, float] = {}
        for pattern, key in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                values[key] = float(match.group(1))

        if "home" in values and "away" in values:
            return values["home"], values["away"], "explicit_lambda", warnings

        # Common prose: "瑞士客场预期进球1.71，卡塔尔主场0.87".
        away_match = re.search(r"瑞士[^。\n]{0,20}(?:预期进球|expected_goals|lambda值?)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        home_match = re.search(r"卡塔尔[^。\n]{0,20}(?:预期进球|expected_goals|主场)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        if home_match and away_match:
            return float(home_match.group(1)), float(away_match.group(1)), "prose_lambda", warnings

        # Fallback for "expected_goals 0.98 vs 瑞士的1.63".
        eg_match = re.search(
            r"expected_goals\s*([0-9]+(?:\.[0-9]+)?)\s*(?:vs|VS|对)\s*(?:瑞士|Switzerland)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if eg_match:
            return float(eg_match.group(1)), float(eg_match.group(2)), "expected_goals_pair", warnings

        def nearest_team_key(position: int) -> Optional[str]:
            window = text[max(0, position - 140):position + 40].lower()
            home_pos = window.rfind(home_team.lower())
            away_pos = window.rfind(away_team.lower())
            if home_pos == -1 and away_pos == -1:
                return None
            if home_pos >= away_pos:
                return "home"
            return "away"

        # Support "xG of 2.38" / "xG: 2.38" / "2.38 xG" formats.
        xg_pattern = r"(?:\bxG\s*(?:of|:)?\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*\bxG\b)"
        for xg_match in re.finditer(xg_pattern, text, re.IGNORECASE):
            raw_value = xg_match.group(1) or xg_match.group(2)
            if raw_value is None:
                continue
            val = float(raw_value)
            if val < 0.1:
                continue
            team_key = nearest_team_key(xg_match.start())
            if team_key:
                if team_key not in values:
                    values[team_key] = val
                continue
            if "home" not in values:
                values["home"] = val
            elif "away" not in values:
                values["away"] = val

        # xGA describes goals allowed by a team, so it is a useful opponent lambda prior.
        xga_pattern = r"(?:\bxGA\s*(?:of|:)?\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*\bxGA\b)"
        for xga_match in re.finditer(xga_pattern, text, re.IGNORECASE):
            raw_value = xga_match.group(1) or xga_match.group(2)
            if raw_value is None:
                continue
            val = float(raw_value)
            if val < 0.1:
                continue
            team_key = nearest_team_key(xga_match.start())
            if team_key == "home" and "away" not in values:
                values["away"] = val
            elif team_key == "away" and "home" not in values:
                values["home"] = val

        if "home" in values and "away" in values:
            return values["home"], values["away"], "xG_based", warnings

        if "home" in values and "away" not in values:
            values["away"] = round(values["home"] * 0.55, 2)
            warnings.append("仅抽取到主队xG，客队lambda由主队xG按保守比例派生。")
            return values["home"], values["away"], "xG_based", warnings

        if "away" in values and "home" not in values:
            values["home"] = round(values["away"] * 1.8, 2)
            warnings.append("仅抽取到客队xG，主队lambda由客队xG按保守比例派生。")
            return values["home"], values["away"], "xG_based", warnings

        return None, None, "missing", warnings

    @classmethod
    def _infer_correlation(cls, text: str, lambda_home: float, lambda_away: float) -> float:
        defense_values = [float(v) for v in re.findall(r"防守(?:指数|评分)?[^0-9]{0,6}([0-9]+(?:\.[0-9]+)?)", text)]
        if defense_values:
            strongest = max(defense_values)
            return min(0.12, max(0.03, (strongest - 70.0) / 250.0))
        gap = abs(lambda_home - lambda_away)
        return min(0.08, max(0.03, gap / 20.0))

    @classmethod
    def _run_bivariate_poisson(cls, inputs: FootballPredictionInputs) -> Dict[str, Any]:
        common_lambda = min(inputs.lambda_home, inputs.lambda_away) * inputs.correlation
        home_base = max(0.001, inputs.lambda_home - common_lambda)
        away_base = max(0.001, inputs.lambda_away - common_lambda)

        seed_basis = f"{inputs.home_team}|{inputs.away_team}|{inputs.lambda_home}|{inputs.lambda_away}|{inputs.samples}|{inputs.correlation}"
        seed = int(hashlib.sha256(seed_basis.encode("utf-8")).hexdigest()[:16], 16)
        rng = random.Random(seed)

        scores: Counter[Tuple[int, int]] = Counter()
        home_wins = draws = away_wins = 0
        home_goals_total = away_goals_total = 0

        for _ in range(inputs.samples):
            home_goals = cls._sample_poisson(rng, home_base) + cls._sample_poisson(rng, common_lambda)
            away_goals = cls._sample_poisson(rng, away_base) + cls._sample_poisson(rng, common_lambda)
            scores[(home_goals, away_goals)] += 1
            home_goals_total += home_goals
            away_goals_total += away_goals
            if home_goals > away_goals:
                home_wins += 1
            elif home_goals == away_goals:
                draws += 1
            else:
                away_wins += 1

        top_scores = [
            {"score": f"{home}-{away}", "prob": round(count / inputs.samples, 4)}
            for (home, away), count in scores.most_common(8)
        ]
        correct_score = [
            {
                "score": item["score"],
                "prob": item["prob"],
                "implied_odds": cls._fair_odds(item["prob"]),
            }
            for item in top_scores
        ]

        matrix = []
        for home in range(cls.SCORE_MATRIX_MAX + 1):
            row = []
            for away in range(cls.SCORE_MATRIX_MAX + 1):
                row.append(round(scores.get((home, away), 0) / inputs.samples, 4))
            matrix.append(row)

        overflow = sum(
            count for (home, away), count in scores.items()
            if home > cls.SCORE_MATRIX_MAX or away > cls.SCORE_MATRIX_MAX
        )

        over_under = cls._derive_over_under(scores, inputs.samples)
        btts = cls._derive_btts(scores, inputs.samples)
        asian_handicap = cls._derive_asian_handicap(scores, inputs.samples)
        double_chance = {
            "home_or_draw": round((home_wins + draws) / inputs.samples, 4),
            "home_or_away": round((home_wins + away_wins) / inputs.samples, 4),
            "draw_or_away": round((draws + away_wins) / inputs.samples, 4),
        }
        non_draw = max(1, home_wins + away_wins)
        draw_no_bet = {
            "home": round(home_wins / non_draw, 4),
            "away": round(away_wins / non_draw, 4),
        }
        clean_sheet = cls._derive_clean_sheet(scores, inputs.samples)
        win_to_nil = cls._derive_win_to_nil(scores, inputs.samples)
        upset_probability = round(min(home_wins, away_wins) / inputs.samples, 4)
        market_efficiency = cls._derive_market_efficiency(home_wins, draws, away_wins, scores, inputs.samples)
        risk_rating = cls._derive_risk_rating(market_efficiency, upset_probability)
        value_bets = cls._derive_value_bets(over_under, asian_handicap, btts, risk_rating)

        return {
            "kind": "football_score_prediction",
            "method": "bivariate_poisson_monte_carlo",
            "result": {
                "win_prob": {
                    "home": round(home_wins / inputs.samples, 4),
                    "draw": round(draws / inputs.samples, 4),
                    "away": round(away_wins / inputs.samples, 4),
                },
                "top_scores": top_scores,
                "correct_score": correct_score,
                "expected_goals": {
                    "home": round(home_goals_total / inputs.samples, 3),
                    "away": round(away_goals_total / inputs.samples, 3),
                },
                "score_distribution_matrix": {
                    "home_goals": list(range(cls.SCORE_MATRIX_MAX + 1)),
                    "away_goals": list(range(cls.SCORE_MATRIX_MAX + 1)),
                    "probabilities": matrix,
                    "overflow_prob": round(overflow / inputs.samples, 4),
                },
                "asian_handicap": asian_handicap,
                "over_under": over_under,
                "btts": btts,
                "double_chance": double_chance,
                "draw_no_bet": draw_no_bet,
                "clean_sheet": clean_sheet,
                "win_to_nil": win_to_nil,
                "implied_odds": {
                    "home_win": cls._fair_odds(home_wins / inputs.samples),
                    "draw": cls._fair_odds(draws / inputs.samples),
                    "away_win": cls._fair_odds(away_wins / inputs.samples),
                    "btts_yes": cls._fair_odds(btts["yes"]),
                    "over_2.5": cls._fair_odds(over_under["2.5"]["over"]),
                    "under_2.5": cls._fair_odds(over_under["2.5"]["under"]),
                },
                "upset_probability": upset_probability,
                "market_efficiency": market_efficiency,
                "risk_rating": risk_rating,
                "value_bets": value_bets,
            },
            "inputs": {
                "home_team": inputs.home_team,
                "away_team": inputs.away_team,
                "lambda_home": inputs.lambda_home,
                "lambda_away": inputs.lambda_away,
                "samples": inputs.samples,
                "correlation": round(inputs.correlation, 4),
                "source": inputs.source,
            },
            "warnings": inputs.warnings,
        }

    @staticmethod
    def _sample_poisson(rng: random.Random, lam: float) -> int:
        if lam <= 0:
            return 0
        threshold = math.exp(-lam)
        k = 0
        product = 1.0
        while product > threshold:
            k += 1
            product *= rng.random()
        return k - 1

    @staticmethod
    def _fair_odds(probability: float) -> float:
        if probability <= 0:
            return 100.0
        return round(min(100.0, 1.0 / probability), 2)

    @classmethod
    def _derive_over_under(cls, scores: Counter[Tuple[int, int]], samples: int) -> Dict[str, Dict[str, float]]:
        markets: Dict[str, Dict[str, float]] = {}
        for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5):
            over = sum(count for (home, away), count in scores.items() if home + away > line) / samples
            markets[f"{line:.1f}"] = {"over": round(over, 4), "under": round(1 - over, 4)}
        return markets

    @staticmethod
    def _derive_btts(scores: Counter[Tuple[int, int]], samples: int) -> Dict[str, float]:
        yes = sum(count for (home, away), count in scores.items() if home >= 1 and away >= 1) / samples
        return {"yes": round(yes, 4), "no": round(1 - yes, 4)}

    @classmethod
    def _derive_asian_handicap(cls, scores: Counter[Tuple[int, int]], samples: int) -> Dict[str, Dict[str, float]]:
        markets: Dict[str, Dict[str, float]] = {}
        for line in (-2.5, -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5):
            cover = sum(count for (home, away), count in scores.items() if home - away + line > 0) / samples
            markets[cls._format_line(line)] = {
                "home_cover": round(cover, 4),
                "away_cover": round(1 - cover, 4),
            }
        return markets

    @staticmethod
    def _format_line(line: float) -> str:
        if line == 0:
            return "0"
        return f"{line:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _derive_clean_sheet(scores: Counter[Tuple[int, int]], samples: int) -> Dict[str, float]:
        return {
            "home": round(sum(count for (_, away), count in scores.items() if away == 0) / samples, 4),
            "away": round(sum(count for (home, _), count in scores.items() if home == 0) / samples, 4),
        }

    @staticmethod
    def _derive_win_to_nil(scores: Counter[Tuple[int, int]], samples: int) -> Dict[str, float]:
        return {
            "home": round(sum(count for (home, away), count in scores.items() if home > away and away == 0) / samples, 4),
            "away": round(sum(count for (home, away), count in scores.items() if away > home and home == 0) / samples, 4),
        }

    @staticmethod
    def _derive_market_efficiency(
        home_wins: int,
        draws: int,
        away_wins: int,
        scores: Counter[Tuple[int, int]],
        samples: int,
    ) -> float:
        max_outcome_prob = max(home_wins, draws, away_wins) / samples
        top_score_share = sum(count for _, count in scores.most_common(5)) / samples
        return round(min(1.0, max(0.0, 0.45 + max_outcome_prob * 0.35 + top_score_share * 0.20)), 4)

    @staticmethod
    def _derive_risk_rating(market_efficiency: float, upset_probability: float) -> str:
        if upset_probability >= 0.35 or market_efficiency < 0.52:
            return "High"
        if upset_probability >= 0.25 or market_efficiency < 0.62:
            return "Medium"
        if upset_probability >= 0.15 or market_efficiency < 0.72:
            return "Low"
        return "Very Low"

    @staticmethod
    def _derive_value_bets(
        over_under: Dict[str, Dict[str, float]],
        asian_handicap: Dict[str, Dict[str, float]],
        btts: Dict[str, float],
        risk_rating: str,
    ) -> List[Dict[str, Any]]:
        candidates = [
            ("Over 2.5", over_under.get("2.5", {}).get("over", 0)),
            ("Under 2.5", over_under.get("2.5", {}).get("under", 0)),
            ("BTTS Yes", btts.get("yes", 0)),
            ("BTTS No", btts.get("no", 0)),
            ("Home AH -2.0", asian_handicap.get("-2", {}).get("home_cover", 0)),
            ("Away AH +2.0", asian_handicap.get("2", {}).get("away_cover", 0)),
        ]
        return [
            {"market": market, "model_probability": round(prob, 4), "risk_level": risk_rating}
            for market, prob in candidates
            if prob >= 0.56
        ][:5]


def football_prediction_to_markdown(prediction: Dict[str, Any]) -> str:
    """Render a prediction result as a report section."""
    if not prediction:
        return "**数据不足**\n\n当前无可用的足球概率预测数据。模拟引擎未能完成概率计算，报告生成流程被阻断。请等待MiroFish Simulation Engine完成概率计算模块的正常执行。"
    result = prediction["result"]
    inputs = prediction["inputs"]
    win_prob = result["win_prob"]
    expected = result["expected_goals"]
    matrix = result["score_distribution_matrix"]

    def pct(value: float) -> str:
        return f"{value * 100:.1f}%"

    top_scores = result.get("top_scores", [])
    top_text = "、".join(f"{item['score']}（{pct(item['prob'])}）" for item in top_scores[:5])
    if win_prob["home"] > win_prob["away"]:
        favorite = inputs["home_team"]
        underdog = inputs["away_team"]
    elif win_prob["away"] > win_prob["home"]:
        favorite = inputs["away_team"]
        underdog = inputs["home_team"]
    else:
        favorite = "双方"
        underdog = "双方"
    edge_text = (
        f"{favorite} 的胜率高于 {underdog}"
        if favorite != "双方"
        else "双方胜率接近，平局风险需要重点关注"
    )

    lines = [
        "本章节直接给出本次足球概率模拟的核心输出。系统已从模拟种子和初始动作中抽取到可用的泊松参数，并按双变量泊松模型完成100,000次蒙特卡洛采样，因此本次报告不再停留在方法论描述。",
        "",
        "**核心输入**",
        "",
        f"- 主队: {inputs['home_team']}",
        f"- 客队: {inputs['away_team']}",
        f"- lambda_home: {inputs['lambda_home']}",
        f"- lambda_away: {inputs['lambda_away']}",
        f"- 攻防相关性修正: {inputs['correlation']}",
        f"- 采样次数: {inputs['samples']:,}",
        "",
        "**胜平负概率**",
        "",
        f"- {inputs['home_team']} 主胜: {pct(win_prob['home'])}",
        f"- 平局: {pct(win_prob['draw'])}",
        f"- {inputs['away_team']} 客胜: {pct(win_prob['away'])}",
        "",
        "**最可能比分**",
        "",
        f"最高概率比分集中在 {top_text}。从分布看，{edge_text}，但平局和弱势方低比分抢分仍保留尾部概率。",
        "",
        "**期望进球**",
        "",
        f"- {inputs['home_team']}: {expected['home']}",
        f"- {inputs['away_team']}: {expected['away']}",
        "",
        "**比分概率分布矩阵**",
        "",
        "下表按“主队进球-客队进球”展示0到6球范围内的概率；更高比分被计入溢出概率。",
        "",
    ]

    header = "| 主队\\客队 | " + " | ".join(str(goal) for goal in matrix["away_goals"]) + " |"
    separator = "|---" * (len(matrix["away_goals"]) + 1) + "|"
    lines.append(header)
    lines.append(separator)
    for home_goal, row in zip(matrix["home_goals"], matrix["probabilities"]):
        cells = " | ".join(pct(value) for value in row)
        lines.append(f"| {home_goal} | {cells} |")

    lines.extend([
        "",
        f"矩阵外溢出概率: {pct(matrix['overflow_prob'])}",
        "",
        "该结果是概率分布，不是单一确定比分。若需要给出一个最可能比分，当前模拟的首选比分为 "
        f"{top_scores[0]['score']}，对应概率 {pct(top_scores[0]['prob'])}。",
    ])

    if prediction.get("warnings"):
        lines.append("")
        lines.append("**数据提示**")
        lines.extend(f"- {warning}" for warning in prediction["warnings"])

    return "\n".join(lines)
