"""calibrate.py —— 校准裁判（v0.2 / C）。

LLM-as-Judge 最容易犯的错误是「看起来很专业，但没人验证过它准不准」。
这个模块用一套**人工标注**的磁带对来量化裁判的可信度：

    一致率（accuracy）—— 判对的比例
    Cohen's kappa      —— 扣掉「瞎猜也能蒙对」之后的一致程度
    混淆矩阵           —— 哪类判断最容易混淆（例如把"变好"判成"漂移"）

标注文件：calibration/cases.json
标注规则很简单：人只看两份磁带的内容，判断 B 相对 A 是等价 / 变好 / 漂移，
不参考裁判的结论。标注定了就不再改，否则校准没有意义。

用法：
    python main.py calibrate                 # 3 票多数，跑全部样本
    python main.py calibrate --runs 1        # 省钱模式
    python main.py calibrate --json
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    from . import judge as judge_mod
    from .tape import load_tape
except ImportError:
    import judge as judge_mod
    from tape import load_tape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "calibration" / "cases.json"
LABELS = ["等价", "变好", "漂移"]


def load_cases(path: Path = DEFAULT_CASES) -> tuple[list[dict], list[str]]:
    """读取校准集，返回 (可用样本, 缺失文件说明)。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases, missing = [], []
    for case in data["cases"]:
        baseline = ROOT / case["baseline"]
        candidate = ROOT / case["candidate"]
        if not baseline.exists() or not candidate.exists():
            missing.append(
                f"{case['id']}：找不到 {baseline if not baseline.exists() else candidate}"
            )
            continue
        cases.append(
            {
                **case,
                "_baseline_path": baseline,
                "_candidate_path": candidate,
            }
        )
    return cases, missing


def run(cases: list[dict], runs: int = 3, progress=print) -> list[dict]:
    """逐题跑裁判，返回每题的标注与预测。"""
    results = []
    for index, case in enumerate(cases, start=1):
        progress(f"[{index}/{len(cases)}] {case['id']} ...", end="", flush=True)
        try:
            verdict = judge_mod.judge_consensus(
                load_tape(case["_baseline_path"]),
                load_tape(case["_candidate_path"]),
                runs=runs,
            )
            predicted = verdict["verdict"]
            agreement = verdict.get("agreement", "?")
            reason = verdict.get("reason", "")
            model = verdict.get("model")
            ok = True
        except Exception as exc:  # 单题失败不应中断整套校准
            predicted, agreement, reason, ok = None, "失败", str(exc), False
            model = None
        progress(" " + (predicted or "失败"))

        results.append(
            {
                "id": case["id"],
                "label": case["label"],
                "predicted": predicted,
                "agreement": agreement,
                "reason": reason,
                "note": case.get("note", ""),
                "ok": ok,
                "model": model,
                "correct": ok and predicted == case["label"],
            }
        )
    return results


def _confusion(results: list[dict]) -> dict:
    matrix = {label: Counter() for label in LABELS}
    for item in results:
        if not item["ok"]:
            continue
        matrix[item["label"]][item["predicted"]] += 1
    return matrix


def cohen_kappa(results: list[dict], labels: list[str] = LABELS) -> float | None:
    """多分类 Cohen's kappa：扣掉随机一致后的真实一致度。"""
    valid = [r for r in results if r["ok"]]
    n = len(valid)
    if n == 0:
        return None
    po = sum(1 for r in valid if r["correct"]) / n
    human = Counter(r["label"] for r in valid)
    judge = Counter(r["predicted"] for r in valid)
    pe = sum(human[label] * judge[label] for label in labels) / (n * n)
    if pe >= 1:
        return 1.0
    return (po - pe) / (1 - pe)


def summarize(results: list[dict], runs: int) -> dict:
    valid = [r for r in results if r["ok"]]
    correct = sum(1 for r in valid if r["correct"])
    matrix = _confusion(results)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs_per_case": runs,
        "model": valid[0].get("model") if valid else None,
        "total": len(results),
        "valid": len(valid),
        "failed": len(results) - len(valid),
        "correct": correct,
        "accuracy": round(correct / len(valid), 3) if valid else None,
        "kappa": round(cohen_kappa(results), 3) if valid else None,
        "confusion": {h: dict(row) for h, row in matrix.items()},
        "mismatches": [r for r in valid if not r["correct"]],
        "failures": [r for r in results if not r["ok"]],
        "results": results,
    }


def _interpret(kappa: float | None) -> str:
    if kappa is None:
        return "样本不足"
    if kappa >= 0.8:
        return "几乎完全一致，可作为自动门禁"
    if kappa >= 0.6:
        return "较强一致，建议保留人工复核高风险判定"
    if kappa >= 0.4:
        return "中等一致，自动结论只能当参考"
    return "一致度低，裁判结论不可直接用于门禁"


def render(summary: dict) -> str:
    lines = []
    total = summary["total"]
    valid = summary["valid"]
    lines.append("=" * 64)
    lines.append("裁判校准报告")
    lines.append("=" * 64)
    lines.append(
        f"样本：{total} 对（有效 {valid}，失败 {summary['failed']}）"
        f"    每对裁判投票：{summary['runs_per_case']} 次"
    )
    if summary["accuracy"] is not None:
        lines.append(
            f"一致率：{summary['accuracy']:.2f}"
            f"（{summary['correct']}/{valid}）"
            f"    Cohen's kappa：{summary['kappa']:.2f} —— {_interpret(summary['kappa'])}"
        )
    lines.append("")
    lines.append(f"混淆矩阵（行 = 人工标注，列 = 裁判结论）")
    header = "        " + "".join(f"{label:<8}" for label in LABELS)
    lines.append(header)
    for human in LABELS:
        row = summary["confusion"].get(human, {})
        cells = "".join(f"{row.get(label, 0):<8}" for label in LABELS)
        lines.append(f"{human:<8}{cells}")
    lines.append("")

    if summary["mismatches"]:
        lines.append("不一致样本：")
        for item in summary["mismatches"]:
            lines.append(
                f"  · {item['id']}：人工={item['label']} 裁判={item['predicted']}"
                f"（{item['agreement']}）"
            )
            lines.append(f"    裁判理由：{item['reason']}")
        lines.append("")
    else:
        lines.append("全部一致。")
        lines.append("")

    if summary["failures"]:
        lines.append("失败样本：")
        for item in summary["failures"]:
            lines.append(f"  · {item['id']}：{item['reason'][:120]}")
        lines.append("")
    return "\n".join(lines)


def save(summary: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    out = out_dir or ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out / f"calibration-{stamp}.json"
    md_path = out / f"calibration-{stamp}.md"

    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(render(summary), encoding="utf-8")
    return md_path, json_path