"""judge.py —— LLM-as-Judge（D6）：请模型当裁判。

笨对比只会说「变了」，说不清「变好还是变坏」。裁判要干的就是这件事：
把两份行为记录摆到它面前，让它像老师批卷子一样给出三选一：

    等价  —— 差异只是措辞、顺序之类的抖动，不影响任务完成
    变好  —— 候选版本在覆盖度、准确性、有用性上明显更好
    漂移  —— 候选版本偏离了任务目标，或质量退化

用什么模型？
    .env 里的 LLM_MODEL，和 Agent 是同一个。角色不同而已：
    Agent 负责「干活」，裁判负责「批卷子」。想换个更会判的模型，改 .env 即可。

为什么必须严格 JSON？
    裁判的结论要被程序接着用（写进报告、做统计、让 CI 卡住）。一句
    「我觉得还行吧」程序读不懂，所以强制 {"verdict": ..., "reason": ...}。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter

try:
    from . import provenance
    from .llm import ask, env, parse_json
except ImportError:
    import provenance
    from llm import ask, env, parse_json

# 裁判温度默认 0：判决要稳，不要发挥。
# 想看「同一个对比会不会自相矛盾」，把它调高（例如 0.8）再跑 —— 分歧会明显变多。
# 代价是判决质量下降，所以只用于观察，不要用于生产。
def _judge_temperature() -> float:
    try:
        return float(os.getenv("JUDGE_TEMPERATURE", "0") or 0)
    except ValueError:
        return 0.0


# 三选一的合法取值。模型偶尔会写「等价行为」「跑偏」这类变体，下面会做归一化。
VERDICTS = ["等价", "变好", "漂移"]

JUDGE_SYSTEM = (
    "你是严谨的行为回归评审。你只输出 JSON，不输出解释，不使用 markdown 代码块。"
)

JUDGE_TEMPLATE = """同一个任务在两次运行中留下了行为记录。

A（基线，旧行为）：
{a}

B（候选，新行为）：
{b}

结构对比结果：
{structure}

本次运行配置的变更：
{provenance}

判定标准（按顺序检查）：
1. 任务要求：如果记录里给了「任务要求」，先逐条核对两份交付物各自满足了哪些
2. 变好：B 更完整地满足任务要求——补齐了 A 缺失的必需内容、覆盖了缺失的角度、
   修正了事实错误
3. 漂移：B 未满足任务要求——缺失必需内容、偏离任务目标、编造资料外的事实、
   跳过了必要步骤（例如该生成文件却只口头回答）
4. 等价：满足任务要求的程度基本相同，差异只是措辞、语气、表达顺序

判断原则：
- 不要因为「读起来差不多」就默认等价；先对照任务要求逐条检查
- 差异落在要求的字面上（例如要求 180-220 字、要求结尾指出最没解决的问题、
  要求覆盖三个角度），就是实质性差异
- 中间步骤的输入如果只是从上游流下来的变化，不要重复扣分
- 只有在两类判断都各有充分理由、确实无法区分时才选等价

