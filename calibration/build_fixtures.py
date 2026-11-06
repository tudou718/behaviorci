"""build_fixtures.py —— 可复现地生成校准用的构造样本。

为什么用脚本生成而不是手工改 JSON？
    标注的可信度来自「变换是已知的」：我们删掉任务要求的结论、把话题换掉、
    插入资料外的事实——每种变换的方向是构造时就确定的，不依赖事后阅读。
    脚本也让任何人都能重新生成、核对。

现有变换：
    offtopic        交付物换成完全无关的内容        → 相对原文应为「漂移」
    hallucination   追加资料里没有的事实            → 「漂移」
    missing-section 删掉任务要求的一个角度          → 「漂移」（作为候选时）
    truncated       删掉任务要求的结尾结论          → 「漂移」（作为候选时）
    too-short       压缩到远低于字数要求            → 「漂移」
    english         中文任务却用英文交付            → 「漂移」
    empty           不交付任何内容                  → 「漂移」
    no-tool         跳过文件生成工具，只口头回答     → 「漂移」（结构层）

同一个样本既可以当候选（比原文差），也可以当基线（比原文好），
方向由 cases.json 里的 A/B 顺序决定。

用法：
    python calibration/build_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "calibration" / "tapes"
DAILY = ROOT / "tapes" / "daily-brief-v2-20261028-163428.json"
DEEPSEARCH = ROOT / "tapes" / "deepsearch-v2-20261102-143405.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(tape: dict, name: str) -> None:
    tape["meta"]["fixture"] = True
    tape["meta"]["variant"] = name
    (OUT / f"{name}.json").write_text(
        json.dumps(tape, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def with_summary(tape: dict, text: str) -> dict:
    """同时改交付物和最后一步的输出，保持磁带内部一致。"""
    import copy

    out = copy.deepcopy(tape)
    out["output"]["summary"] = text
    out["steps"][-1]["output"]["summary"] = text
    return out


def build() -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    daily = load(DAILY)
    deepsearch = load(DEEPSEARCH)
    full = daily["output"]["summary"]
    built = []

    # 跑题：完全无关的内容
    save(
        with_summary(
            daily,
            "本季度咖啡豆价格受产区天气影响明显走高，烘焙商普遍上调零售价，"
            "消费者转向替代饮品，行业需关注供应链波动。",
        ),
        "fixture-offtopic",
    )
    built.append("fixture-offtopic")

    # 编造：追加资料里没有的事实
    save(
        with_summary(
            daily,
            full + "另据最新报道，某实验室已将该类 Agent 的推理成本降低 60%。",
        ),
        "fixture-hallucination",
    )
    built.append("fixture-hallucination")

    # 缺角度：删掉「工程实践」那段
    sentences = full.split("。")
    kept = "。".join([sentences[0], sentences[3], sentences[4]]).strip()
    if not kept.endswith("。"):
        kept += "。"
    save(with_summary(daily, kept), "fixture-missing-section")
    built.append("fixture-missing-section")

    # 缺结尾结论：删掉最后一句
    cut = full.rsplit("。", 2)[0] + "。"
    save(with_summary(daily, cut), "fixture-truncated")
    built.append("fixture-truncated")

    # 太短：远低于 180-220 字要求
    save(with_summary(daily, "AI Agent 最近有些进展，但问题也不少。"), "fixture-too-short")
    built.append("fixture-too-short")

    # 语言不符：中文任务用英文交付
    save(
        with_summary(
            daily,
            "Recent work on AI agents focuses on tool-calling stability, long-horizon "
            "planning, and inference cost. Reproducibility remains the main gap.",
        ),
        "fixture-english",
    )
    built.append("fixture-english")

    # 不交付
    save(with_summary(daily, ""), "fixture-empty")
    built.append("fixture-empty")

    # 智研搜：跑题交付
    import copy

    ds_off = copy.deepcopy(deepsearch)
    bad = "已为你生成《咖啡豆市场周报.md》，内容包括产区天气、期货价格与替代品趋势。"
    ds_off["output"]["final"] = bad
    ds_off["steps"][-1]["output"]["content"] = bad
    save(ds_off, "fixture-deepsearch-offtopic")
    built.append("fixture-deepsearch-offtopic")

    # 智研搜：跳过工具，只口头回答
    ds_no_tool = copy.deepcopy(deepsearch)
    ds_no_tool["steps"] = [s for s in ds_no_tool["steps"] if s["name"] == "model_message"]
    oral = "根据我的了解，多智能体协同可以提升效率，建议直接阅读相关资料。"
    ds_no_tool["output"]["final"] = oral
    if ds_no_tool["steps"]:
        ds_no_tool["steps"][0]["output"]["content"] = oral
    save(ds_no_tool, "fixture-deepsearch-no-tool")
    built.append("fixture-deepsearch-no-tool")

    return built


if __name__ == "__main__":
    names = build()
    print(f"✓ 生成 {len(names)} 个样本：")
    for name in names:
        print(f"  {OUT / (name + '.json')}")