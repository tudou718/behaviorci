"""experiment.py —— 分布级对比（v0.2 / B）。

单对单比较解决不了的问题：
    两份磁带不一样，是「行为漂移」，还是「模型这次手气不好」？

答案不是再判断一次，而是看分布：
    同一变体跑 N 次 → 组内差异 = 这个 Agent 的天然抖动
    两个变体之间差异 = 天然抖动 + 真实变化

如果组间相似度和组内相似度差不多，说明变化落在噪声范围里；
如果组间明显更低，才是真的漂移。

注意：这里的判定是**启发式**，阈值是经验值。它的价值是把「像不像」
变成可解释的数字，而不是替代裁判。
"""

from __future__ import annotations

import difflib
import json
import statistics
from collections import Counter
from pathlib import Path

try:
    from .tape import final_output_text, load_tape
except ImportError:
    from tape import final_output_text, load_tape

ROOT = Path(__file__).resolve().parent.parent

# 经验阈值：组间相似度比组内低多少，才算「真变了」
DRIFT_STRONG = 0.15
DRIFT_MILD = 0.05


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _pairwise_mean(texts: list[str], other: list[str] | None = None) -> float:
    """两组文本两两比较的平均相似度；other 为空时算组内。"""
    other = texts if other is None else other
    values = []
    for i, a in enumerate(texts):
        start = i + 1 if other is texts else 0
        for b in other[start:]:
            values.append(_similarity(a, b))
    return statistics.mean(values) if values else 0.0


def _sequence(tools: list[str]) -> str:
    return " → ".join(tools)


def _metrics(tapes: list[dict]) -> dict:
    steps = [len(t["steps"]) for t in tapes]
    durations = [t["meta"].get("duration_ms", 0) for t in tapes]
    finals = [final_output_text(t) for t in tapes]
    sequences = Counter(_sequence([s["name"] for s in t["steps"]]) for t in tapes)

    return {
        "n": len(tapes),
        "steps_mean": statistics.mean(steps),
        "steps_std": statistics.pstdev(steps) if len(steps) > 1 else 0.0,
        "duration_mean": statistics.mean(durations),
        "duration_std": statistics.pstdev(durations) if len(durations) > 1 else 0.0,
        "output_chars_mean": statistics.mean(len(x) for x in finals),
        "within_similarity": round(_pairwise_mean(finals), 3) if len(finals) > 1 else None,
        "tool_sequences": dict(sequences),
        "finals": finals,
    }


def compare_groups(group_a: list[dict], group_b: list[dict]) -> dict:
    """比较两个变体组，返回结构化结论。"""
    a = _metrics(group_a)
    b = _metrics(group_b)
    cross = round(_pairwise_mean(a["finals"], b["finals"]), 3)

    # 结构层：工具集合 / 序列 / 步骤数
    tools_a = {s["name"] for t in group_a for s in t["steps"]}
    tools_b = {s["name"] for t in group_b for s in t["steps"]}
    structural = {
        "tools_added": sorted(tools_b - tools_a),
        "tools_removed": sorted(tools_a - tools_b),
        "step_gap": round(abs(a["steps_mean"] - b["steps_mean"]), 2),
        "same_sequence_mode": set(a["tool_sequences"]) == set(b["tool_sequences"]),
    }
    structure_changed = bool(
        structural["tools_added"]
        or structural["tools_removed"]
        or structural["step_gap"] >= 1
        or not structural["same_sequence_mode"]
    )

    # 语义层：组间 vs 基线组内。
    # 噪声线必须取「基线自己的抖动」，不能取两组平均——
    # 候选组如果本身就不稳定（组内相似度低），平均会把真实差异稀释掉。
    within_ref = (
        a["within_similarity"]
        if a["within_similarity"] is not None
        else b["within_similarity"]
    )
    delta = round(within_ref - cross, 3) if within_ref is not None else None
    stability_gap = (
        round(a["within_similarity"] - b["within_similarity"], 3)
        if a["within_similarity"] is not None and b["within_similarity"] is not None
        else None
    )

    if delta is None:
        level = "样本不足"
    elif delta >= DRIFT_STRONG:
        level = "明显漂移"
    elif delta >= DRIFT_MILD:
        level = "轻微差异"
    else:
        level = "未见漂移"

    return {
        "baseline": a,
        "candidate": b,
        "cross_similarity": cross,
        "within_baseline": a["within_similarity"],
        "within_candidate": b["within_similarity"],
        "within_ref": within_ref,
        "delta": delta,
        "stability_gap": stability_gap,
        "structural": structural,
        "structure_changed": structure_changed,
        "level": level,
        "thresholds": {"strong": DRIFT_STRONG, "mild": DRIFT_MILD},
    }


