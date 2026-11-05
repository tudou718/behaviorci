#!/usr/bin/env python3
"""demo_agent.py —— BehaviorCI 的第 2 天产物：一个最小的「小白鼠」Agent。

它做的活很简单，分三步：

    1. 规划（调 LLM）：给一个主题，想出 3 个搜索关键词
    2. 搜索（假数据）：按关键词假装搜到几条资料
    3. 写作（调 LLM）：把资料写成一段 200 字左右的摘要

为什么搜索是假的？
    第 2 天的目标是「先让 Agent 动起来」。真接搜索引擎会引入网络、额度、
    反爬、解析等一堆额外变量，而 BehaviorCI 要观察的是 Agent 的「行为」，
    不是搜索质量。等流程跑通，第 11 天接真实项目时再替换掉这一步。

为什么假数据是「固定的」？
    因为第 4 天要重放同一个任务、观察两份磁带差在哪。把搜索这一步钉死，
    差异就只可能来自两次 LLM 调用——你才能亲眼看到不确定性到底出在哪。
    这本身就是 BehaviorCI 的一个核心思想：变量要可控。

用法：
    python src/demo_agent.py "AI Agent 最新进展"
    python src/demo_agent.py "AI Agent 最新进展" --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 支持两种运行方式：python src/demo_agent.py  或  python -m src.demo_agent
try:
    from . import provenance
    from .llm import ask, parse_json
    from .recorder import Recorder
except ImportError:
    import provenance
    from llm import ask, parse_json
    from recorder import Recorder

# .env 在项目根目录，不在 src/ 里。用 __file__ 往上找一层，这样从哪个目录
# 运行脚本都能读到配置。
ROOT = Path(__file__).resolve().parent.parent

# 这个 Agent 的任务标识。磁带里会带上它，以后按任务名找基线。
TASK_NAME = "daily-brief"


# ---------------------------------------------------------------------------
# 第 1 步：规划 —— 把主题拆成 3 个搜索关键词
# ---------------------------------------------------------------------------

KEYWORD_SYSTEM = (
    "你是一个信息检索助手。你只输出 JSON，不输出解释，不使用 markdown 代码块。"
)


def generate_keywords(topic: str, cache_key: str | None = None) -> list[str]:
    """让模型围绕主题想 3 个互补的搜索关键词。"""
    prompt = f"""围绕主题「{topic}」设计 3 个互补的搜索关键词。
要求：
- 三个词分别覆盖「最新进展 / 工程实践 / 争议或局限」三个角度
- 每个关键词 4-15 个字，像真人会输入搜索框的词
- 只输出 JSON，格式严格如下：
{{"keywords": ["关键词1", "关键词2", "关键词3"]}}"""

    raw = ask(
        KEYWORD_SYSTEM,
        prompt,
        temperature=0.2,
        max_tokens=2000,
        cache_key=cache_key,
        purpose="agent:keywords",
    )
    data = parse_json(raw)
    keywords = [str(k).strip() for k in data.get("keywords", []) if str(k).strip()]
    if len(keywords) < 3:
        raise RuntimeError(f"关键词数量不足 3 个：{keywords}")
    return keywords[:3]


# ---------------------------------------------------------------------------
# 第 2 步：搜索 —— 用假数据模拟搜索引擎
# ---------------------------------------------------------------------------

# 三条固定的「资料模板」。用固定内容而不是随机内容，是为了让重放时的差异
# 只来自模型，不来自数据本身。
_SEARCH_TEMPLATES = [
    (
        "{kw}：本年度进展综述",
        "多家机构在「{kw}」方向上发布新工作，关注点集中在工具调用稳定性、"
        "长任务规划与推理成本，行业仍缺一套统一的评测口径。",
    ),
    (
        "「{kw}」工程落地盘点",
        "一线团队反馈，「{kw}」落地的难点不在模型能力，而在行为可复现性："
        "同一个任务跑两次，中间步骤和最终结论都可能不一样。",
    ),
    (
        "关于「{kw}」的三个常见误解",
        "讨论「{kw}」时，常把「演示效果好」等同于「生产可用」。"
        "两者之间差的是回归测试、可观测性与失败时的兜底策略。",
    ),
]


def mock_search(keywords: list[str]) -> list[dict]:
    """模拟搜索：每个关键词返回一条假资料。

    注意这是个「工具调用」——第 3 天的 recorder 会把它记成磁带里的一步，
    所以返回值刻意做成结构化数据，而不是一段拼好的字符串。
    """
    results = []
    for keyword, (title_tpl, snippet_tpl) in zip(keywords, _SEARCH_TEMPLATES):
        results.append(
            {
                "keyword": keyword,
                "title": title_tpl.format(kw=keyword),
                "snippet": snippet_tpl.format(kw=keyword),
                "url": "mock://search/" + str(abs(hash(keyword)) % 10**8),
            }
        )
    return results


# ---------------------------------------------------------------------------
# 第 3 步：写作 —— 把资料写成 200 字摘要
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM = (
    "你是一名技术简报撰稿人。写作克制、具体，不堆形容词，不用 markdown 标题，"
    "不编造资料里没有的数字或事实。"
)


def write_summary(
    topic: str, results: list[dict], cache_key: str | None = None
) -> str:
    """让模型把搜到的资料写成一段摘要。"""
    materials = "\n".join(
        f"- 标题：{r['title']}\n  内容：{r['snippet']}" for r in results
    )
    prompt = f"""主题：{topic}

