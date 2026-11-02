# BehaviorCI

给 Agent 装上「行为回归 CI」——Prompt 是代码，Agent 行为就该有 CI。

## 它解决什么问题

Agent 的输出是不确定的：改一行 Prompt、换一个模型，行为可能在看不见的地方漂移。
BehaviorCI 把 Agent 每次任务的完整行为录制下来（行为磁带 tape），
在 Prompt / 模型 / 依赖变更后重放并做**语义级对比**，
用 LLM-as-Judge 给出人话结论：等价、变好了，还是行为漂移了。

## 项目结构（当前骨架）

```
behaviorci/
├── main.py       # 统一入口：record / replay / compare
├── src/          # demo_agent / recorder / replay / diff / judge / report / llm / tape
├── tasks/        # 任务定义（JSON）
├── tapes/        # 行为磁带（JSON，进 Git 作为基线）
├── reports/      # 漂移报告
├── .env          # 环境配置（LLM_API_KEY 等，不进 Git）
└── requirements.txt
```

## 环境

- Python：`/Users/xinpingyang/.workbuddy/binaries/python/envs/default/bin/python`（已装 openai / python-dotenv）
- 配置：`.env` 里的 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`

## 一条命令跑完

BehaviorCI 的流程是「录 → 放 → 比 → 报告」：先录一份基线磁带；改 Prompt 或换模型后，
用同样的任务重放一次；结构对比确认骨架没塌；最后让裁判读内容，给出「等价 / 变好 / 漂移」
的结论。报告写到 `reports/`，一份 Markdown 给人看，一份 JSON 给 CI 用。

```bash
python main.py record                                   # 录基线（跑一次任务）
python main.py replay --runs 2 --labels baseline,new    # 重放两次，并排看差异
python main.py compare tapes/<基线>.json tapes/<候选>.json   # 对比 + 裁判 + 出报告
```

`compare` 默认裁判跑 3 次取多数；判定为漂移时想让它以非零退出码失败，加 `--fail-on-drift`。

## 分步工具（调试或只跑某一段时用）

```bash
# 主题 → 3 个关键词 → 模拟搜索 → 200 字摘要（默认录磁带）
python src/demo_agent.py "AI Agent 最新进展"

# 同一次运行，输出结构化结果（含磁带路径）
python src/demo_agent.py "AI Agent 最新进展" --json

# 只跑不录，不生成磁带
python src/demo_agent.py "AI Agent 最新进展" --no-record

# 同一任务跑两次，生成 v1/v2 两份磁带并并排展示
python src/replay.py
python src/replay.py --runs 3 --labels baseline,new-prompt,new-prompt-2

# 只并排查看两份已有磁带（不重跑、不花 token）
python src/replay.py --compare tapes/a.json tapes/b.json

# 结构对比 + 裁判（默认裁判跑 3 次取多数）
python src/diff.py tapes/a.json tapes/b.json
python src/diff.py tapes/a.json tapes/b.json --judge-runs 5
python src/diff.py tapes/a.json tapes/b.json --no-judge   # 只看结构
python src/diff.py tapes/a.json tapes/b.json --json

# 想看裁判自相矛盾长什么样（温度默认 0，调高后分歧会变多，仅用于观察）
JUDGE_TEMPERATURE=0.9 python src/diff.py tapes/a.json tapes/b.json
```

每跑一次，`tapes/` 下会多一份 `daily-brief-YYYYMMDD-HHMMSS.json`，
记录任务、模型、每一步的输入输出和耗时。

> 解释器路径见上方「环境」一节。搜索这一步目前是**固定的假数据**，
> 为的是让后续重放时的差异只来自模型本身。

## 自动巡检（GitHub Actions）

`.github/workflows/behaviorci.yml`：手动点按钮，或改动了任务定义 / 源码 / 基线磁带后自动触发。
每次运行会录一份候选磁带，与仓库里最新的基线磁带对比，把报告写进运行摘要并可下载。

需要在仓库 Settings → Secrets and variables → Actions 配置三个变量：
`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`（本机 `.env` 不会进仓库）。

## 路线图

- [x] D1 骨架与配置
- [x] D2 demo Agent（搜索 → 摘要）
- [x] D3 行为磁带 recorder
- [x] D4 replay（同一任务多次重放，观察不确定性）
- [x] D5 diff v1（结构对比：步骤数 / 工具序列 / 最终输出非空）
- [x] D6 Judge（LLM-as-Judge：等价 / 变好 / 漂移）
- [x] D7 分布校验（裁判跑 3 次取多数，记录分歧）
- [x] D8 CLI 闭环（main.py：record / replay / compare + 报告）
- [x] D9 GitHub Actions（手动/变更触发，报告进运行摘要 + 产物）
- [ ] D10 Pages 报告
- [ ] D11–13 接入真实项目（智研搜）+ README + v0.1 发布
