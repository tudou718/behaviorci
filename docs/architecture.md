# 架构说明

> 这份文档回答三个问题：系统由哪些部分组成、一次对比的数据怎么流动、
> 关键设计为什么这么定。看完应该能独立改代码。

---

## 1. 一句话架构

**把 Agent 的运行过程录成可比较的数据（磁带），再用「结构规则 + LLM 裁判」两层判断行为有没有变。**

```
                    ┌──────────────┐
   任务定义 ────────►│  record/replay │────► 磁带 JSON（tapes/）
   tasks/*.json     └──────────────┘              │
                                                  │
                    ┌──────────────┐              │
   两份磁带 ────────►│     diff      │◄─────────────┘
                    │ 结构 + 内容清点│
                    └──────┬───────┘
                           │ 有内容差异？
                    ┌──────▼───────┐
                    │    judge      │  3 次投票 → 等价/变好/漂移
                    │  LLM-as-Judge │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ report/pages  │  终端 + md + json + 网页
                    └──────────────┘
```

---

## 2. 数据：磁带长什么样

一份磁带就是一次运行的完整记录，`tapes/*.json`：

```json
{
  "tape_version": 1,
  "task": {
    "name": "daily-brief",
    "input": {"topic": "AI Agent 最新进展"},
    "requirements": ["输出 180-220 字", "覆盖三个角度", "不得编造", "结尾指出问题"]
  },
  "meta": {
    "run_id": "daily-brief-before-20261105-120000",
    "agent": "demo_agent",
    "model": "deepseek-v4.1-flash-1017",
    "variant": "before",
    "status": "ok",
    "duration_ms": 8123,
    "provenance": {
      "model": "deepseek-v4.1-flash-1017",
      "prompts": [{"name": "summary_system", "sha256": "…", "text": "…"}],
      "params": {"temperature_summary": 0.7},
      "tools": ["mock_search"]
    }
  },
  "steps": [
    {"index": 1, "name": "generate_keywords", "label": "规划关键词",
     "input": {"topic": "…"}, "output": {"keywords": ["…"]}, "duration_ms": 2018}
  ],
  "output": {"summary": "…"}
}
```

四个关键字段的分工：

| 字段 | 作用 | 为什么需要 |
|---|---|---|
| `steps[].input/output` | 行为本体 | 只看最终答案分不清「改写」和「少查一次」 |
| `meta.provenance` | 运行配置指纹 | 回答「为什么变」，而不是只知道「变了」 |
| `task.requirements` | 任务硬性要求 | 裁判据此判断「补齐缺失内容」算不算变好 |
| `output` | 最终交付物 | 结构检查判断「有没有交货」 |

---

## 3. 模块职责

```
main.py            统一入口：record / replay / compare / experiment / calibrate / stats
│
├── src/llm.py           所有模型调用的唯一入口；token 用量流水
├── src/recorder.py      把步骤写成磁带（失败也落盘、文件名防覆盖）
├── src/provenance.py    运行配置指纹：Prompt hash/全文、模型、参数、工具
├── src/demo_agent.py    被测试的 Agent（也是接入示例）
├── src/replay.py        多次重放；字段级并排查看
├── src/tape.py          磁带的读与通用比较（final_output_text、walk_diff）
├── src/diff.py          结构对比（3 项）+ 内容清点（源头/传染）+ 归因
├── src/judge.py         LLM 裁判：三选一、严格 JSON、N 次投票
├── src/toolreplay.py    工具输出确定性回放（按步骤名 + 输入匹配）
├── src/calibrate.py     用人工标注集校准裁判（一致率、混淆矩阵、kappa）
├── src/experiment.py    分布对比：组内噪声线 vs 组间相似度
├── src/report.py        Markdown / JSON 报告 + 自包含 payload
├── src/pages.py         报告渲染成静态 HTML
├── src/guide.py         接入指南渲染成独立网页
└── src/stats.py         磁带、判定分布、token 用量的汇总
```

依赖方向是单向的：`main → (diff/judge/experiment/calibrate) → (tape/provenance/llm)`。
底层模块不反向依赖上层，`recorder.py` 也不依赖 `llm.py`（它只读环境变量）。

---

## 4. 一次 compare 的调用链

```
main.py cmd_compare
  ├─ replay.load_tape(a), load_tape(b)
  ├─ diff.compare()
  │    ├─ check_step_count / check_tool_sequence / check_final_output   ← 本地规则
  │    ├─ content_changes()      ← walk_diff 找字段差异，区分源头/传染
  │    ├─ provenance.diff()      ← 两次运行的 Prompt/模型/参数差异
  │    └─ judge.judge_consensus(runs=3)
  │         └─ 每票：provenance + 结构信息 + 两份 tape_digest → 模型 → 严格 JSON
  ├─ diff.print_report()         ← 终端
  └─ report.save()               ← md + json + html 三份
```

关键点：**只要内容没有差异，就不调用裁判**（省钱）；裁判失败不会毁掉结构报告。

---

## 5. 关键设计决策

| 决策 | 取舍 |
|---|---|
| 磁带记录每步输入输出，而非只记最终答案 | 字段多、文件大，但能定位到「哪一步变的」 |
| 结构对比与语义裁决分离 | 结构塌了不用花钱；结构没问题才让裁判读内容 |
| 源头/传染判定 | 避免一个根因被报成多个问题；代价是依赖「输入=上一步输出」这一常见结构 |
| 裁判 3 次投票 + 票型 | 单次裁决等于抽签；2:1 本身是「该人工复核」的信号 |
| 记录配置指纹（Prompt 全文） | 能算相似度、能诊断；代价是磁带体积与提示词外泄风险 |
| 分布对比以基线噪声线为参照 | 比「两组平均」更不容易被候选自身不稳定稀释 |
| 校准集独立于裁判 | 用人工标注衡量裁判可信度；32 对含留出集，仍非独立第三方 |
| 工具回放（exact / name） | exact 严格但模型重生成计划时会打不中；name 能隔离模型，代价是假设工具调用可替换 |

---

## 6. 已知局限

1. **步骤按下标对齐**：如果候选插入或删除了一步，后续步骤会全部错位。正确做法是序列对齐（LCS）。
2. **裁判卷子有截断**：单段文本截到 500 字，超长交付物可能掩盖差异。
3. **分布阈值是经验值**：0.05 / 0.15 来自当前样本，不同 Agent 需要重新标定。
4. **工具回放按「步骤名 + 输入」匹配**：模型重新生成计划（例如关键词变化）时，
   `exact` 会打不中而回退真实工具；`name` 能命中，但前提是工具调用可互换。
4. **校准集 32 对**（dev 11 / test 21）由作者按构造方式标注，不是独立第三方；
   留出集 kappa 0.93，仍存在标注偏差与合成样本偏「明显」的问题。
5. **提示词全文进 Git**：公开仓库会暴露提示词；敏感项目应改为只存 hash。
6. **CI 每次都会调用模型**：公开仓库的 Actions 也在花 token，注意额度。

---

## 7. 想扩展时从哪里下手

- **接入新 Agent**：实现「每步调用 `Recorder.log`」即可，见 [接入指南](integration.md)
- **换裁判模型**：改 `.env` 的 `LLM_MODEL`；判定标准在 `src/judge.py` 的 `JUDGE_TEMPLATE`
- **加结构检查项**：在 `src/diff.py` 写一个 `check_*` 函数塞进 `compare()` 列表
- **改报告样式**：只动 `src/pages.py`，判定逻辑不受影响