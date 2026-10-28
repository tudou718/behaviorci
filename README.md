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
├── src/          # 代码（D2 起：demo_agent.py、recorder、diff）
├── tasks/        # 任务定义（JSON）
├── tapes/        # 行为磁带（JSON，进 Git 作为基线）
├── reports/      # 漂移报告
├── .env          # 环境配置（DEEPSEEK_API_KEY，不进 Git）
└── requirements.txt
```

## 环境

- Python：`/Users/xinpingyang/.workbuddy/binaries/python/envs/default/bin/python`（已装 openai / python-dotenv）
- 配置：`.env` 里的 `DEEPSEEK_API_KEY`

## 路线图

- [x] D1 骨架与配置
- [ ] D2 demo Agent（搜索 → 摘要）
- [ ] D3 行为磁带 recorder
- [ ] D4–8 replay / diff / Judge / 分布校验 / CLI 闭环
- [ ] D9–10 GitHub Action + Pages 报告
- [ ] D11–13 接入真实项目（智研搜）+ README + v0.1 发布
