#!/usr/bin/env python3
"""main.py —— BehaviorCI 统一入口（D8）。

以前每个环节一把工具，今天串成一条命令：

    python main.py record                  # 录：跑一次任务，存一份磁带
    python main.py replay --runs 2         # 放：同一任务再跑两次，并排看
    python main.py compare A.json B.json   # 比：结构对比 + 裁判 + 出报告

三个子命令对应三个动作，各自还能单跑——这样出问题时能只重跑坏掉的那一段，
不用把整条链路重来（这也是 CI 里省时间的关键）。

报告默认写到 reports/：一份 .md 给人看，一份 .json 给 CI 看。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# src/ 里的模块互相以扁平名字导入（diff / judge / replay ...），
# 所以把 src 加进搜索路径，入口就能像脚本一样直接用它们。
sys.path.insert(0, str(ROOT / "src"))

import demo_agent  # noqa: E402
import diff  # noqa: E402
import replay  # noqa: E402
from report import save  # noqa: E402

DEFAULT_TASK = ROOT / "tasks" / "daily_brief.json"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# record：录一份磁带
# ---------------------------------------------------------------------------

def cmd_record(args: argparse.Namespace) -> int:
    task = replay.load_task(Path(args.task))
    topic = task["input"]["topic"]

    print(f"任务：{task['name']}    主题：{topic}")
    result = demo_agent.run(topic, record=True, variant=args.label)

    tape = Path(result["tape"])
    print(f"\n✓ 磁带：{_rel(tape)}")
    print(f"  摘要：{result['summary'][:60]}…")
    return 0


# ---------------------------------------------------------------------------
# replay：同一任务跑多次
# ---------------------------------------------------------------------------

def cmd_replay(args: argparse.Namespace) -> int:
    task = replay.load_task(Path(args.task))
    labels = [s.strip() for s in args.labels.split(",")] if args.labels else None

    records = replay.replay(task, runs=args.runs, labels=labels)
    replay.print_overview(records)

    ok = [r for r in records if r["ok"]]
    if len(ok) >= 2:
        replay.print_step_diff(
            replay.load_tape(ok[0]["tape"]), replay.load_tape(ok[-1]["tape"])
        )
    return 0 if all(r["ok"] for r in records) else 1


# ---------------------------------------------------------------------------
# compare：对比 + 裁判 + 报告
# ---------------------------------------------------------------------------

def cmd_compare(args: argparse.Namespace) -> int:
    tape_a = replay.load_tape(args.tape_a)
    tape_b = replay.load_tape(args.tape_b)

    if tape_a.get("task", {}).get("name") != tape_b.get("task", {}).get("name"):
        print("两份磁带的任务名不一样，比不了（它们不是同一道考题）", file=sys.stderr)
        return 2

    report = diff.compare(
        tape_a,
        tape_b,
        use_judge=not args.no_judge,
        judge_runs=args.judge_runs,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        diff.print_report(report)

    if not args.no_save:
        md_path, json_path = save(report, tape_a, tape_b)
        print(f"\n报告已保存：{_rel(md_path)}")
        print(f"            {_rel(json_path)}")

    if args.fail_on_drift and report["verdict"].get("verdict") == "漂移":
        return 1
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="BehaviorCI：Agent 行为回归（录 → 放 → 比 → 报告）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="录一份磁带（跑一次任务）")
    p_record.add_argument("--task", default=str(DEFAULT_TASK), help="任务定义 JSON")
    p_record.add_argument("--label", help="变体名，写进磁带（如 baseline）")
    p_record.set_defaults(func=cmd_record)

    p_replay = sub.add_parser("replay", help="同一任务跑多次，生成多份磁带")
    p_replay.add_argument("--task", default=str(DEFAULT_TASK), help="任务定义 JSON")
    p_replay.add_argument("--runs", type=int, default=2, help="运行次数（默认 2）")
    p_replay.add_argument(
        "--labels", help="逗号分隔的变体名，如 baseline,new-prompt"
    )
    p_replay.set_defaults(func=cmd_replay)

    p_compare = sub.add_parser("compare", help="对比两份磁带，出判定和报告")
    p_compare.add_argument("tape_a", help="基线磁带")
    p_compare.add_argument("tape_b", help="候选磁带")
    p_compare.add_argument("--judge-runs", type=int, default=3, help="裁判跑几次（默认 3）")
    p_compare.add_argument("--no-judge", action="store_true", help="只做结构对比")
    p_compare.add_argument("--no-save", action="store_true", help="不写 reports/")
    p_compare.add_argument("--json", action="store_true", help="只输出 JSON")
    p_compare.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="判定为漂移时以退出码 1 结束（CI 用）",
    )
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())