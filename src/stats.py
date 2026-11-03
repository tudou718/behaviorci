"""stats.py —— 项目实测统计（D13）。

回答三个问题：
    1. 一共录了多少份磁带、跑了多少次对比？
    2. 裁判都怎么判的？票型分布如何（有没有出现 2:1 这种分歧）？
    3. 花了多少 token / 多少钱？

数据来源都是本地真实产物：
    tapes/*.json            行为磁带（基线）
    tapes/examples/*.json   案例磁带（如故意漂移的样本）
    reports/*.json          compare 生成的报告
    reports/usage.jsonl     llm.ask 记录的 token 流水

注意：usage 流水是后加的计量，之前的调用没有记录。所以统计里会标出
「计量区间」，不把旧数据算成 0，也不假装知道。
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USAGE_LOG = ROOT / "reports" / "usage.jsonl"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def collect() -> dict:
    base_tapes = [
        tape
        for tape in map(_load_json, sorted(ROOT.glob("tapes/*.json")))
        if tape
    ]
    example_tapes = [
        t for t in (map(_load_json, sorted(ROOT.glob("tapes/examples/*.json")))) if t
    ]

    reports = []
    for path in sorted(ROOT.glob("reports/*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        report = payload.get("report")
        if isinstance(report, dict) and "verdict" in report:
            reports.append(report)

    usage = []
    if USAGE_LOG.exists():
        for line in USAGE_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                usage.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    all_tapes = base_tapes + example_tapes
    verdicts = Counter()
    agreements = Counter()
    judge_votes = 0
    for report in reports:
        verdict = report.get("verdict") or {}
        if verdict.get("skipped"):
            verdicts["未裁决"] += 1
            continue
        if verdict.get("verdict") is None:
            verdicts["裁决失败"] += 1
            continue
        verdicts[verdict["verdict"]] += 1
        agreements[verdict.get("agreement", "?")] += 1
        judge_votes += len(verdict.get("runs") or [])

    tokens_by_purpose: Counter = Counter()
    prompt_tokens = completion_tokens = total_tokens = 0
    for item in usage:
        purpose = item.get("purpose", "generic")
        tokens_by_purpose[purpose] += item.get("total_tokens", 0)
        prompt_tokens += item.get("prompt_tokens", 0)
        completion_tokens += item.get("completion_tokens", 0)
        total_tokens += item.get("total_tokens", 0)

    price_in = float(os.getenv("LLM_PRICE_INPUT", "0") or 0)  # 元 / 百万 token
    price_out = float(os.getenv("LLM_PRICE_OUTPUT", "0") or 0)
    cost = None
    if price_in or price_out:
        cost = prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out

    return {
        "tapes": {
            "baseline": len(base_tapes),
            "examples": len(example_tapes),
            "steps": sum(len(t.get("steps", [])) for t in all_tapes),
            "by_task": dict(Counter(t["task"]["name"] for t in all_tapes)),
            "by_model": dict(
                Counter(t["meta"].get("model") or "unknown" for t in all_tapes)
            ),
        },
        "comparisons": {
            "total": len(reports),
            "verdicts": dict(verdicts),
            "agreements": dict(agreements),
            "judge_votes": judge_votes,
        },
        "usage": {
            "calls": len(usage),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "by_purpose": dict(tokens_by_purpose),
            "cost": cost,
            "currency": "CNY",
            "priced": bool(price_in or price_out),
            "since": usage[0]["at"] if usage else None,
        },
    }


def render(stats: dict) -> str:
    tapes = stats["tapes"]
    comp = stats["comparisons"]
    usage = stats["usage"]
    lines = []

    lines.append("=" * 62)
    lines.append("BehaviorCI 实测统计")
    lines.append("=" * 62)
    lines.append("")
    lines.append(
        f"磁带        {tapes['baseline']} 份基线 + {tapes['examples']} 份案例，"
        f"共 {tapes['steps']} 步记录"
    )
    tasks = " / ".join(f"{k} ×{v}" for k, v in tapes["by_task"].items())
    lines.append(f"任务        {tasks}")
    models = " / ".join(f"{k} ×{v}" for k, v in tapes["by_model"].items())
    lines.append(f"模型        {models}")
    lines.append("")

    lines.append(f"对比报告    {comp['total']} 次")
    if comp["verdicts"]:
        verdicts = " · ".join(f"{k} {v}" for k, v in comp["verdicts"].items())
        lines.append(f"判定分布    {verdicts}")
    if comp["agreements"]:
        agreements = " · ".join(f"{k} ×{v}" for k, v in comp["agreements"].items())
        lines.append(f"裁判票型    {agreements}（累计 {comp['judge_votes']} 次有效判断）")
    lines.append("")

    if usage["calls"]:
        lines.append(
            f"Token 用量  {usage['total_tokens']:,}"
            f"（输入 {usage['prompt_tokens']:,} / 输出 {usage['completion_tokens']:,}，"
            f"{usage['calls']} 次调用）"
        )
        by_purpose = " · ".join(
            f"{k} {v:,}" for k, v in usage["by_purpose"].items()
        )
        lines.append(f"  按用途    {by_purpose}")
        if usage["priced"]:
            lines.append(f"费用        约 ¥{usage['cost']:.2f}")
        else:
            lines.append(
                "费用        未配置单价（设置 LLM_PRICE_INPUT / LLM_PRICE_OUTPUT，"
                "单位：元/百万 token）"
            )
        lines.append(f"计量区间    {usage['since']} 起（此前调用未计量）")
    else:
        lines.append("Token 用量  暂无记录（跑一次 compare 后会开始计量）")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="统计 BehaviorCI 的真实运行数据")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    stats = collect()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(render(stats))


if __name__ == "__main__":
    main()