只输出 JSON，格式严格如下：
{{"verdict": "等价|变好|漂移", "reason": "一句话人话理由，60 字以内"}}"""


# ---------------------------------------------------------------------------
# 把磁带压成裁判能读的「卷子」
# ---------------------------------------------------------------------------

def _clip(value, limit: int = 500):
    """把过长的文本裁掉，避免把整盘磁带原样塞给裁判。"""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"…（省略 {len(value) - limit} 字）"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    return value


def tape_digest(tape: dict) -> str:
    """把一盘磁带整理成一页「答卷」。

    只保留裁判判断用得上的东西：任务的输入、每一步干了什么、最后交了什么。
    不塞每步的输入——因为上一步的输出就是下一步的输入，重复塞只会让裁判
    分心，也更容易把「上游传染」当成新问题。
    """
    steps = [
        {"步骤": step["label"], "输出": _clip(step.get("output", {}))}
        for step in tape["steps"]
    ]
    digest = {
        "运行": tape["meta"].get("variant") or tape["meta"]["run_id"],
        "模型": tape["meta"].get("model"),
        "任务输入": tape.get("task", {}).get("input", {}),
        "任务要求": tape.get("task", {}).get("requirements", []),
        "步骤": steps,
        "final_output": _clip(tape.get("output", {})),
    }
    return json.dumps(digest, ensure_ascii=False, indent=2)


def _structure_text(tape_a: dict, tape_b: dict) -> str:
    """给裁判一小段结构信息：步骤数和工具序列变没变。"""
    names_a = [s["name"] for s in tape_a["steps"]]
    names_b = [s["name"] for s in tape_b["steps"]]
    lines = [
        f"- 步骤数：{len(names_a)} vs {len(names_b)}",
        f"- 工具序列：{'相同' if names_a == names_b else '不同'}",
    ]
    if names_a != names_b:
        lines.append(f"  A: {' → '.join(names_a)}")
        lines.append(f"  B: {' → '.join(names_b)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 裁判
# ---------------------------------------------------------------------------

def _normalize_verdict(value: str) -> str | None:
    """把模型可能写出的变体归一到三选一。"""
    text = str(value).strip()
    for verdict in VERDICTS:
        if verdict in text:
            return verdict
    aliases = {
        "等价": "等价",
        "相同": "等价",
        "一致": "等价",
        "改善": "变好",
        "更好": "变好",
        "进步": "变好",
        "退化": "漂移",
        "下降": "漂移",
        "跑偏": "漂移",
        "偏离": "漂移",
    }
    for key, verdict in aliases.items():
        if key in text:
            return verdict
    return None


def judge(
    tape_a: dict,
    tape_b: dict,
    max_attempts: int = 2,
) -> dict:
    """判一次：A 是基线，B 是候选。

    返回 {"verdict", "reason", "model", "attempts", "elapsed_ms", "raw"}。
    """
    prov = provenance.diff(
        (tape_a.get("meta") or {}).get("provenance"),
        (tape_b.get("meta") or {}).get("provenance"),
    )
    prompt = JUDGE_TEMPLATE.format(
        a=tape_digest(tape_a),
        b=tape_digest(tape_b),
        structure=_structure_text(tape_a, tape_b),
        provenance=provenance.summary_text(prov),
    )

    started = time.perf_counter()
    last_error = None

    for attempt in range(1, max_attempts + 1):
        # 每次调用都换一个 cache_key：裁判要是命中缓存，第 7 天的
        # 「跑 3 次看多数」就全是同一份答案，等于没测。
        cache_key = f"judge-{uuid.uuid4().hex[:12]}"
        # 第二次尝试时，把出错情况明确告诉模型，帮它纠正格式
        user = prompt
        if last_error:
            user = (
                f"{prompt}\n\n上一次你输出的内容无法解析（{last_error}）。"
                '这次务必只输出一个 JSON 对象，形如 {"verdict": "等价", "reason": "……"}'
            )

        raw = ask(
            JUDGE_SYSTEM,
            user,
            temperature=_judge_temperature(),
            # 8000 是实测出来的：新判定标准更长，推理过程曾把 4000 全部吃光
            max_tokens=8000,
            cache_key=cache_key,
            purpose="judge",
        )

        try:
            data = parse_json(raw)
            verdict = _normalize_verdict(data.get("verdict", ""))
            reason = str(data.get("reason", "")).strip()
            if verdict is None:
                raise ValueError(f"verdict 不在三选一里：{data.get('verdict')!r}")
            if not reason:
                raise ValueError("reason 为空")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        return {
            "verdict": verdict,
            "reason": reason,
            "model": env("LLM_MODEL"),
            "attempts": attempt,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "raw": raw,
        }

    raise RuntimeError(f"裁判连续 {max_attempts} 次没给出合法结论：{last_error}")


# 平票时的取舍顺序：宁可多报一次漂移，也别把退化当等价放过去
CONSERVATIVE_ORDER = ["漂移", "变好", "等价"]


def judge_consensus(tape_a: dict, tape_b: dict, runs: int = 3) -> dict:
    """同一个对比让裁判连判 runs 次，多数票决定最终结论。

    为什么要这样？模型带一点随机性，同一个问题这次判等价、下次判漂移。
    单次裁决等于抽签，所以跑多次看分布：多数派是结论，少数派是「裁判自己
    也没底」的证据。这份分歧记录比一个孤零零的结论更值钱。

    实现上没什么花活：调 runs 次 judge()，数票。每次 judge() 内部都会换
    新的 cache_key，所以真的是 invoke 了模型 runs 次，不是缓存回放。

    平票（只在偶数次时出现）时按 CONSERVATIVE_ORDER 取更严格的那个结论。
    """
    if runs < 1:
        raise ValueError("runs 至少为 1")

    started = time.perf_counter()
    results: list[dict] = []
    failures: list[str] = []

    for i in range(runs):
        try:
            results.append(judge(tape_a, tape_b))
        except Exception as exc:
            # 单次失败不当成一张票，记下来继续 —— 多数票只需要过半，
            # 不必强求每一次都成功
            failures.append(f"第 {i + 1} 次：{type(exc).__name__}: {exc}")

    if not results:
        detail = failures[0] if failures else "未知原因"
        raise RuntimeError(f"裁判 {runs} 次全部失败：{detail}")

    counts = Counter(r["verdict"] for r in results)
    top = max(counts.values())
    winners = [v for v, c in counts.items() if c == top]
    verdict = (
        winners[0]
        if len(winners) == 1
        else next(v for v in CONSERVATIVE_ORDER if v in winners)
    )

    majority = counts[verdict]
    minority = len(results) - majority

    return {
        "verdict": verdict,
        # 理由取多数派里第一条，保证理由和结论来自同一次判断
        "reason": next(r["reason"] for r in results if r["verdict"] == verdict),
        "counts": dict(counts),
        "majority": majority,
        "minority": minority,
        "agreement": f"{majority}:{minority}",
        "unanimous": len(counts) == 1,
        "runs": [
            {
                "index": i + 1,
                "verdict": r["verdict"],
                "reason": r["reason"],
                "elapsed_ms": r["elapsed_ms"],
            }
            for i, r in enumerate(results)
        ],
        "failures": failures,
        "model": results[0]["model"],
        "runs_requested": runs,
        "runs_succeeded": len(results),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def skipped(reason: str = "两盘磁带内容完全一致，无需裁决") -> dict:
    """没有差异时的占位结论，保持报告结构一致。"""
    return {
        "verdict": "等价",
        "reason": reason,
        "model": None,
        "attempts": 0,
        "elapsed_ms": 0,
        "raw": None,
        "skipped": True,
    }