def load_groups(task_name: str, tapes_dir: Path | None = None) -> dict[str, list[dict]]:
    """按变体分组读取某个任务的全部磁带。"""
    directory = Path(tapes_dir) if tapes_dir else ROOT / "tapes"
    # 实验磁带放在 tapes/experiments/，与会被 CI 当作基线的 tapes/*.json 分开
    paths = sorted(directory.glob("*.json")) + sorted(
        (directory / "experiments").glob("*.json")
    )
    groups: dict[str, list[dict]] = {}
    for path in paths:
        tape = load_tape(path)
        if tape.get("task", {}).get("name") != task_name:
            continue
        variant = tape["meta"].get("variant") or "unlabeled"
        groups.setdefault(variant, []).append(tape)
    return groups


def render(result: dict, baseline: str, candidate: str) -> str:
    a, b = result["baseline"], result["candidate"]
    lines = []
    lines.append("=" * 64)
    lines.append(f"分布对比：{baseline}（{a['n']} 次） vs {candidate}（{b['n']} 次）")
    lines.append("=" * 64)
    lines.append("")

    def fmt(value, unit=""):
        return f"{value:.1f}{unit}" if isinstance(value, (int, float)) else "—"

    rows = [
        ("运行次数", str(a["n"]), str(b["n"])),
        (
            "步骤数",
            f"{a['steps_mean']:.1f} ± {a['steps_std']:.1f}",
            f"{b['steps_mean']:.1f} ± {b['steps_std']:.1f}",
        ),
        (
            "耗时",
            f"{fmt(a['duration_mean'] / 1000)}s ± {fmt(a['duration_std'] / 1000)}s",
            f"{fmt(b['duration_mean'] / 1000)}s ± {fmt(b['duration_std'] / 1000)}s",
        ),
        (
            "交付物长度",
            f"{a['output_chars_mean']:.0f} 字",
            f"{b['output_chars_mean']:.0f} 字",
        ),
        (
            "组内相似度",
            f"{a['within_similarity']:.2f}" if a["within_similarity"] is not None else "—（样本 < 2）",
            f"{b['within_similarity']:.2f}" if b["within_similarity"] is not None else "—（样本 < 2）",
        ),
    ]
    width = 12
    print_header = f"{'指标':<{width}}{baseline:<22}{candidate:<22}"
    lines.append(print_header)
    for name, left, right in rows:
        lines.append(f"{name:<{width}}{left:<22}{right:<22}")

    lines.append("")
    lines.append(
        f"组间相似度：{result['cross_similarity']:.2f}"
        f"    基线噪声线：{result['within_ref'] if result['within_ref'] is not None else '—'}"
        f"    差值：{result['delta'] if result['delta'] is not None else '—'}"
    )
    if result.get("stability_gap") is not None and result["stability_gap"] >= 0.2:
        lines.append(
            f"⚠ 候选组自身不稳定（组内 {result['within_candidate']:.2f}，"
            f"基线 {result['within_baseline']:.2f}）——即使不谈漂移，这个变体也值得看一下"
        )
    lines.append("")

    structural = result["structural"]
    lines.append("结构层")
    if result["structure_changed"]:
        if structural["tools_added"]:
            lines.append(f"  · 新增工具：{'、'.join(structural['tools_added'])}")
        if structural["tools_removed"]:
            lines.append(f"  · 移除工具：{'、'.join(structural['tools_removed'])}")
        if structural["step_gap"] >= 1:
            lines.append(f"  · 步骤数差异：{structural['step_gap']:.1f}")
        if not structural["same_sequence_mode"]:
            lines.append("  · 主导工具序列不同")
    else:
        lines.append("  ✓ 工具集合、步骤数、主导序列均一致")
    lines.append("")

    lines.append(f"结论：{result['level']}")
    lines.append(
        "说明：基线组内相似度代表这个 Agent 的天然抖动（噪声线）；"
        f"组间相似度比噪声线低 {result['delta'] if result['delta'] is not None else '—'}，"
        "差值越大越可能是真实变化。"
    )
    lines.append("阈值（经验值）：≥0.15 明显漂移，≥0.05 轻微差异，<0.05 未见漂移。")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="按变体统计分布，判断漂移还是抖动")
    parser.add_argument("--task", required=True, help="任务名，例如 daily-brief")
    parser.add_argument("--baseline", required=True, help="基线变体名")
    parser.add_argument("--candidate", required=True, help="候选变体名")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    groups = load_groups(args.task)
    missing = [v for v in (args.baseline, args.candidate) if v not in groups]
    if missing:
        raise SystemExit(
            f"找不到变体：{', '.join(missing)}。现有变体：{', '.join(groups) or '无'}"
        )

    result = compare_groups(groups[args.baseline], groups[args.candidate])
    if args.json:
        payload = {
            k: v for k, v in result.items() if k not in ("baseline", "candidate")
        }
        payload["baseline"] = {
            k: v for k, v in result["baseline"].items() if k != "finals"
        }
        payload["candidate"] = {
            k: v for k, v in result["candidate"].items() if k != "finals"
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(result, args.baseline, args.candidate))


if __name__ == "__main__":
    main()