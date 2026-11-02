"""tape.py —— 磁带的读与比（纯数据层）。

这里只做两件事：把磁带读进来、把两份数据逐字段找出差异。
不调模型、不碰业务逻辑。

为什么单独拎出来？
    第 4 天的并排查看器和第 5 天的对比器，用的是同一套「哪里不一样」的算法。
    如果各写一份，早晚会出现「查看器说变了、对比器说没变」的尴尬。
    所以差异算法只写一次，两边共用。
"""

from __future__ import annotations

import json
from pathlib import Path


def load_tape(path: str | Path) -> dict:
    """读一份磁带文件。"""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"找不到磁带：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def walk_diff(a, b, path: str = "") -> list[tuple[str, object, object]]:
    """递归找出两份数据里值不同的叶子，返回 [(路径, 基线值, 候选值)]。

    为什么是「叶子级」而不是整段比较？
        如果把整个 steps 当字符串比，你只会得到一句「不一样」。逐层往下走到
        具体的字段和数组元素，才能说出「第 2 个关键词变了」这种能读的话。
    """
    diffs: list[tuple[str, object, object]] = []

    if isinstance(a, dict) and isinstance(b, dict):
        for key in list(a.keys()) + [k for k in b if k not in a]:
            child = f"{path}.{key}" if path else str(key)
            if key not in a:
                diffs.append((child, None, b[key]))
            elif key not in b:
                diffs.append((child, a[key], None))
            else:
                diffs += walk_diff(a[key], b[key], child)
        return diffs

    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            child = f"{path}[{i}]"
            if i >= len(a):
                diffs.append((child, None, b[i]))
            elif i >= len(b):
                diffs.append((child, a[i], None))
            else:
                diffs += walk_diff(a[i], b[i], child)
        return diffs

    if a != b:
        diffs.append((path, a, b))
    return diffs