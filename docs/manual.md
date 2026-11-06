# BehaviorCI 操作手册

> 给项目所有者自己看的日常操作说明：怎么用、报告在哪、出问题怎么查。
> 第一次接入别人的项目，请看 [接入指南](integration.md)。

---

## 0. 一分钟速查

| 我想… | 命令 | 会调模型吗 |
|---|---|---|
| 录一份磁带 | `python main.py record --label before` | 会（2 次） |
| 批量重放、做分布对比 | `python main.py replay --runs 2 --labels a,b --repeat 3` | 会（每轮 2 次） |
| 对比两份磁带并出报告 | `python main.py compare A.json B.json --open` | 会（裁判 3 次） |
| 只看结构、不花钱 | `python main.py compare A.json B.json --no-judge` | 不会 |
| 判断漂移还是抖动 | `python main.py experiment --task daily-brief --baseline a --candidate b` | 不会 |
| 校准裁判 | `python main.py calibrate` | 会（32 对 × 3 票） |
| 只跑留出集校准 | `python main.py calibrate --split test` | 会 |
| 工具输出确定性回放 | `python main.py record --replay-from tapes/x.json --replay-match name` | 会（仅模型） |
| 看总量与花费 | `python main.py stats` | 不会 |
| 生成接入指南网页 | `python src/guide.py` | 不会 |
| 跑单元测试 | `python -m unittest discover -s tests -v` | 不会 |

解释器不是系统默认的 `python` 时，用绝对路径替换，例如本机：
`/Users/xinpingyang/.workbuddy/binaries/python/envs/default/bin/python`。

---

## 1. 环境配置

`.env`（不进 Git）：

```
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-v4.1-flash-1017
```

自检：

```bash
python src/llm.py      # ✓ 连通正常
```

---

## 2. 最常用的三条工作流

### A. 改了 Prompt，确认没改坏

```bash
# 1) 改之前，录一份基线
python main.py record --label before

# 2) 改代码（Prompt / 模型 / 参数）

# 3) 改完再录一份
python main.py record --label after

# 4) 对比并打开网页报告
python main.py compare $(ls -t tapes/*-before-*.json | head -1) \
                       $(ls -t tapes/*-after-*.json | head -1) --open
```

报告里看三处：**最终判定**、**本次变更**（是哪个 Prompt 改了、相似度多少）、**内容差异**。

### B. 分不清「漂移」还是「这次手气不好」

单次比较不够，跑分布：

```bash
python main.py replay --runs 2 --labels base,new --repeat 3
python main.py experiment --task daily-brief --baseline base --candidate new
```

判读：
- 组间相似度 ≈ 基线噪声线 → 抖动，未见漂移
- 组间明显低于噪声线 → 漂移
- 候选组自身相似度低 → 这个变体本来就不稳定

### C. 怀疑裁判判得不准

```bash
python main.py calibrate                 # 全部 32 对
python main.py calibrate --split test    # 只看留出集（评估是否过拟合）
```

看一致率、Cohen's kappa、混淆矩阵。标注在 `calibration/cases.json`，
**标注必须在跑裁判前定好**，否则校准没有意义。

---

### D. 只想让模型成为唯一变量

工具（搜索 / 数据库）本身也会变。用基线磁带里的工具输出回放：

```bash
python main.py record --label after --replay-from tapes/<基线>.json --replay-match name
```

- `--replay-match exact`（默认）：输入必须完全一致，最严格
- `--replay-match name`：只要求步骤名一致，适合模型重新生成了计划的场景

回放命中的步骤会被标记在运行配置指纹里（`params.tool_replay`），报告可追溯。

## 3. 产物都在哪

| 路径 | 内容 | 进 Git |
|---|---|---|
| `tapes/*.json` | 行为磁带（基线） | 是 |
| `tapes/experiments/` | 分布实验的磁带 | 是 |
| `tapes/examples/` | 案例磁带（如故意漂移） | 是 |
| `calibration/tapes/` | 校准集里的构造样本 | 是 |
| `reports/*.html/.md/.json` | 对比报告、校准报告 | 否 |
| `reports/usage.jsonl` | token 用量流水 | 否 |
| `_site/` | 网页构建产物 | 否 |

公开页面：
- 巡检报告：https://tudou718.github.io/behaviorci/
- 接入指南：https://tudou718.github.io/behaviorci/guide.html

---

## 4. 维护

### 轮换模型 Key

```bash
# 本地
# 编辑 .env 的 LLM_API_KEY
python src/llm.py

# GitHub Actions
gh secret set LLM_API_KEY --repo tudou718/behaviorci     # 终端里粘贴
```

### 基线是怎么选的（CI）

CI 每次录一份 `daily-brief` 候选，然后取**同一任务名下、已提交的、非 ci- 变体**的
最新磁带作为基线。`tapes/experiments/` 与 `calibration/` 不参与，避免拿实验样本当基线。

### 清理报告

`reports/` 已被 `.gitignore` 排除，可以随时删；`usage.jsonl` 删了会重置用量统计。

---

## 5. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `401 Authentication` | Key 失效 / 换过 / 网关不认 | 更新 `.env` 或 GitHub Secret；`python src/llm.py` 验证 |
| `模型返回空内容（finish_reason=length）` | 推理吃光 `max_tokens` | 调大该值（裁判已设 8000） |
| 两次运行 0.3 秒且完全一样 | 命中网关响应缓存 | 已有唯一 cache key；若自行接入，记得每次换 `user` |
| `两份磁带的任务名不一样` | 拿错任务的文件 | 用同一 `--task` 产出的磁带 |
| CI `选基线磁带` 失败 | 没有同任务的已提交磁带 | 先 commit 一份基线 |
| CI 没被触发 | 变更路径不在 `on.push.paths` | 手动 `gh workflow run behaviorci.yml` |
| Pages 404 | 部署还在跑 / 失败 | 看 Actions 的 `deploy-pages` 步骤 |

---

## 6. 名词表

| 名词 | 意思 |
|---|---|
| 磁带（tape） | 一次运行的完整流水账 JSON：任务、模型、每步输入输出、耗时 |
| 变体（variant） | 磁带上的标签，如 `before` / `after` / `baseline` |
| 源头步骤 | 输入相同但输出变化的那一步，是差异的根因 |
| 上游传染 | 某步的输出变化来自上一步的输出变化，不是它自己变了 |
| 噪声线 | 同一变体多次运行时的组内相似度，用来判断差异是否只是抖动 |
| kappa | 扣掉「随机也能蒙对」之后的裁判一致度，>0.6 一般认为可信 |
| 运行配置指纹 | 磁带里记录的 Prompt hash/全文、模型、参数、工具清单 |