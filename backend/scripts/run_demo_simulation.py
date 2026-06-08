"""
Lightweight live-demo simulation runner.

This runner preserves the Foresight UI/API contract when the local OASIS stack is
blocked by Torch/CAMEL binary compatibility. It writes the same actions.jsonl
shape that SimulationRunner already monitors, but it does not import OASIS,
Torch, CAMEL, or GPU-backed libraries.
"""

import argparse
import json
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List


ACTION_LIBRARY = [
    {
        "action_type": "CREATE_POST",
        "template": "{name} 发布观察：AI 算力扩张正在把电力容量、液冷组件和园区配套变成新增投资的约束条件。",
    },
    {
        "action_type": "CREATE_COMMENT",
        "template": "{name} 评论：下一步要看订单兑现、授信需求和现金流压力是否同步出现。",
    },
    {
        "action_type": "LIKE_POST",
        "template": "{name} 赞同了关于绿色信贷和设备更新贷款的讨论。",
    },
    {
        "action_type": "CREATE_COMMENT",
        "template": "{name} 提醒：变量推演不是预测，关键是把客户拜访问题提前准备好。",
    },
]


def write_jsonl(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        f.flush()


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_agents(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    agents = config.get("agent_configs") or []
    if agents:
        return agents
    return [
        {"agent_id": 0, "entity_name": "AI 数据中心", "entity_type": "DataCenterOperator"},
        {"agent_id": 1, "entity_name": "制造企业", "entity_type": "ManufacturingCompany"},
        {"agent_id": 2, "entity_name": "银行客户经理", "entity_type": "BankRelationshipManager"},
    ]


def platforms_from_arg(platform: str) -> List[str]:
    if platform == "parallel":
        return ["twitter", "reddit"]
    if platform in {"twitter", "reddit"}:
        return [platform]
    return ["reddit"]


def reset_logs(simulation_dir: str, platforms: List[str]) -> Dict[str, str]:
    log_paths = {}
    for platform in platforms:
        platform_dir = os.path.join(simulation_dir, platform)
        os.makedirs(platform_dir, exist_ok=True)
        log_path = os.path.join(platform_dir, "actions.jsonl")
        with open(log_path, "w", encoding="utf-8"):
            pass
        log_paths[platform] = log_path
    return log_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--platform", default="reddit")
    parser.add_argument("--tick-seconds", type=float, default=0.45)
    args = parser.parse_args()

    config = load_config(args.config)
    simulation_dir = os.path.dirname(os.path.abspath(args.config))
    platforms = platforms_from_arg(args.platform)
    log_paths = reset_logs(simulation_dir, platforms)

    time_config = config.get("time_config", {})
    total_hours = int(time_config.get("total_simulation_hours", 72))
    minutes_per_round = int(time_config.get("minutes_per_round", 60)) or 60
    calculated_rounds = max(1, int(total_hours * 60 / minutes_per_round))
    total_rounds = min(calculated_rounds, args.max_rounds) if args.max_rounds else calculated_rounds
    agents = get_agents(config)

    print(f"[demo-runner] start simulation={config.get('simulation_id')} platforms={platforms} rounds={total_rounds}", flush=True)

    for platform, log_path in log_paths.items():
        write_jsonl(log_path, {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_start",
            "platform": platform,
            "total_rounds": total_rounds,
            "agents_count": len(agents),
        })

    random.seed(config.get("simulation_id", "foresight-demo"))
    total_actions = {platform: 0 for platform in platforms}

    for round_num in range(1, total_rounds + 1):
        simulated_hours = round_num * minutes_per_round // 60
        for platform, log_path in log_paths.items():
            write_jsonl(log_path, {
                "round": round_num,
                "timestamp": datetime.now().isoformat(),
                "event_type": "round_start",
                "simulated_hours": simulated_hours,
            })

            sample_size = min(len(agents), 3)
            selected_agents = random.sample(agents, sample_size)
            for agent in selected_agents:
                action = random.choice(ACTION_LIBRARY)
                name = agent.get("entity_name") or agent.get("name") or f"Agent {agent.get('agent_id', 0)}"
                result = action["template"].format(name=name)
                write_jsonl(log_path, {
                    "round": round_num,
                    "timestamp": datetime.now().isoformat(),
                    "agent_id": agent.get("agent_id", 0),
                    "agent_name": name,
                    "action_type": action["action_type"],
                    "action_args": {
                        "platform": platform,
                        "topic": config.get("simulation_requirement", "")[:80],
                    },
                    "result": result,
                    "success": True,
                })
                total_actions[platform] += 1

            write_jsonl(log_path, {
                "round": round_num,
                "timestamp": datetime.now().isoformat(),
                "event_type": "round_end",
                "actions_count": total_actions[platform],
                "simulated_hours": simulated_hours,
            })

        time.sleep(args.tick_seconds)

    for platform, log_path in log_paths.items():
        write_jsonl(log_path, {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_end",
            "platform": platform,
            "total_rounds": total_rounds,
            "total_actions": total_actions[platform],
        })

    print(f"[demo-runner] completed actions={total_actions}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
