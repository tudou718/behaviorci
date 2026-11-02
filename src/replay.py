"""replay.py —— 重放（D4）：同一个任务，再考一次。

这里的「重放」不是把录音倒回去播一遍，而是**重新跑一遍**：
相同的任务定义、相同的输入、相同的代码，让 Agent 再走一次。

为什么不做「回放录音」？
    回放录音你会得到一模一样的结果，那什么都学不到。BehaviorCI 要观察的是
    不确定性：同一个输入，Agent 会不会走出不同的路。所以真正有意义的
    「重放」= 用同样的条件重新考一次，然后看两次答案差多少。

用法：
    # 跑 2 次，自动标成 v1 / v2
    python src/replay.py

    # 跑 3 次
    python src/replay.py --runs 3

    # 用别的任务定义
    python src/replay.py tasks/daily_brief.json

    # 自己指定变体名（比如改 Prompt 前后的对照）
    python src/replay.py --labels baseline,new-prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from . import demo_agent
    from .tape import load_tape, walk_diff
except ImportError:
    import demo_agent
    from tape import load_tape, walk_diff

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASK = ROOT / "tasks" / "daily_brief.json"


# ---------------------------------------------------------------------------
# 任务定义
# ---------------------------------------------------------------------------

def load_task(path: Path) -> dict:
    """读任务定义 JSON，并检查必需字段。

    任务定义和磁带分开存，是因为它是「考题」，磁带的「答卷」：
    同一道考卷可以考很多次，比的是答卷。
    """
    if not path.exists():
        raise SystemExit(f"找不到任务定义：{path}")
    task = json.loads(path.read_text(encoding="utf-8"))

    if not task.get("name"):
        raise SystemExit(f"任务定义缺少 name 字段：{path}")
    topic = (task.get("input") or {}).get("topic")
    if not topic:
        raise SystemExit(f"任务定义缺少 input.topic：{path}")
    return task


# ---------------------------------------------------------------------------
# 重放
# ---------------------------------------------------------------------------

def replay(task: dict, runs: int = 2, labels: list[str] | None = None) -> list[dict]:
    """把同一个任务跑 runs 次，每次录一份磁带，返回每次的结果摘要。"""
    topic = task["input"]["topic"]
    labels = labels or [f"v{i}" for i in range(1, runs + 1)]
    if len(labels) != runs:
        raise SystemExit(f"labels 数量是 {len(labels)}，但 runs 是 {runs}，对不上")

    print(f"任务：{task['name']}  主题：{topic}  共 {runs} 次\n")

    records = []
    for i, label in enumerate(labels, start=1):
        print(f"[{i}/{runs}] 运行 {label} ...", file=sys.stderr)
        try:
            result = demo_agent.run(topic, record=True, variant=label)
        except Exception as exc:
            # 一次跑崩不该毁掉整批；记下来，继续跑下一次
            print(f"      ✗ 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            records.append({"variant": label, "ok": False, "error": str(exc)})
            continue

        tape_path = Path(result["tape"])
        tape = json.loads(tape_path.read_text(encoding="utf-8"))
        records.append(
            {
                "variant": label,
                "ok": True,
                "tape": tape_path,
                "duration_ms": tape["meta"]["duration_ms"],
                "keywords": result["keywords"],
                "summary": result["summary"],
            }
        )
    return records


# ---------------------------------------------------------------------------
# 并排查看：这一步只负责「让你看见差异」，不做任何判断
# ---------------------------------------------------------------------------


def _render(value: object, limit: int = 80) -> str:
    """把任意值压成一行可读文本；太长的截断加省略号。"""
    if isinstance(value, str):
        text = value
    elif value is None:
        return "（无）"
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字）"


def _print_value_block(title: str, value: str, indent: str = "     ") -> None:
    """长文本（比如摘要）单独成段打印，比塞进一行好读。"""
    import textwrap

    print(f"{indent}{title}：")
    for line in textwrap.wrap(value, width=72) or [""]:
        print(f"{indent}  {line}")


def _print_step_changes(old: dict, new: dict, max_lines: int = 5) -> None:
    """打印一个步骤内部的字段级差异；条数太多时只列前几条。"""
    diffs = walk_diff(old, new)
    for path, before, after in diffs[:max_lines]:
        # 摘要这种长文本给全，便于人直接读
        if isinstance(before, str) and isinstance(after, str) and max(
            len(before), len(after)
        ) > 120:
            _print_value_block("v1", before)
            _print_value_block("v2", after)
        else:
            print(f"     {path}:  {_render(before)}  →  {_render(after)}")
    if len(diffs) > max_lines:
        print(f"     ……还有 {len(diffs) - max_lines} 处，略")


def print_step_diff(tape_a: dict, tape_b: dict) -> None:
    """把两份磁带的每一步并排摊开。

    注意：这里只显示「哪里不一样」，不说「一不一样要紧」。后者是第 6 天
    请裁判（LLM-as-Judge）干的活，现在别急着下结论。
    """
    label_a = tape_a["meta"].get("variant") or Path(tape_a["meta"]["run_id"]).name
    label_b = tape_b["meta"].get("variant") or Path(tape_b["meta"]["run_id"]).name

    print("\n" + "=" * 72)
    print(f"逐步骤并排看：{label_a}  vs  {label_b}")
    print("=" * 72)

    steps_a, steps_b = tape_a["steps"], tape_b["steps"]

    print(f"\n任务：{tape_a['task']['name']}   模型：{tape_a['meta']['model']}")
    print(
        f"步骤数：{len(steps_a)} vs {len(steps_b)}    "
        f"总耗时：{tape_a['meta']['duration_ms']}ms vs {tape_b['meta']['duration_ms']}ms"
    )

    names_a = [s["name"] for s in steps_a]
    names_b = [s["name"] for s in steps_b]
    if names_a == names_b:
        print(f"工具调用序列：相同  {' → '.join(names_a)}")
    else:
        print(f"工具调用序列：不同\n  {label_a}: {' → '.join(names_a)}\n  {label_b}: {' → '.join(names_b)}")

    for i in range(max(len(steps_a), len(steps_b))):
        if i >= len(steps_a):
            print(f"\n#{i + 1} {steps_b[i]['label']}：只存在于 {label_b}（步骤多了一步）")
            continue
        if i >= len(steps_b):
            print(f"\n#{i + 1} {steps_a[i]['label']}：只存在于 {label_a}（步骤少了一步）")
            continue

        old, new = steps_a[i], steps_b[i]
        print(f"\n#{i + 1} {old['label']}（{old['name']}）")
        print(f"   耗时：{old['duration_ms']}ms → {new['duration_ms']}ms")

        in_diffs = walk_diff(old["input"], new["input"])
        out_diffs = walk_diff(old["output"], new["output"])

        # 上一步的输出，常常就是这一步的输入。如果两份差异完全一样，
        # 那这一步的输入变化是上一部传下来的，不是它自己改的——别把同一个
        # 根因数两遍。
        inherited = i > 0 and in_diffs == walk_diff(
            steps_a[i - 1]["output"], steps_b[i - 1]["output"]
        )

        if not in_diffs:
            print("   输入：相同")
        elif inherited:
            print(f"   输入：{len(in_diffs)} 处不同，跟 #{i} 的输出完全一致（上游传染，不是它自己变了）")
        else:
            print(f"   输入：{len(in_diffs)} 处不同")
            _print_step_changes(old["input"], new["input"])

        print(f"   输出：{'相同' if not out_diffs else f'{len(out_diffs)} 处不同'}")
        if out_diffs:
            _print_step_changes(old["output"], new["output"])

    print("\n" + "-" * 72)
    print("读法：#2 的输入变了，是因为它吃的是 #1 的输出——上游一变，下游全跟着变。")
    print("      这不等于 #2 自己出了问题，这种「传染」第 5 天的对比器必须能认出来。")


def print_overview(records: list[dict]) -> None:
    """把每次运行的关键信息并排打出来——这是「肉眼能看差异」的第一眼。"""
    print("\n" + "=" * 70)
    print("两次运行并排看")
    print("=" * 70)
    for r in records:
        print(f"\n【{r['variant']}】", end="")
        if not r["ok"]:
            print(f"  失败：{r['error']}")
            continue
        print(f"  耗时 {r['duration_ms'] / 1000:.1f}s")
        print(f"  关键词：{' / '.join(r['keywords'])}")
        text = r["summary"].replace("\n", " ")
        print(f"  摘要：{text[:60]}…" if len(text) > 60 else f"  摘要：{text}")
        print(f"  磁带：{r['tape'].relative_to(ROOT) if r['tape'].is_relative_to(ROOT) else r['tape']}")

    ok = [r for r in records if r["ok"]]
    if len(ok) == 2:
        same_kw = ok[0]["keywords"] == ok[1]["keywords"]
        same_sum = ok[0]["summary"] == ok[1]["summary"]
        print("\n" + "-" * 70)
        print(f"关键词两次{'相同' if same_kw else '不同'}")
        print(f"摘要两次{'相同' if same_sum else '不同'}")
        print("打开上面两份磁带，逐段对比 steps，就能看到差异到底出在哪一步。")


def main() -> None:
    parser = argparse.ArgumentParser(description="重放任务，生成新的行为磁带")
    parser.add_argument(
        "task",
        nargs="?",
        default=str(DEFAULT_TASK),
        help=f"任务定义 JSON 路径（默认 {DEFAULT_TASK.relative_to(ROOT)}）",
    )
    parser.add_argument("--runs", type=int, default=2, help="运行次数（默认 2）")
    parser.add_argument(
        "--labels",
        help="逗号分隔的变体名，例如 baseline,new-prompt；默认 v1,v2,...",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("TAPE_A", "TAPE_B"),
        help="只并排查看两份已有磁带，不重新运行（不花 token）",
    )
    args = parser.parse_args()

    # 只想看两份现成磁带时，不必再跑一遍
    if args.compare:
        tape_a, tape_b = (load_tape(p) for p in args.compare)
        print_step_diff(tape_a, tape_b)
        return

    labels = [s.strip() for s in args.labels.split(",")] if args.labels else None
    task = load_task(Path(args.task))
    records = replay(task, runs=args.runs, labels=labels)
    print_overview(records)

    ok = [r for r in records if r["ok"]]
    if len(ok) >= 2:
        print_step_diff(load_tape(ok[0]["tape"]), load_tape(ok[-1]["tape"]))

    if not all(r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()