"""diff.py —— 对比器：结构层对数 + 语义层裁决（D5 打底，D6 接裁判）。

前半段是「笨办法」，只回答三个「骨架问题」：

    1. 步骤数一样吗？
    2. 工具调用的顺序一样吗？
    3. 最终输出都有东西吗（不是空的）？

这三项都很笨——它们看得懂结构，看不懂内容。所以它们能告诉你
「两份磁带的骨架对不上」，但永远说不出「这个变化是好是坏」。
那是第 6 天请裁判（LLM-as-Judge）的活。

后半段是「聪明办法」：结构对完账、内容也确实有变化时，把两份磁带交给
judge.judge()，由模型给出「等价 / 变好 / 漂移」+ 人话理由。

两者分工明确：
    结构对比 —— 保证骨架没塌（步骤、顺序、交没交货），纯本地，不花钱
    裁判     —— 读内容，判断好坏，要调模型

用法：
    python src/diff.py tapes/a.json tapes/b.json
    python src/diff.py tapes/a.json tapes/b.json --no-judge   # 只看结构，不调模型
    python src/diff.py tapes/a.json tapes/b.json --json
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

try:
    from . import judge as judge_mod
    from .tape import final_output_text, load_tape, walk_diff
except ImportError:
    import judge as judge_mod
    from tape import final_output_text, load_tape, walk_diff

# ---------------------------------------------------------------------------
# 三项结构对比
# ---------------------------------------------------------------------------

def check_step_count(tape_a: dict, tape_b: dict) -> dict:
    """步骤数一样吗？"""
    a, b = len(tape_a["steps"]), len(tape_b["steps"])
    return {
        "name": "step_count",
        "label": "步骤数",
        "consistent": a == b,
        "baseline": a,
        "candidate": b,
        "detail": f"{a} = {b}" if a == b else f"{a} ≠ {b}",
    }


def check_tool_sequence(tape_a: dict, tape_b: dict) -> dict:
    """调用的工具、以及它们的先后顺序，一样吗？"""
    a = [s["name"] for s in tape_a["steps"]]
    b = [s["name"] for s in tape_b["steps"]]
    same = a == b
    return {
        "name": "tool_sequence",
        "label": "工具调用序列",
        "consistent": same,
        "baseline": a,
        "candidate": b,
        "detail": " → ".join(a) if same else f"{' → '.join(a)}  ≠  {' → '.join(b)}",
    }


def check_final_output(tape_a: dict, tape_b: dict) -> dict:
    """最终输出都有东西吗？

    注意这里只查「有没有」，不查「一不一样」——一样不一样是内容层的事，
    骨架层只看交没交货。
    """
    a, b = final_output_text(tape_a), final_output_text(tape_b)
    both = bool(a.strip()) and bool(b.strip())
    return {
        "name": "final_output_nonempty",
        "label": "最终输出非空",
        "consistent": both,
        "baseline": len(a),
        "candidate": len(b),
        "detail": f"{len(a)} 字 / {len(b)} 字" if both else "有一边没交出东西",
    }


# ---------------------------------------------------------------------------
# 内容清点：给第 6 天的裁判准备卷子
# ---------------------------------------------------------------------------

def content_changes(tape_a: dict, tape_b: dict) -> dict:
    """清点哪些步骤的输出变了，并区分「源头」和「上游传染」。

    判定方法很朴素：
        某一步的输入差异，如果跟它上一步的输出差异完全一致，那它的输入
        变化就是从上游流下来的，它自己没改行为——叫「传染」。
        反过来，输入没变（或是新出现的差异）而输出变了，它就是源头。
    """
    steps_a, steps_b = tape_a["steps"], tape_b["steps"]
    changed, roots = [], []

    for i in range(min(len(steps_a), len(steps_b))):
        old, new = steps_a[i], steps_b[i]
        out_diffs = walk_diff(old["output"], new["output"])
        if not out_diffs:
            continue

        in_diffs = walk_diff(old["input"], new["input"])
        inherited = (
            i > 0
            and in_diffs
            and in_diffs == walk_diff(steps_a[i - 1]["output"], steps_b[i - 1]["output"])
        )

        item = {
            "index": i + 1,
            "name": old["name"],
            "label": old["label"],
            "diff_count": len(out_diffs),
            "inherited_input": inherited,
        }
        changed.append(item)
        if not inherited:
            roots.append(item)

    return {
        "changed_steps": changed,
        "root_steps": roots,
        "final_output_changed": walk_diff(
            tape_a.get("output", {}), tape_b.get("output", {})
        )
        != [],
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def compare(
    tape_a: dict, tape_b: dict, use_judge: bool = True, judge_runs: int = 3
) -> dict:
    """跑完一次完整对比：先结构对数，有内容差异再请裁判。"""
    checks = [
        check_step_count(tape_a, tape_b),
        check_tool_sequence(tape_a, tape_b),
        check_final_output(tape_a, tape_b),
    ]
    consistent = sum(1 for c in checks if c["consistent"])
    content = content_changes(tape_a, tape_b)

    # 内容没变就不必花钱问裁判；变了才把卷子递过去
    has_content_change = bool(content["changed_steps"]) or content["final_output_changed"]
    if not has_content_change:
        verdict = judge_mod.skipped()
    elif not use_judge:
        verdict = judge_mod.skipped("已跳过裁判（--no-judge）")
    else:
        try:
            # 不是判一次就算数：跑 3 次取多数，把分歧也记下来
            verdict = judge_mod.judge_consensus(tape_a, tape_b, runs=judge_runs)
        except Exception as exc:  # 裁判挂了不该把结构报告一起毁掉
            verdict = {
                "verdict": None,
                "reason": f"裁判调用失败：{exc}",
                "error": str(exc),
            }

    return {
        "task": tape_a.get("task", {}).get("name"),
        "baseline": {
            "run_id": tape_a["meta"]["run_id"],
            "variant": _variant(tape_a),
            "model": tape_a["meta"].get("model"),
        },
        "candidate": {
            "run_id": tape_b["meta"]["run_id"],
            "variant": _variant(tape_b),
            "model": tape_b["meta"].get("model"),
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "consistent": consistent,
            "different": len(checks) - consistent,
        },
        "content": content,
        # 好坏不是笨办法能判的，这一段来自 judge.py
        "verdict": verdict,
    }


def _display_width(text: str) -> int:
    """中文在终端占两个字符宽，算对宽度才能对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _variant(tape: dict) -> str:
    return tape["meta"].get("variant") or tape["meta"]["run_id"]