可用资料：
{materials}

请写一段中文摘要，180-220 字，要求：
1. 开头直接给正文，不要「以下是摘要」这类引导语
2. 只使用上面资料里出现的信息，不要补充资料之外的事实
3. 结尾用一句话指出：这个方向目前最没解决好的问题是什么"""

    return ask(
        SUMMARY_SYSTEM,
        prompt,
        temperature=0.7,
        max_tokens=4000,
        cache_key=cache_key,
        purpose="agent:summary",
    )


# ---------------------------------------------------------------------------
# 串起来：一次完整运行
# ---------------------------------------------------------------------------

def run(
    topic: str,
    record: bool = True,
    variant: str | None = None,
    cache_nonce: str | None = None,
    requirements: list[str] | None = None,
) -> dict:
    """跑一次完整任务，返回这次运行的完整结果。

    默认边跑边录：每做完一步就 recorder.log 一笔，最后存成一份磁带。
    返回 dict 而不是直接打印，是为了调用方（比如后面的 replay）能直接用。

    variant 是磁带上的标记，比如「v1」「v2」——replay 用它区分同任务的多次运行。
    """
    # 每次运行一个唯一的运行标识。它有两个用途：
    #   1) 当 API 的 user 字段，让网关的缓存失效（见 ask 的说明）
    #   2) 写进磁带，方便你把某一步的问题追溯到唯一一次运行
    run_tag = variant or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if cache_nonce:
        # 同一变体重复运行时，必须让缓存键不同，否则每次拿到的都是同一份缓存
        run_tag = f"{run_tag}-{cache_nonce}"

    recorder = (
        Recorder(
            task_name=TASK_NAME,
            task_input={"topic": topic},
            task_requirements=requirements,
            agent="demo_agent",
            variant=variant,
            model=os.getenv("LLM_MODEL", ""),
            provenance=provenance.build(
                agent="demo_agent",
                model=os.getenv("LLM_MODEL", ""),
                prompts={
                    "keyword_system": KEYWORD_SYSTEM,
                    "summary_system": SUMMARY_SYSTEM,
                },
                params={
                    "temperature_keywords": 0.2,
                    "temperature_summary": 0.7,
                },
                tools=["mock_search"],
            ),
        )
        if record
        else None
    )

    try:
        say(f"[1/3] 规划关键词：{topic}")
        keywords = generate_keywords(topic, cache_key=f"{TASK_NAME}-{run_tag}-kw")
        if recorder:
            recorder.log(
                "generate_keywords",
                input={"topic": topic},
                output={"keywords": keywords},
                label="规划关键词",
            )
        say(f"      → {keywords}")

        say("[2/3] 模拟搜索")
        results = mock_search(keywords)
        if recorder:
            recorder.log(
                "search",
                input={"keywords": keywords},
                output={"results": results},
                label="模拟搜索",
            )
        say(f"      → 命中 {len(results)} 条资料")

        say("[3/3] 撰写摘要")
        summary = write_summary(topic, results, cache_key=f"{TASK_NAME}-{run_tag}-sum")
        if recorder:
            recorder.log(
                "write_summary",
                input={"topic": topic, "results": results},
                output={"summary": summary},
                label="撰写摘要",
            )

    except Exception as exc:
        # 跑崩了也要把已记录的部分存下来——出错的那份磁带最有分析价值
        if recorder:
            path = recorder.finish(
                status="error", error=f"{type(exc).__name__}: {exc}"
            )
            say(f"✗ 运行出错，已记录残缺磁带：{_rel(path)}")
        raise

    result = {
        "topic": topic,
        "keywords": keywords,
        "results": results,
        "summary": summary,
    }
    if recorder:
        result["tape"] = str(recorder.finish(output={"summary": summary}))
    return result


def say(message: str) -> None:
    """过程信息走 stderr，这样 --json 时 stdout 只有干净的 JSON。"""
    print(message, file=sys.stderr)


def _rel(path: Path) -> str:
    """路径显示短一点：能相对项目根就相对，不能就写绝对路径。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BehaviorCI 的 demo Agent：主题 → 关键词 → 搜索 → 摘要"
    )
    parser.add_argument("topic", help="要研究的主题，例如「AI Agent 最新进展」")
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出完整运行结果（JSON），含磁带路径",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="只跑不录，不生成磁带（调试用）",
    )
    args = parser.parse_args()

    result = run(args.topic, record=not args.no_record)
    tape = result.get("tape")
    if tape:
        say(f"磁带已保存：{_rel(Path(tape))}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("\n" + "=" * 60)
    print(f"主题：{result['topic']}")
    print("=" * 60)
    print(f"\n关键词：{' / '.join(result['keywords'])}\n")
    print("检索到的资料：")
    for i, item in enumerate(result["results"], 1):
        print(f"  {i}. {item['title']}")
        print(f"     {item['snippet']}")
    print("\n" + "-" * 60)
    print("摘要：\n")
    print(result["summary"])
    print("\n" + "-" * 60)


if __name__ == "__main__":
    main()