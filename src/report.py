"""report.py —— 把对比结果渲染成人话报告（D8）。

一份报告要回答五个问题：

    1. 这是哪个任务？
    2. 比的是哪两份磁带（概要）？
    3. 每项结构检查过没过？
    4. 内容差在哪、源头是谁？
    5. 裁判怎么判的、理由是什么？

输出两份文件到 reports/：
    .md   —— 给人看的（也能直接贴到 GitHub Pages，D10 用得上）
    .json —— 给程序和 CI 看的（D9 用得上）

为什么不直接在终端打？终端输出是过程，报告是产物。产物要能存档、能对比
历史、能被别人打开——所以必须落盘。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

try:
    from .tape import final_output_text
except ImportError:
    from tape import final_output_text

ROOT = Path(__file__).resolve().parent.parent


def _fmt_ms(ms: int | None) -> str:
    if not ms:
        return "—"
    return f"{ms / 1000:.1f}s"


def _verdict_line(verdict: dict) -> str:
    """把裁判结论压成一句话。"""
    if verdict.get("skipped"):
        return f"未裁决（{verdict['reason']}）"
    if verdict.get("verdict") is None:
        return f"裁决失败（{verdict['reason']}）"
    return f"**{verdict['verdict']}**（{verdict['agreement']}）"


def _tape_row(label: str, tape: dict) -> str:
    meta = tape["meta"]
    return (
        f"| {label} | `{meta.get('variant') or meta['run_id']}` | "
        f"{meta.get('model', '—')} | {meta.get('started_at', '—')} | "
        f"{_fmt_ms(meta.get('duration_ms'))} | {meta.get('step_count', len(tape['steps']))} |"
    )


def render_markdown(report: dict, tape_a: dict, tape_b: dict) -> str:
    """渲染成一份 Markdown 报告。"""
    content = report["content"]
    verdict = report["verdict"]
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []
    lines.append(f"# BehaviorCI 报告 · {report['task']}")
    lines.append("")
    lines.append(f"生成时间：{generated}")
    lines.append("")
    lines.append(f"## 最终判定：{_verdict_line(verdict)}")
    lines.append("")
    if verdict.get("verdict") and not verdict.get("skipped"):
        lines.append(f"> {verdict['reason']}")
        lines.append("")
        tally = " / ".join(f"{v} ×{n}" for v, n in (verdict.get("counts") or {}).items())
        if tally:
            lines.append(f"裁判票型：{tally}（共 {verdict.get('runs_succeeded', 0)} 次有效判断）")
            lines.append("")

    lines.append("## 磁带概要")
    lines.append("")
    lines.append("| | 变体 | 模型 | 开始时间 | 耗时 | 步骤数 |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(_tape_row("基线", tape_a))
    lines.append(_tape_row("候选", tape_b))
    lines.append("")

    lines.append("## 结构对比")
    lines.append("")
    lines.append("| 检查项 | 结果 | 说明 |")
    lines.append("|---|---|---|")
    for check in report["checks"]:
        mark = "✓ 一致" if check["consistent"] else "✗ 不同"
        lines.append(f"| {check['label']} | {mark} | {check['detail']} |")
    s = report["summary"]
    lines.append("")
    lines.append(
        f"**{s['total']} 项对比，{s['consistent']} 项一致，{s['different']} 项不同**"
    )
    lines.append("")

    lines.append("## 内容差异")
    lines.append("")
    if not content["changed_steps"]:
        lines.append("两份磁带内容完全一致。")
    else:
        root_names = {r["name"] for r in content["root_steps"]}
        for item in content["changed_steps"]:
            tag = "（源头）" if item["name"] in root_names else "（输入来自上游，输出跟着变）"
            lines.append(
                f"- 第 {item['index']} 步「{item['label']}」：输出 {item['diff_count']} 处不同{tag}"
            )
        if content["final_output_changed"]:
            lines.append("- 最终交付物（summary）也变了")
    lines.append("")

    base_text = final_output_text(tape_a)
    cand_text = final_output_text(tape_b)
    if base_text or cand_text:
        lines.append("### 最终交付物对比")
        lines.append("")
        lines.append(f"**基线**")
        lines.append("")
        lines.append(f"> {base_text or '（空）'}")
        lines.append("")
        lines.append(f"**候选**")
        lines.append("")
        lines.append(f"> {cand_text or '（空）'}")
        lines.append("")

    lines.append("## 裁判")
    lines.append("")
    if verdict.get("skipped"):
        lines.append(f"未调用裁判：{verdict['reason']}")
    elif verdict.get("verdict") is None:
        lines.append(f"裁判调用失败：{verdict['reason']}")
    else:
        lines.append(f"- 结论：{verdict['verdict']}")
        lines.append(f"- 票型：{verdict.get('agreement', '—')}")
        lines.append(f"- 理由：{verdict['reason']}")
        if verdict.get("runs"):
            lines.append("")
            lines.append("### 每次判断")
            lines.append("")
            for run in verdict["runs"]:
                lines.append(f"{run['index']}. **{run['verdict']}** — {run['reason']}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "由 BehaviorCI 生成。结构对比是本地规则，最终判定由 LLM-as-Judge "
        f"（{verdict.get('model') or '未调用'}）投票给出。"
    )
    lines.append("")
    return "\n".join(lines)


def save(
    report: dict,
    tape_a: dict,
    tape_b: dict,
    out_dir: Path | str | None = None,
) -> tuple[Path, Path]:
    """把报告写到 reports/，返回 (markdown 路径, json 路径)。"""
    out = Path(out_dir) if out_dir else ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"{stamp}-{report['task']}"

    md_path = out / f"{stem}.md"
    json_path = out / f"{stem}.json"

    md_path.write_text(render_markdown(report, tape_a, tape_b), encoding="utf-8")
    # 把两份磁带也塞进 payload：这样报告是自包含的，
    # 网页渲染、事后复查都不需要再去找原始磁带文件。
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "baseline_tape": tape_a["meta"]["run_id"],
        "candidate_tape": tape_b["meta"]["run_id"],
        "baseline": tape_a,
        "candidate": tape_b,
        "report": report,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return md_path, json_path