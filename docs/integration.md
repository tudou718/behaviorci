# 接入指南：把 BehaviorCI 用到你自己的 Agent 上

> 这份文档写给第一次接触 BehaviorCI 的人。不需要读源码，照着做就能给自己的
> Agent 加上「行为回归测试」。遇到卡住的地方，先看最后的「常见问题」。

---

## 先说清楚它是什么

你的 Agent 每次干活，会做很多步：调工具、拿结果、写回答。

BehaviorCI 做的事只有一件：**把「这一次干活的过程」记下来，然后和另一次比。**

- 记下来的那份东西叫**磁带（tape）**，就是一个 JSON 文件
- 比较的时候，先看结构（步骤数、工具顺序、有没有交付），再看内容
- 最后请一个 LLM 当裁判，告诉你两次行为是**等价 / 变好 / 漂移**

它不能代替你的单元测试，也不能保证 Agent 永远不出错。它解决的是另一个问题：
**你改了 Prompt 或换了模型，怎么知道行为有没有偷偷变化。**

---

## 你需要准备什么

- Python 3.10 以上
- 一个能调模型的 Key（任何 OpenAI 兼容的服务都行：百炼、DeepSeek、OpenAI…）
- 大约 30 分钟

---

## 第一步：把 BehaviorCI 放到手边

```bash
git clone https://github.com/tudou718/behaviorci.git
cd behaviorci
pip install -r requirements.txt
cp .env.example .env        # 打开 .env，填 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
```

先确认它能跑：

```bash
python src/llm.py           # 应该输出：✓ 连通正常
```

---

## 第二步：在你的 Agent 里插记录器

只有两件事要做：**开始录**、**每做完一步记一笔**、**最后收尾**。

### 2.1 把记录器复制过去

把 `behaviorci/src/recorder.py` 复制到你项目的任意位置（比如
`observability/recorder.py`）。它只依赖 Python 标准库，不需要装别的包。

### 2.2 找一个「每一步都会经过」的地方

绝大多数 Agent 都有这样的地方：

- 工具调用的地方（每次调用前/后）
- 模型返回消息的地方
- 主循环里处理每个事件的地方

### 2.3 加三行代码

```python
from observability.recorder import Recorder

# ① 开始，把任务输入记下来
rec = Recorder(
    task_name="my-agent",              # 你的 Agent 叫什么
    task_input={"query": user_query},  # 这次任务问了什么
    tapes_dir="tapes",                 # 磁带存哪
)

# ② 每做完一步记一笔（在你的工具调用/消息处理处）
rec.log(
    "search",                          # 机器名，要稳定
    input={"query": keyword},          # 这一步吃进去什么
    output={"results": results},       # 这一步吐出来什么
    label="网络搜索",                   # 人看的名字
)

# ③ 收尾，把最终交付物也记上
rec.finish(output={"answer": final_answer})
```

就这样。跑一次你的 Agent，`tapes/` 里就会多一个 JSON 文件。

### 2.4 一个可以直接跑的最小例子

```python
from observability.recorder import Recorder

def run_my_agent(query):
    rec = Recorder("my-agent", {"query": query}, tapes_dir="tapes")
    try:
        keywords = call_llm("帮我想 3 个搜索关键词：" + query)   # 你的逻辑
        rec.log("plan", {"query": query}, {"keywords": keywords}, label="规划")

        results = my_search_tool(keywords)                    # 你的工具
        rec.log("search", {"keywords": keywords}, {"results": results}, label="搜索")

        answer = call_llm("根据资料回答：" + query)             # 你的逻辑
        rec.log("answer", {"query": query}, {"answer": answer}, label="回答")

        rec.finish(output={"answer": answer})                 # 收尾
        return answer
    except Exception as exc:
        # 出错了也要落盘：失败的那份磁带最有分析价值
        rec.finish(status="error", error=f"{type(exc).__name__}: {exc}")
        raise
```

**为什么要记「输入 + 输出」而不是只记结果？**
因为只看最终答案，你分不清「换个说法」和「少查了一次资料」——而后者才是真正的问题。

---

## 第三步：跑两次，看对比

```bash
# 1. 改 Prompt / 换模型之前，先录一份基线
python main.py record --label baseline

# 2. 改完再录一份候选
python main.py record --label new-prompt

# 3. 对比（默认裁判跑 3 次取多数）
python main.py compare tapes/<基线>.json tapes/<候选>.json --open
```

`--open` 会用浏览器打开一份**网页版报告**，里面有：

- 大标题写着 Final 判定（等价 / 变好 / 漂移）和理由
- 结构对比表格（✓ / ✗）
- 内容差异清单：哪一步变了、它是不是「源头」
- 裁判的每次投票和理由

报告同时存成三份：`reports/xxx.html`（给人看）、`.md`、`.json`（给 CI 看）。
不加 `--open` 也能在 `reports/` 里找到并用浏览器打开。

---

## 常见问题

**Q：两次结果都是「等价」，是不是没测出来？**
不是。**你什么都没改，行为当然等价**——这是工具正常工作。想看到「漂移」，
必须真的改动一个东西：提示词、模型、温度、工具实现。改完再比，才有意义。

**Q：我的交付物字段不叫 `summary` 怎么办？**
磁带的 `output` 里放什么都行。BehaviorCI 会依次找 `summary / final / answer /
text / result`，找不到就用第一个非空字符串——结构检查只关心「有没有交货」。

**Q：每次运行都有随机 ID / 时间戳，会不会全被当成差异？**
会，需要在记录前抹掉。参考智研搜的做法：

```python
def scrub(value, session_id):
    if isinstance(value, str):
        return value.replace(session_id, "<session>")
    if isinstance(value, dict):
        return {k: scrub(v, session_id) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, session_id) for v in value]
    return value
```

**Q：我的输出特别长，磁带会不会很大？**
记录前截断（比如保留前 2000 字）。磁带是拿来对比结构的，不是全文存档。

**Q：我重放了两次，结果一模一样，正常吗？**
如果两次跑出来的结果完全一致、连耗时都短得离谱（比如 0.2 秒），
很可能命中了模型网关的**响应缓存**。BehaviorCI 的做法是每次调用带一个唯一的
`user` 字段（见 `src/llm.py`），让缓存失效。

**Q：记录器挂了会不会拖垮我的服务？**
按上面的写法，记录发生在业务代码里，一定要用 `try/except` 包住，并且
`finish()` 本身不要抛异常。智研搜的适配层（`app/observability/behaviorci.py`）
就是在找不到 BehaviorCI 时自动降级成空操作。

---

## 接入检查清单

- [ ] 每次运行有唯一标识（写进 `task_input`，敏感/易变的部分做脱敏）
- [ ] 每一步都记录了 `name / input / output`
- [ ] 最后调了 `finish()`，并把最终交付物放进去
- [ ] 出错路径也调了 `finish(status="error")`
- [ ] 记录逻辑用 try/except 包住，失败不影响主流程
- [ ] 重放两次确认没有命中缓存（耗时是秒级，不是毫秒级）

---

## 参考实现

- 演示 Agent：`src/demo_agent.py`（最简版，三步）
- 真实项目：智研搜的
  [`app/observability/behaviorci.py`](https://github.com/tudou718/deepsearch-agents-learning/blob/main/app/observability/behaviorci.py)
  （LangGraph/deepagents，流式消息记录）