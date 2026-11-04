"""provenance.py —— 运行配置的「指纹」（v0.2 / A）。

磁带原本只记录「行为」，不知道「为什么会变」。这个模块补上另一半：

    - 这次用的是哪个模型
    - 每个 system prompt 的 sha256 和全文
    - 关键参数（温度、max_tokens）
    - 注册了哪些工具

对比两份磁带时，就能回答：
    「行为变了，同时 summary_system 提示词也改过（相似度 0.82）」

注意两个取舍：
1. prompt 全文存进磁带，而不是只存 hash。因为要算相似度、要给人看改了什么，
   只存 hash 只能告诉你「变了」，说不出「变了多少」。prompt 通常几百字，
   存全文的代价可以接受。
2. 指纹放在 meta 里，不参与 steps 对比。它不是 Agent 的行为，而是行为的环境。
"""

from __future__ import annotations

import difflib
import hashlib


def prompt_fingerprint(name: str, text: str) -> dict:
    """一个 prompt 的指纹：名字、短 hash、长度、全文。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return {"name": name, "sha256": digest, "chars": len(text), "text": text}


def build(
    agent: str,
    model: str,
    prompts: dict[str, str] | None = None,
    params: dict | None = None,
    tools: list[str] | None = None,
) -> dict:
    """组装一份运行配置，交给 Recorder 存进磁带。"""
    return {
        "agent": agent,
        "model": model or "",
        "prompts": [
            prompt_fingerprint(name, text) for name, text in (prompts or {}).items()
        ],
        "params": params or {},
        "tools": sorted(tools or []),
    }


def _prompt_index(prompts: list[dict] | None) -> dict[str, dict]:
    return {item["name"]: item for item in (prompts or [])}


def diff(old: dict | None, new: dict | None) -> dict:
    """比较两份运行配置，返回结构化差异。"""
    if not old or not new:
        return {
            "available": False,
            "changed": False,
            "items": [],
            "reason": "至少一份磁带没有记录运行配置（旧版本录制的磁带）",
        }

    items: list[dict] = []

    if (old.get("model") or "") != (new.get("model") or ""):
        items.append(
            {
                "kind": "model",
                "label": "模型",
                "from": old.get("model") or "—",
                "to": new.get("model") or "—",
            }
        )

    old_prompts = _prompt_index(old.get("prompts"))
    new_prompts = _prompt_index(new.get("prompts"))
    for name in sorted(set(old_prompts) | set(new_prompts)):
        before = old_prompts.get(name)
        after = new_prompts.get(name)
        if before and after:
            if before["sha256"] == after["sha256"]:
                continue
            similarity = difflib.SequenceMatcher(
                None, before["text"], after["text"]
            ).ratio()
            items.append(
                {
                    "kind": "prompt",
                    "name": name,
                    "label": f"提示词 {name}",
                    "similarity": round(similarity, 2),
                    "from": before["text"],
                    "to": after["text"],
                }
            )
        elif before:
            items.append(
                {
                    "kind": "prompt_removed",
                    "name": name,
                    "label": f"移除提示词 {name}",
                }
            )
        else:
            items.append(
                {
                    "kind": "prompt_added",
                    "name": name,
                    "label": f"新增提示词 {name}",
                }
            )

    old_params = old.get("params") or {}
    new_params = new.get("params") or {}
    for key in sorted(set(old_params) | set(new_params)):
        if old_params.get(key) != new_params.get(key):
            items.append(
                {
                    "kind": "param",
                    "name": key,
                    "label": f"参数 {key}",
                    "from": old_params.get(key, "—"),
                    "to": new_params.get(key, "—"),
                }
            )

    old_tools = set(old.get("tools") or [])
    new_tools = set(new.get("tools") or [])
    if new_tools - old_tools:
        items.append(
            {
                "kind": "tools_added",
                "label": "新增工具",
                "to": sorted(new_tools - old_tools),
            }
        )
    if old_tools - new_tools:
        items.append(
            {
                "kind": "tools_removed",
                "label": "移除工具",
                "to": sorted(old_tools - new_tools),
            }
        )

    return {"available": True, "changed": bool(items), "items": items}


def describe(item: dict) -> str:
    """把一条差异压成一句人话。"""
    kind = item["kind"]
    if kind == "model":
        return f"模型：{item['from']} → {item['to']}"
    if kind == "prompt":
        return f"{item['label']} 改动（相似度 {item['similarity']:.2f}）"
    if kind == "param":
        return f"{item['label']}：{item['from']} → {item['to']}"
    if kind == "tools_added":
        return f"新增工具：{'、'.join(item['to'])}"
    if kind == "tools_removed":
        return f"移除工具：{'、'.join(item['to'])}"
    return item["label"]


def summary_text(prov_diff: dict) -> str:
    """给裁判看的一段简短变更说明（不放 prompt 全文，控制 token）。"""
    if not prov_diff.get("available"):
        return "（两份磁带都没有记录运行配置）"
    if not prov_diff.get("changed"):
        return "（模型、Prompt、参数、工具均未变化）"
    return "；".join(describe(item) for item in prov_diff["items"])