def print_report(report: dict) -> None:
    print("\n" + "=" * 70)
    print(f"对比：{report['baseline']['variant']}  vs  {report['candidate']['variant']}")
    print("=" * 70)
    print(f"任务：{report['task']}    模型：{report['baseline']['model']}")

    print("\n结构对比")
    for i, c in enumerate(report["checks"], 1):
        mark = "✓ 一致" if c["consistent"] else "✗ 不同"
        print(f"  {i}. {_pad(c['label'], 14)} {mark}   {c['detail']}")

    s = report["summary"]
    print(f"\n结论：{s['total']} 项对比，{s['consistent']} 项一致，{s['different']} 项不同")

    content = report["content"]
    print("\n内容清点（不计入上面的结构对比，是裁判的附件）")
    if not content["changed_steps"]:
        print("  两步之间内容完全一致，裁判这次没活干。")
    else:
        root_names = {r["name"] for r in content["root_steps"]}
        for item in content["changed_steps"]:
            tag = "← 源头" if item["name"] in root_names else "（输入来自上游，输出跟着变）"
            print(f"  #{item['index']} {item['label']}：输出 {item['diff_count']} 处不同  {tag}")
        if content["final_output_changed"]:
            print("  最终交付物也变了。")

    print("\n注意：结构一致 ≠ 行为等价。骨架一模一样、内容却变了，是最常见的情况——")
    print("      这正是笨办法的天花板，所以要请裁判来读内容。\n")

    print_verdict(report["verdict"])


def print_verdict(verdict: dict) -> None:
    """打印裁判的结论。"""
    model = verdict.get("model") or "—"
    print("=" * 70)
    print(f"裁判（LLM-as-Judge / {model}）")
    print("=" * 70)

    if verdict.get("skipped"):
        print(f"  跳过：{verdict['reason']}")
        return

    if verdict.get("verdict") is None:
        print(f"  ✗ {verdict['reason']}")
        if any(k in verdict["reason"] for k in ("401", "Authentication", "token")):
            print("  提示：401 表示 Key 没被网关认可（失效、被回收或换过），不是代码问题。")
            print("        去网关后台确认 Key 仍有效，或换新 Key 写进 .env 的 LLM_API_KEY。")
        return

    print(f"  结论：{verdict['verdict']}（{verdict['agreement']}）")
    print(f"  理由：{verdict['reason']}")

    counts = verdict.get("counts") or {}
    tally = " / ".join(f"{v} ×{n}" for v, n in counts.items())
    print(f"  票型：{tally}    耗时：{verdict['elapsed_ms']}ms")
    if verdict.get("failures"):
        print(f"  跳过了 {len(verdict['failures'])} 次失败的调用")

    if not verdict.get("unanimous", True):
        print("\n  分歧记录（裁判自己也没底，这正是分布校验要暴露的东西）：")
        for run in verdict["runs"]:
            print(f"    第 {run['index']} 次 → {run['verdict']}：{run['reason']}")
    else:
        print(f"  {verdict.get('runs_succeeded', 0)} 次判断完全一致，结论稳定。")


def main() -> None:
    parser = argparse.ArgumentParser(description="对比两份行为磁带（结构层，笨办法）")
    parser.add_argument("tape_a", help="基线磁带路径")
    parser.add_argument("tape_b", help="候选磁带路径")
    parser.add_argument("--json", action="store_true", help="输出机读的 JSON 结论")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="只做结构对比，不调模型裁决",
    )
    parser.add_argument(
        "--judge-runs",
        type=int,
        default=3,
        help="裁判跑几次取多数（默认 3）",
    )
    args = parser.parse_args()

    tape_a, tape_b = load_tape(args.tape_a), load_tape(args.tape_b)

    if tape_a.get("task", {}).get("name") != tape_b.get("task", {}).get("name"):
        raise SystemExit("两份磁带的任务名不一样，比不了（它们不是同一道考题）")

    report = compare(
        tape_a, tape_b, use_judge=not args.no_judge, judge_runs=args.judge_runs
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()