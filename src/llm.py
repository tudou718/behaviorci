"""llm.py —— 所有调模型的入口。

配置、客户端、一次对话、JSON 解析，全放这里。

为什么单独拎出来？
    Agent 要调模型（干活），裁判也要调模型（批卷子）。如果各写一份，
    迟早会出现「Agent 用 A 配置、裁判用 B 配置」的错乱。
    所以这里只留一个入口：想调模型，就来 ask()。

模型是谁？
    由 .env 里的 LLM_MODEL 决定，代码里不写死任何厂商或型号。
    Agent 和裁判默认用同一个模型——角色不同，工具相同。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(name: str) -> str:
    """读取一个必填环境变量，缺了就明确报错。"""
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"缺少环境变量 {name}，请在 {ROOT / '.env'} 里配置")
    return value


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """懒加载客户端：只有真正要调模型时才创建。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=env("LLM_API_KEY"), base_url=env("LLM_BASE_URL"))
    return _client


def ask(
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    cache_key: str | None = None,
) -> str:
    """一次最普通的对话调用，返回模型说的话（已去掉首尾空白）。

    注意 max_tokens 要给得宽裕：现在的模型带「推理过程」，思考用的 token
    也从这个额度里扣。额度给少了，推理会把预算吃光，最后正文是空的。

    cache_key 会作为 API 的 user 字段发出去，用来区分「这是哪一次调用」。
    必须传：网关会把 prompt 完全相同的请求直接返回缓存结果（实测 1.5 秒的
    生成变成了 150 毫秒且内容一字不差）。做行为测试时命中缓存等于什么都没
    测到；换个 user 值，缓存键就变了，模型才会真跑。
    """
    extra = {"user": cache_key} if cache_key else {}
    response = get_client().chat.completions.create(
        model=env("LLM_MODEL"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
    )
    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        raise RuntimeError(
            f"模型返回空内容（finish_reason={choice.finish_reason}）。"
            "多半是推理过程把 max_tokens 吃光了，调大该值再试。"
        )
    return content


def parse_json(text: str) -> dict:
    """从模型输出里抠出 JSON。

    就算提示词写了「只输出 JSON」，模型偶尔还是会包一层 ```json 代码块，
    或者前面加一句「好的：」。所以先剥代码块，再截取第一个 { 到最后一个 }。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉第一行的 ``` 或 ```json，以及结尾的 ```
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"模型没有返回 JSON：{text[:200]}")
    return json.loads(cleaned[start : end + 1])

if __name__ == "__main__":
    # 一行自检：确认 .env 里的 Key 现在还能不能调通。
    # 用法：python src/llm.py
    import sys
    import uuid

    try:
        reply = ask(
            "你只回答一个词：ok",
            "现在能正常调用吗？只回答 ok。",
            temperature=0,
            max_tokens=500,
            cache_key=f"probe-{uuid.uuid4().hex[:8]}",
        )
        print(f"✓ 连通正常（模型 {env('LLM_MODEL')}）：{reply[:50]}")
    except Exception as exc:
        print(f"✗ 调用失败：{type(exc).__name__}: {exc}")
        sys.exit(1)
