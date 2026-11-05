"""recorder.py —— 行为磁带记录器（D3）。

一份「磁带（tape）」就是一次运行的完整流水账 JSON：
    任务是什么、什么时候跑的、用的哪个模型、
    一共几步、每步叫什么、输入和输出是什么、各花了多久、总共多久。

三条设计原则，后面几天都靠它们：

1. 记录器不碰业务逻辑
   它只负责「收」和「存」，Agent 负责「报」。所以它不需要知道 Agent 在干嘛，
   换成第 11 天的智研搜，照样能用。

2. 输入输出必须是普通数据（能 json.dumps 的）
   这会逼着每一步的「契约」变清晰：输入是什么、输出是什么，一目了然。
   后面 diff 对比的也是这些结构，而不是一坨日志字符串。

3. 失败了也要落盘
   一次跑崩的运行，恰恰是最有分析价值的那一份。所以 finish() 支持
   status="error"，把错误信息也写进磁带。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 磁带格式版本号。以后字段变了，老磁带还能按版本号识别。
TAPE_VERSION = 1


def safe_name(text: str, limit: int = 80) -> str:
    """把任务名/变体名变成安全的文件名片段。

    磁带里的 task 名可能来自外部导入，若含 "/" 或 ".." 会写到目录之外；
    这里只保留字母数字、下划线、连字符、点和中日韩文字。
    """
    cleaned = re.sub(r"[^\w\-.一-鿿]+", "-", str(text or "task"))
    return cleaned.strip("-.")[:limit] or "task"


class Recorder:
    """收集一次运行的所有步骤，最后写成一份 tape JSON。"""

    def __init__(
        self,
        task_name: str,
        task_input: dict | None = None,
        task_requirements: list[str] | None = None,
        agent: str = "demo_agent",
        tapes_dir: Path | str | None = None,
        variant: str | None = None,
        model: str | None = None,
        provenance: dict | None = None,
    ) -> None:
        self.task_name = task_name
        self.task_input = task_input or {}
        self.task_requirements = task_requirements or []
        self.agent = agent
        self.tapes_dir = Path(tapes_dir) if tapes_dir else ROOT / "tapes"
        # 变体标记：同一个任务跑第几次、或者改 Prompt 的前后版本（v1/v2/baseline）
        self.variant = variant
        # 运行配置指纹：用的哪套 prompt / 模型 / 参数 / 工具（见 provenance.py）
        self.provenance = provenance or {}

        self.steps: list[dict] = []
        self.started_at = datetime.now().astimezone()
        # perf_counter 是单调时钟，不受系统时间被改动的影响，比 time.time 靠谱
        self._start = time.perf_counter()
        self._last = self._start

        # 记下用的是什么模型：以后行为变了，先看是不是模型换了。
        # 接入别的项目时可以显式传（它们的变量名不一定叫 LLM_MODEL）。
        self.model = model or os.getenv("LLM_MODEL", "")

    # -- 记录 ---------------------------------------------------------------

    def log(
        self,
        name: str,
        input: dict | None = None,
        output: dict | None = None,
        label: str | None = None,
    ) -> dict:
        """记一步。Agent 每做完一步就调一次。

        name   : 机器名，比如 generate_keywords（diff 对比靠它，要稳定）
        label  : 人看的名字，比如「规划关键词」（报告里显示它）
        input  : 这一步的输入，普通 dict
        output : 这一步的输出，普通 dict
        """
        now = time.perf_counter()
        step = {
            "index": len(self.steps) + 1,
            "name": name,
            "label": label or name,
            "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            # 距上一步结束的时间，也就是这一步自己花的时间
            "duration_ms": round((now - self._last) * 1000),
            "input": input or {},
            "output": output or {},
        }
        self._last = now
        self.steps.append(step)
        return step

    # -- 落盘 ---------------------------------------------------------------

    def finish(
        self,
        output: dict | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> Path:
        """收尾：补上结束时间、总耗时，把磁带写到 tapes/ 目录，返回文件路径。"""
        finished_at = datetime.now().astimezone()
        stamp = f"{self.started_at:%Y%m%d-%H%M%S}"
        task_part = safe_name(self.task_name)
        if self.variant:
            run_id = f"{task_part}-{safe_name(self.variant)}-{stamp}"
        else:
            run_id = f"{task_part}-{stamp}"

        tape = {
            "tape_version": TAPE_VERSION,
            "task": {
                "name": self.task_name,
                "input": self.task_input,
                "requirements": self.task_requirements,
            },
            "meta": {
                "run_id": run_id,
                "agent": self.agent,
                "model": self.model,
                "variant": self.variant,
                "provenance": self.provenance,
                "status": status,
                "error": error,
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "duration_ms": round((time.perf_counter() - self._start) * 1000),
                "step_count": len(self.steps),
            },
            "steps": self.steps,
            "output": output or {},
        }

        self.tapes_dir.mkdir(parents=True, exist_ok=True)
        path = self.tapes_dir / f"{run_id}.json"
        # 同一秒内跑多次（例如批量重复实验）时不要互相覆盖
        suffix = 2
        while path.exists():
            path = self.tapes_dir / f"{run_id}-{suffix}.json"
            suffix += 1
        path.write_text(
            json.dumps(tape, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return path