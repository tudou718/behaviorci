"""toolreplay.py —— 确定性工具回放（v0.3 / D）。

问题：重放 Agent 时，工具（搜索、数据库、知识库）本身也可能变——
接口返回不同、排序不同、甚至偶发失败。这时你分不清「行为变了」是模型造成的，
还是工具环境污染的。

做法：把基线磁带里记录的工具输入输出当作「录像」，重放时按（步骤名 + 输入）
匹配，直接返回录好的输出，不再真的调用工具。这样**模型成为唯一变量**。

匹配规则：
    1. 步骤名相同
    2. 输入规范化后完全相等（JSON 键顺序无关）
    3. 按磁带中的先后顺序消费，同一步不会被复用两次

匹配不上就返回 None，由调用方决定：回退到真实工具（默认）还是直接报错。
在真实项目里建议用「报错」，因为静默回退会重新引入不确定性。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path


def _canonical(value) -> str:
    """把输入规范成可比较的字符串：键排序、紧凑分隔符。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StepReplay:
    """按顺序回放某一份磁带里记录过的步骤输出。"""

    def __init__(self, tape: dict, match: str = "exact"):
        """match="exact" 要求输入完全一致；match="name" 只要求步骤名一致。

        exact 更严格，但模型重生成计划时（关键词变了）会全部打不中；
        name 适合「只想隔离某一步模型行为」的场景，代价是假设工具调用可替换。
        """
        if match not in ("exact", "name"):
            raise ValueError("match 只能是 exact 或 name")
        self.match = match
        self.tape = tape
        self._steps = tape.get("steps", [])
        self._used: set[int] = set()
        self.hits = 0
        self.misses = 0

    @classmethod
    def from_path(cls, path: str | Path, match: str = "exact") -> "StepReplay":
        tape = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(tape, match=match)

    def replay(self, name: str, payload) -> dict | None:
        """返回录好的输出（深拷贝，避免调用方改到磁带）；没有匹配返回 None。"""
        wanted = _canonical(payload)
        fallback: int | None = None
        for index, step in enumerate(self._steps):
            if index in self._used or step.get("name") != name:
                continue
            if _canonical(step.get("input", {})) == wanted:
                return self._take(index)
            if fallback is None:
                fallback = index
        if self.match == "name" and fallback is not None:
            return self._take(fallback)
        self.misses += 1
        return None

    def _take(self, index: int) -> dict:
        self._used.add(index)
        self.hits += 1
        return copy.deepcopy(self._steps[index].get("output", {}))

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses}

    @property
    def source(self) -> str:
        return self.tape.get("meta", {}).get("run_id", "")