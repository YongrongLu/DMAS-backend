# Retail Rescue — 实施方案

> 需求见 [prd.md](prd.md)。基础代码来自 `~/Desktop/AnimeRec/distributed_mas_validation`（下文称"验证项目"）。
> 本文档说明代码怎么写、按什么顺序写；具体参数以实现时的代码为准，实现中如有调整，回来更新本文档。

---

## 0. 一页摘要

- **4 个 Agent**：1 个 Orchestrator，加 Sales / Customer / Product 3 个部门 Agent。它们分别运行在 4 台设备上，通过 WebSocket hub 组网。
- **1 个模型**：一个 vLLM 实例运行 NVIDIA Nemotron 3.5 Lightning 30B-A3B（总参数约 31.6B），4 个 Agent 共用，总参数 < 33B。
- **工具很少**：
  - Orchestrator 只有 5 个控制工具；
  - 部门 Agent 只有 `load_skill` 和 `shell_executor` 两个工具，所有分析能力都做成 **Skill**，需要时再加载。
- **隐私边界写在代码里**：
  - 原始 CSV 只存在于所属设备上；
  - `shell_executor` 只能运行 Skill 脚本；
  - Skill 脚本只输出聚合结果；
  - 结果进入 LLM 上下文之前、离开设备之前，各有一道确定性检查。
- **大部分运行时直接复用验证项目**：hub、protocol、主图、worker 子图、plan 和 fanout 工具。需要新写的是：数据视图、Skills、`shell_executor`、隐私策略和各个 prompt。

---

## 1. 硬性约束与对应做法

| 约束 | 做法 |
|---|---|
| 必须使用 Nemotron Lightning | 用 `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`，沿用验证项目已经跑通的 vLLM 启动参数（`--reasoning-parser nemotron_v3 --tool-call-parser qwen3_coder --enable-auto-tool-choice`） |
| 总参数 ≤ 33B | 4 个 Agent 共用同一个模型实例，共 31.6B。**不再部署任何其他模型**（embedding、guard、Nano 都不行，余量只有约 1.4B），所以隐私检查必须写成确定性代码，不能靠另一个 LLM |
| 推理引擎用 vLLM，部署在租来的 GPU 上 | 在 Brev 上租 H100，跑 vLLM，通过 Tailscale 只对团队设备开放 |
| 使用 Open Dataset | UCI Online Retail II，由它派生出三份部门 CSV（§7） |
| 分布式、跨部门协作 | 每个部门一台设备，Orchestrator 内嵌 hub（§9.6） |
| 原始数据不集中 | 见 §6 |

> **关于"每个 Agent 8B"**：Lightning 只有 30B-A3B 这一个尺寸，没有 8B 版本。如果每个 Agent 用一个 8B 模型，就只能换成别的模型，这和"必须用 Lightning"冲突。共享一个 Lightning 实例可以同时满足两条要求。
>
> 代码里每个角色的 model 和 base_url 都可以单独配置（§9.1）。如果规则的解释有变化，只需要改 `.env`。**建议找主办方确认一下参数是怎么计数的。**

---

## 2. 总体架构

```
              CEO 笔记本：Orchestrator + 内嵌 hub（ws://<ip>:8800）
                 │   task（部门问题）/ result（部门结论）   ← 只传这两种消息
      ┌──────────┼──────────────────┐
  Sales 设备     Customer 设备       Product 设备
  sales.csv      customers.csv       products.csv          ← 原始数据只在这里
  skills/*       skills/*            skills/*
      └──────────┴────────┬─────────┘    （4 个进程都调用同一个 endpoint）
         租用 GPU：vLLM · Nemotron 3.5 Lightning 30B-A3B（唯一的模型）
```

**信任边界：谁能看到什么**

| 位置 | 能看到 | 看不到 |
|---|---|---|
| 部门设备上的 Skill 脚本子进程 | 本部门的完整 CSV | 其他部门的数据 |
| 部门 Agent 的 LLM 上下文（在 GPU 上推理） | 任务描述、Skill 文档、Skill 脚本输出的**聚合结果** | 原始行 |
| Orchestrator | 各部门的最终结论（≤ 3000 字符） | 部门的工具输出、原始数据 |
| hub 网络链路 | task / result 消息 | 原始数据 |

如果评委问"数据是不是发到 GPU 上了"：原始行从来没有进过 LLM 上下文，到 GPU 的只有聚合值。所以 §5.5 和 §6 的规则是整个隐私故事的基础。

---

## 3. 从验证项目复用什么

目录名沿用本仓库已经建好的骨架（`core/middlewares`、`core/agents/worker`），不用验证项目里的 `middleware` / `workers`。

| 验证项目 | 本项目 | 处理方式 |
|---|---|---|
| `distributed/protocol.py` | 同名 | 原样复制；REGISTER 加一个可选字段 `capabilities` |
| `distributed/hub.py` | 同名 | 原样复制；注册时保存 `capabilities`，`online_agents()` 一并返回 |
| `distributed/agent.py` | 同名 | 修改：CLI 改成 `--department/--data`；按 DepartmentSpec 构建图；去掉 `close_crawler` |
| `distributed/orchestrator.py` | 同名 | 修改：默认问题换成 CEO 问题；新增 `--interactive` 多轮模式 |
| `distributed/task_console.py`、`constants.py` | 同名 | 原样复制；console 增加 🔒 行的显示 |
| `core/agents/graph.py` | 同名 | 修改：部门子图改为参数传入（§9.4） |
| `core/agents/state.py`、`remote_agent.py`、`utils.py` | 同名 | 原样复制；`render_online_agents_block` 改为渲染能力卡 |
| `core/agents/orchestrator.py`、`announce.py` | 同名 | 小改：去掉 workspace 注入，换成新的 prompt |
| `core/agents/model.py`、`constants.py` | 同名 | 精简：只保留 OpenAI 兼容的 vLLM provider，每个角色可单独配置 |
| `core/agents/workers/{graph,llm,prepare,summarize,state}.py` | `core/agents/worker/` | 原样复制；`graph.py` 增加可选的 `post_summarize_node`，迭代上限改为参数传入 |
| `core/agents/workers/worker_registry.py` | `core/agents/worker/worker_registry.py` | 重写：`build_department_graph(spec, data_path)` |
| `core/middleware/{control_tool_node,identity_injection,orchestration_callback,constants}.py` | `core/middlewares/` | 原样复制；constants 里的角色改为三个部门 |
| `core/tools/_kernel/_plan.py` | 同名 | 原样复制 |
| `core/tools/_kernel/_orch_control.py` | 同名 | 小改：去掉 `pause_orchestration` 和 `project_dir` |
| `core/tools/_kernel/sandbox/{executor,profile}.py` | 同名 | 复用异步子进程、杀进程组、环境变量清理，以及 air-gapped profile |
| `core/tools/_kernel/constants.py` | 同名 | 只保留 plan、orch_control、sandbox 相关的部分，并加入 skill 相关常量 |
| `core/tools/descriptions/{plan,orch_control}.py` | 同名 | 复制；fanout 的描述改写 |
| `core/tools/bundles/orchestrator.py` | 同名 | 精简为 5 个工具 |
| `core/prompts/system_prompt_{orchestrator,announce}.py` | 同名 | 重写内容，保留结构（系统提示词前缀不变 + 尾部状态快照） |
| `utils/{settings,logging,console}.py` | 同名 | settings 精简；logging 和 console 原样复制 |
| `scripts/test_tool_calling.py` | 同名 | 复制；增加 `load_skill → shell_executor` 两步调用的检查 |
| `tests/test_plan_*`、`test_orch_control_{end_orchestration,fanout_subagent}`、`test_orchestrator_no_tool_call_guard`、`test_distributed_runtime`、`conftest`、`helpers` | `tests/` | 复制后按新角色修改断言；conftest 去掉 web 相关的 fixture |
| `_fs_readonly`、`_fs_mutate`、`_web`、`_bash`、programmer/researcher/reviewer 的 bundles 和 prompts | — | **不复制** |

---

## 4. 目录结构

```
distributed-mas-demo/
├── docs/
│   ├── prd.md
│   └── implementation-plan.md
├── data/
│   ├── README.md                     # Data card：来源、许可、字段定义、派生逻辑（Demo 时展示）
│   ├── raw/                          # online_retail_II.xlsx（不进 git）
│   └── departments/                  # 生成的部门 CSV（不进 git，每台设备只拷贝自己那一份）
├── scripts/
│   ├── download_dataset.py
│   ├── eda_find_decline.py
│   ├── build_department_views.py
│   ├── run_department.py             # 单个部门的本地调试入口（Phase 2）
│   ├── run_local.py                  # 单进程运行 4 个 Agent（Phase 3）
│   └── test_tool_calling.py
├── skills/                           # 部门 Agent 能加载的分析技能
│   ├── dataset-profile/{SKILL.md, scripts/profile.py}
│   ├── aggregate-query/{SKILL.md, scripts/aggregate.py}
│   ├── time-trend/{SKILL.md, scripts/trend.py}
│   ├── period-comparison/{SKILL.md, scripts/compare.py}
│   ├── anomaly-detection/{SKILL.md, scripts/anomalies.py}
│   ├── customer-retention/{SKILL.md, scripts/retention.py}
│   └── data-access-request/{SKILL.md, scripts/request_export.py}
├── core/
│   ├── departments/                  # 每个部门的唯一定义
│   │   ├── base.py                   #   DepartmentSpec / Metric
│   │   ├── sales.py
│   │   ├── customer.py
│   │   └── product.py
│   ├── data/                         # Skill 脚本共用的数据层（纯 pandas）
│   │   ├── loader.py
│   │   ├── filters.py
│   │   ├── metrics.py
│   │   ├── policy.py
│   │   ├── output.py
│   │   └── cli.py
│   ├── agents/
│   │   ├── graph.py, state.py, orchestrator.py, announce.py, remote_agent.py
│   │   ├── model.py, utils.py, constants.py
│   │   └── worker/
│   │       ├── graph.py, llm.py, prepare.py, summarize.py, state.py
│   │       └── worker_registry.py
│   ├── middlewares/
│   │   ├── control_tool_node.py, identity_injection.py, orchestration_callback.py, constants.py
│   │   └── egress_guard.py           # 新写：结果离开设备前的检查
│   ├── prompts/
│   │   ├── system_prompt_orchestrator.py
│   │   ├── system_prompt_department.py
│   │   └── system_prompt_announce.py
│   └── tools/
│       ├── _kernel/
│       │   ├── _plan.py, _orch_control.py, constants.py
│       │   ├── _skills.py            # 新写：Skill 注册表和 load_skill
│       │   ├── _shell_executor.py    # 新写：受限执行器
│       │   └── sandbox/{executor.py, profile.py}
│       ├── descriptions/{plan.py, orch_control.py, skills.py}
│       └── bundles/
│           ├── orchestrator.py
│           └── department.py         # build_department_tools(spec, data_path)
├── distributed/{protocol, hub, agent, orchestrator, task_console, constants}.py
├── utils/{settings, logging, console}.py
├── tests/
├── .env.example
└── requirements.txt
```

---

## 5. 工具与 Skills

### 5.1 Orchestrator 工具（5 个，全部复用）

| 工具 | 说明 |
|---|---|
| `make_plan` / `edit_plan` / `delete_plan` | 原样复用。计划会显示在 console 上，让观众看到"系统先拆解问题"（PRD §6） |
| `fanout_subagents` | `AVAILABLE_SUBAGENT_PREFIXES = ["sales", "customer", "product"]`；device_id 在分布式模式下必填；去掉 `project_dir`，少一个字段，模型就少一个填错的机会 |
| `end_orchestration` | 原样复用。图只有在调用它之后才会进入 announce，所以必须保留 |

`ControlAwareToolNode` 原样复用：每轮最多执行一个控制工具。

### 5.2 部门 Agent 工具（2 个，新写）

| 工具 | 签名 | 作用 |
|---|---|---|
| `load_skill` | `load_skill(name: <本部门可用 skill 的 enum>)` | 返回 SKILL.md 的正文（不含 frontmatter）和可以运行的脚本列表 |
| `shell_executor` | `shell_executor(command: str, timeout: int = 30)` | 运行 Skill 脚本，返回脚本输出的标准 JSON（规则见 §5.5） |

**渐进式加载**：system prompt 里只放每个 skill 的 `name` 和一行 `description`，完整的 SKILL.md 要调用 `load_skill` 才会进入上下文。这样可以省上下文，对小模型更友好。

### 5.3 Skill 格式

```
skills/time-trend/
├── SKILL.md
└── scripts/
    └── trend.py
```

SKILL.md 的示例（每个控制在 1500 字符以内）：

```markdown
---
name: time-trend
description: 按日/周/月查看某个指标的走势和环比变化。用于回答"什么时候开始下降""哪个时间段变化最大"。
departments: [sales, customer, product]
---
## 何时使用
需要看一个指标随时间的变化，或者找出变化最大的时间段。

## 用法
python skills/time-trend/scripts/trend.py --metric <metric> --freq month
    [--start YYYY-MM] [--end YYYY-MM] [--group-by <dimension>] [--top-groups 5]
    [--filter "<dimension>=<value>"]...

## 参数
- metric / dimension 必须使用 system prompt 数据卡里列出的名字
- --filter 可以重复；运算符：= != > >= < <= in（in 的值用逗号分隔）

## 输出怎么读
- rows 里每行是一个时间段：value 是指标值，pop_change 是环比变化
- notes 会标出不完整的时间段，下结论时必须考虑

## 常见错误
- 指标名写错 → 脚本会返回可用的指标列表，改正后重试一次
```

脚本的骨架（逻辑写在 `run()` 里，方便单测时直接 import）：

```python
# skills/time-trend/scripts/trend.py
from core.data.cli import build_parser, load_context, emit

def run(ctx, metric, freq, start, end, group_by, top_groups, filters) -> dict:
    """ctx 包含 spec 和 DataFrame；返回标准结果 dict（§5.6）。"""
    ...

def main():
    parser = build_parser(metric=True, freq=True, period=True, group_by=True, filters=True)
    ctx, args = load_context(parser)   # 从环境变量 DEPT_NAME / DEPT_DATA_PATH 读取部门和数据路径
    emit(run(ctx, **vars(args)))       # emit 统一经过 policy 检查，再打印标准 JSON

if __name__ == "__main__":
    main()
```

### 5.4 Skill 清单

| Skill | 能力（对应 PRD §11） | 部门 |
|---|---|---|
| `dataset-profile` | 字段、粒度、行数、时间范围（标出不完整的月份）、维度的取值个数、指标定义、基础统计。**不返回原始行** | 全部 |
| `aggregate-query` | 筛选、分组、sum/mean/count/nunique、排序、Top N | 全部 |
| `time-trend` | 时间趋势和环比 | 全部 |
| `period-comparison` | 比较两个时间段：差值、变化率、**每组对总变化的贡献和累计占比**。对 revenue 不分组时，还会把变化拆成"订单数的影响"和"AOV 的影响" | 全部 |
| `anomaly-detection` | 计算环比变化的 z-score，找出超过阈值的时间段或分组 | 全部 |
| `customer-retention` | A 期活跃的客户中，B 期留存、流失、新增的人数和营收，可按 segment 或 country 分组。客户 ID 只在脚本内部用来求集合 | customer |
| `data-access-request` | 把"给我原始数据"变成一次正式的数据访问申请。MVP 阶段的策略固定为拒绝行级导出，并给出可以改用的聚合分析（§6.2） | 全部 |

这些 Skill 怎么回答 PRD §4 里的问题：

- "销售什么时候开始下降""哪个时间段变化最大"：`time-trend`、`anomaly-detection`
- "哪些市场 / 哪些 SKU 贡献了主要下降""是不是少数 SKU 造成的"：`period-comparison`（看贡献和累计占比）
- "是订单数量下降还是订单金额下降"：`period-comparison`（看 revenue 的拆分）
- "是否正在失去重要客户""高价值客户是否减少购买"：`customer-retention`、`period-comparison`（按 segment 分组）
- "哪些商品退货率较高"：`aggregate-query`（按 return_rate 排序）

### 5.5 `shell_executor` 规则

`shell_executor` 是一个**受限执行器**：命令写法和 shell 一样，可以直接照抄 SKILL.md 里的用法行，但只能运行 Skill 脚本。

1. **解析**：用 `shlex.split` 拆分命令。命令里只要出现 `| ; & > < $ \``，或者换行，就直接拒绝。命令不经过 shell，以 `subprocess` exec 的方式运行。
2. **解释器**：第一个 token 必须是 `python`，执行时替换成 Agent 自己的 `sys.executable`。
3. **脚本路径**：第二个 token 必须是 `skills/<skill>/scripts/<file>.py`。取 `realpath` 后，路径必须在 `skills/` 目录内，而且这个 skill 必须对本部门开放（看 frontmatter 里的 `departments`）。
4. **参数**：剩下的 token 原样传给脚本，由脚本用 argparse 加 DepartmentSpec 校验。
5. **环境变量**：只传 `PATH`、`PYTHONPATH=<项目根目录>`、`DEPT_NAME`、`DEPT_DATA_PATH`。数据路径由执行器注入，模型既看不到也不能传入。所有带 key/token 的变量都去掉（复用 `SANDBOX_SENSITIVE_ENV_KEYWORDS` 的逻辑）。
6. **沙箱**：在 macOS 上，用验证项目的 seatbelt **air-gapped** profile 包一层，禁止联网，这样脚本即使读到数据也发不出去。其他系统直接用普通子进程。
7. **超时**：默认 30 秒，超时就杀掉整个进程组（复用 `sandbox/executor.py` 里 `_exec_async` 的做法）。
8. **输出闸门**：stdout 必须是标准 JSON（§5.6），而且要先通过 `policy.check_output` 才能返回给 LLM，条件是：
   - 行数 ≤ `MAX_RESULT_ROWS`（25）；
   - 字符数 ≤ `SKILL_OUTPUT_MAX_CHARS`（6000。验证项目 bash 的 806 字符放不下一张表）；
   - 不包含本地的 customer_id。

   不满足就返回 `denied`。
9. **非零退出码**：把截断后的 stderr 末尾返回给模型，让它修正参数后重试。
10. **审计**：每次拒绝都写一条结构化日志，并在设备终端打印 `🔒 POLICY DENIED: <原因>`。

**为什么不开放任意 shell 或任意 Python（需要确认的设计决定）**：

- **隐私**：只要有 `cat customers.csv` 或 `print(df)`，原始行就会进入 LLM 上下文，到达 GPU，甚至可能被带回给 Orchestrator。输出过滤很难拦住所有泄露的形式。
- **小模型**：Lightning 激活参数约 3B。让它每次现写 pandas 代码，不如让它带参数调用一个已经测过的脚本可靠。
- **可复现**：同样的问题，每次得到同样的数字，方便彩排和核对。

后续可以扩展一个"临时 Python 模式"：按部门开关，默认关闭，Customer 部门永远不开。模型写的代码依然通过执行器运行，并经过同一个输出闸门。

### 5.6 共享数据层 `core/data/`

Skill 脚本本身很薄，共用的逻辑放在这里，这样新增一个 Skill 不需要改 core。

| 文件 | 职责 |
|---|---|
| `loader.py` | 只读加载 CSV（进程内缓存）、解析日期、按 DepartmentSpec 校验列 |
| `filters.py` | 解析 `--filter "country=Germany"`，按白名单检查列名和运算符 |
| `metrics.py` | 计算命名指标：`sum` / `nunique` / `ratio`。比率一律用"总和之比"，例如 AOV = Σrevenue / Σorders，绝不对每行的 AOV 求平均 |
| `policy.py` | 输入检查（PII 列不能出现在 group_by 或 filter 里）、k-匿名隐藏、行数截断、构造 `deny()` 结果、给执行器用的 `check_output()` |
| `output.py` | 构造标准结果：保留两位小数，附上 `source` |
| `cli.py` | Skill 脚本共用的 argparse 参数、从环境变量读取上下文、`emit()` |

DepartmentSpec 的草图：

```python
@dataclass(frozen=True)
class Metric:
    name: str
    kind: Literal["sum", "nunique", "ratio"]
    column: str | None = None          # sum / nunique 用
    numerator: str | None = None       # ratio：分子的指标名
    denominator: str | None = None     # ratio：分母的指标名
    description: str = ""

@dataclass(frozen=True)
class DepartmentSpec:
    name: str                          # "sales" / "customer" / "product"；同时是 role 和 subagent_id 的前缀
    display_name: str
    csv_name: str
    date_column: str
    dimensions: dict[str, str]         # 可以 group_by / filter 的列 -> 说明
    metrics: dict[str, Metric]
    pii_columns: frozenset[str]        # customer: {"customer_id"}
    k_anon_column: str | None          # customer: "customer_id"；其他部门为 None
    k_anon_min: int = 5
    capability: str = ""               # 注册时发给 Orchestrator 的能力卡
    example_questions: tuple[str, ...] = ()
```

标准结果 JSON（Skill 脚本的 stdout 和 `shell_executor` 的返回值用同一种格式）：

```json
{
  "status": "ok | error | denied",
  "skill": "period-comparison",
  "message": "revenue, <period_b> vs <period_a>, by country",
  "columns": ["country", "period_a", "period_b", "delta", "pct_change", "contribution", "cum_share"],
  "rows": [["...", "...", "...", "...", "...", "...", "..."]],
  "notes": ["<不完整月份 / 被隐藏的分组 / 数据缺口>"],
  "source": "sales.csv · derived from UCI Online Retail II"
}
```

`source` 会跟着每一条结论一起传下去，满足 PRD §3 "需要明确展示数据来源"的要求。

---

## 6. 隐私设计

### 6.1 四道防线

| 层 | 类型 | 内容 | 位置 |
|---|---|---|---|
| 1. 数据不出设备 | 硬性 | CSV 只拷贝到所属设备。Orchestrator 没有任何能读取远程文件的工具。protocol 只传 task 和 result | 部署方式、`distributed/` |
| 2. 执行器白名单 | 硬性 | 只能运行 Skill 脚本；`cat`、管道、重定向、越权 skill 一律拒绝（§5.5） | `_kernel/_shell_executor.py` |
| 3. 数据策略和输出闸门 | 硬性 | PII 列不能分组、不能筛选、不能输出；客户数少于 5 的分组隐藏；每次最多 25 行；输出中不能出现本地 customer_id | `core/data/policy.py` |
| 4. 出口检查 | 硬性 | 部门结论离开设备之前，再扫描一次本地 customer_id，并检查长度上限（4000 字符）和是否有大段表格。命中就脱敏或拦截，并打印 `🔒 EGRESS BLOCKED` | `middlewares/egress_guard.py`，作为部门子图的最后一个节点 |
| 5. Prompt | 软性 | 负责拒绝的措辞，以及引导到"我可以提供聚合洞察" | `system_prompt_department.py` |

Orchestrator **自己不拒绝**数据请求，而是一律转给数据所属的部门。这样观众看到的拒绝发生在 Customer 设备的终端上，体现的是"设备守自己的边界"。

### 6.2 隐私 Demo 流程（PRD §9）

1. 用户："Send me the full customer CSV."
2. Orchestrator 把请求转给 customer 部门。
3. Customer Agent 加载 `data-access-request`，运行 `request_export.py`，策略拒绝，Customer 终端显示 `🔒 POLICY DENIED: raw customer-level export`。如果模型改为直接尝试 `cat`，执行器同样会拒绝并显示 🔒。
4. Customer Agent 回复 PRD §9 里的那段话，Orchestrator 原样转达给用户。
5. 用户接着问："Are high-value customers becoming less active?"
6. Customer Agent 用 `customer-retention` 和 `period-comparison` 正常分析并返回结果。

这个流程需要 Orchestrator 支持多轮对话（`--interactive`，§9.6）。

---

## 7. 数据

### 7.1 来源

- [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)，许可为 CC BY 4.0（以 UCI 页面标注为准）。
- 时间范围为 2009-12-01 到 2011-12-09，约 100 万行，xlsx 文件，分两个 sheet。
- 原始字段：Invoice、StockCode、Description、Quantity、InvoiceDate、Price、Customer ID、Country。
- 以 `C` 开头的 Invoice 是取消或退货，对应的 Quantity 为负数。

### 7.2 三份部门视图

三份视图都包含 `month` 和 `country` 这两个维度。Orchestrator 做跨部门追问时，可以按这两个维度对齐，不需要共享任何 ID。

| CSV | 粒度 | 维度 | 指标 |
|---|---|---|---|
| `sales.csv` | 日 × 国家 | date, week, month, country | revenue, orders, units, aov = revenue/orders, units_per_order |
| `customers.csv` | 客户 × 月 | month, country, segment（基准期 RFM 分层）, customer_type（new/returning）, cohort_month；customer_id 只在内部使用 | active_customers, revenue, orders, aov, revenue_per_customer, new_customers |
| `products.csv` | SKU × 月（是否加国家维度，在 Phase 0 看数据量后再定） | stock_code（结果里带上 description）, month, price_band | units_sold, revenue, returned_units, return_rate = returned/sold, active_skus |

`build_department_views.py` 必须确定且可复现：固定清洗规则，输出时附上行数和 sha256。

### 7.3 Data card（`data/README.md`）

- 内容包括：来源链接、许可、下载日期、原始文件的 sha256、清洗规则（取消单的处理、负数和零价格、缺失 Customer ID 的处理）、三份视图的字段定义、已知的数据缺口。
- Demo 时直接展示这一页，作为"数据来源"的证据。

### 7.4 三个坑

1. **"销售下降"必须在数据里真实存在。** 这个数据集季节性很强（Q4 是高峰），2011-12 又只到 12 月 9 日，直接看会像暴跌。`eda_find_decline.py` 要先找出一个真实的下降窗口，CEO 的问题里写明时间段，data card 里标注不完整的月份。
2. **EDA 结果只用来核对 Agent 的答案对不对，不能写进任何 prompt。** PRD §7 要求结论不能硬编码。
3. **很多订单没有 Customer ID**（游客下单），所以 customers.csv 的营收加起来和 sales.csv 对不上。data card 里要写清楚，部门 Agent 在 Caveats 里也应该能指出这一点。

### 7.5 分发

- 部门 CSV **不进 git**：如果仓库里有三份 CSV，每台设备 clone 下来都会拿到全部数据，Demo 的说法就站不住了。
- 做法：在一台机器上生成三份 CSV，然后每台设备只拷贝自己那一份到 `data/departments/<dept>/`，部门设备上也不留原始 xlsx。

---

## 8. Agent 的行为

### 8.1 Orchestrator 的流程（写进 `system_prompt_orchestrator.py`）

1. `make_plan`：拆成四个阶段，"拆解与派发 → 部门分析 → 跨部门追问（可选） → 综合"。
2. `fanout_subagents` 只调用一次：每个相关部门一个任务。`task_description` 必须写清：
   - 时间窗口；
   - 要回答的问题；
   - 要返回哪些数字；
   - 要求按部门输出格式（§8.3）回复。
3. 拿到结果后 `edit_plan`，再判断要不要追问：**最多追问一轮**，按 month 或 country 维度对齐。例如 Sales 发现德国下降，就问 Customer"德国的高价值客户是否流失"。
4. `end_orchestration`：交出 handoff note，由 announce 输出最终报告（§8.4）。
5. 数据访问请求：不自己拒绝，转给数据所属的部门（§6.1）。
6. 失败处理：结果状态是 `failed` 或 `timeout` 时，如果该设备仍然在线，就向**同一台设备**重派一次；否则把缺口写进 Missing Information。验证项目的做法是"改派给另一台机器"，这里不适用，因为部门数据只存在于一台设备上。

### 8.2 部门 Agent 的流程（写进 `system_prompt_department.py`）

System prompt 包括：

- 角色；
- 数据卡（由 DepartmentSpec 渲染，包含维度、指标定义、时间范围、不完整的月份）；
- Skill 索引（name + description）；
- 隐私规则；
- 输出格式。

工作步骤：

1. 读任务，确认时间窗口和要看的指标。
2. 选 1 到 3 个 skill，每个都是先 `load_skill`，再 `shell_executor`。
3. 用数字下结论，并注明时间段。
4. 按 §8.3 的格式回复。

迭代上限：`DEPARTMENT_MAX_ITERATIONS = 16`，`DEPARTMENT_ITERATION_BUDGET = 12`（验证项目里的子代理是 42 / 37，部门任务用不了那么多）。

### 8.3 部门结论的格式

```
## Findings
- 3–5 条，每条都带数字和时间段
## Evidence
- 用了哪些 skill、关键数字
## Caveats
- 不完整的月份、季节性、缺失的 Customer ID、被隐藏的分组
## Source
- <csv> · derived from UCI Online Retail II
```

### 8.4 最终报告（写进 `system_prompt_announce.py`，对应 PRD §14）

- **What happened**
- **Why**：Sales、Customer、Product 三方面分别提供的证据
- **Key Drivers**
- **Recommended Actions**：2 到 4 条，每条都要对应前面的证据
- **Missing Information**：没有完成的部门或证据不足的地方
- **Data sources**

---

## 9. 代码改动细节

### 9.1 `utils/settings.py` 与 `core/agents/model.py`

- 去掉 deepseek / mimo / glm / tavily / database，只保留一个 OpenAI 兼容的 provider：
  ```
  llm_base_url, llm_api_key, llm_model_name, llm_server ("vllm" | "ollama")
  orchestrator_llm_model_name, orchestrator_llm_base_url   # 可选覆盖，留空就用上面的
  department_llm_model_name,  department_llm_base_url      # 可选覆盖
  orchestrator_thinking, sub_agent_thinking
  langsmith_*, log_level, dev_mode, console_print
  ```
- `init_model(role, temperature, max_tokens, streaming, thinking)` 按 role 选择 model 和 base_url。关闭 thinking 时，沿用验证项目的 `chat_template_kwargs.enable_thinking`。
- 采样参数：模型卡推荐 temperature 1.0、top_p 0.95，验证项目用的是 0.3。两种都用 `test_tool_calling.py` 测一遍再决定。
- 开发期可以先用 OpenRouter 上托管的 Lightning（同一个模型，换个 `llm_base_url` 就行）。最终测试必须在自己的 vLLM 上做，因为 tool-call parser 不同。

### 9.2 worker 子图（`core/agents/worker/`）

- `prepare`、`llm`、`summarize`、`state` 原样复制。
- `build_react_agent(...)` 增加两个参数：
  - `post_summarize_node=None`：部门子图把 `egress_guard` 接在这里，形成 `prepare → llm ↔ tools → summarize → egress_guard`。这样本地模式和分布式模式都会经过出口检查。
  - `max_iterations` / `iteration_budget`：取代原来的全局常量。
- 部门 Agent 没有控制工具，所以 `control_tool_names` 传空。

### 9.3 部门图（`worker_registry.py`）

```python
def build_department_graph(spec: DepartmentSpec, data_path: str):
    tools = build_department_tools(spec, data_path)          # load_skill + shell_executor，绑定到这个部门
    prompt = render_department_prompt(spec, skills_for(spec))
    return build_react_agent(
        name=spec.name, tools=tools, system_prompt=prompt,
        post_summarize_node=make_egress_guard(spec, data_path),
        max_iterations=DEPARTMENT_MAX_ITERATIONS, iteration_budget=DEPARTMENT_ITERATION_BUDGET,
    )

def build_department_graphs(data_root: str) -> dict:          # 本地模式：一个进程跑三个部门
    return {s.name: build_department_graph(s, ...) for s in DEPARTMENTS}
```

- 工具通过闭包绑定到 spec 和 data_path，**不使用"当前部门"这种全局设置**。原因是本地模式下，一个进程里同时有三个部门。
- 验证项目在 import 时就构建了 `SUB_AGENT_GRAPHS`，这里改成函数调用，避免一 import 就去加载 CSV。

### 9.4 主图（`core/agents/graph.py`）

- 签名改为 `build_graph(callback_handler, department_graphs: dict | None)`：
  - 本地模式传入三个部门子图；
  - 分布式模式传 `None`，图里只有 `remote_agent` 节点。
- `_build_sub_agent_send`、collect barrier、`announce` 的路由原样保留。
- `MAX_RESULT_SUMMARY_CHARS` 从 1500 调到 3000。
- `core/agents/orchestrator.py`：去掉 `inject_workspace_dir`（Orchestrator 已经没有文件工具）；`ORCHESTRATOR_DISTRIBUTED_PROMPT` 按 §8.1 重写。

### 9.5 Orchestrator 的工具包（`core/tools/bundles/orchestrator.py`）

- 只保留 `make_plan`、`edit_plan`、`delete_plan`、`fanout_subagents`、`end_orchestration`，`ORCHESTRATOR_HARD_STOP_TOOLS` 不变。
- `FanoutTaskInput`：去掉 `project_dir`；`subagent_id` 的描述改为 `'<department>_<n>', department ∈ sales/customer/product`。

### 9.6 分布式运行时（`distributed/`）

- **protocol**：REGISTER 增加一个可选字段 `capabilities`，内容为 `{"department", "capability", "dimensions", "metrics", "skills", "example_questions"}`。它不放进 `REQUIRED_PAYLOAD_FIELDS`，以便兼容。
- **hub**：
  - 注册时校验 `roles ⊆ ("sales", "customer", "product")`；
  - 保存 `capabilities`；
  - `online_agents()` 把它一起返回；
  - `render_online_agents_block` 把能力卡渲染进 `<ONLINE_AGENTS>`，这就是 Orchestrator"知道每个 Agent 擅长什么"（PRD §12）的来源。
- **agent.py**：
  ```bash
  python -m distributed.agent --department customer --data data/departments/customer/customers.csv \
      --hub ws://<orchestrator-ip>:8800 --id pc-customer
  ```
  - 启动时先校验 CSV 和 spec 是否匹配；
  - 只构建本部门的图；
  - `run_task` 的逻辑不变。
- **orchestrator.py**：
  - `DEFAULT_QUERY` 用 PRD §7 的 CEO 问题，加上 EDA 确定的时间窗口；
  - 新增 `--interactive`：hub 一直开着，每输入一个问题就跑一次新的编排；
  - `--agents 3`。
- **task_console.py**：显示 `load_skill` 和 `shell_executor` 的调用行，🔒 行用醒目的颜色。
- **鉴权（可选）**：在 REGISTER 里带一个共享的 `HUB_TOKEN`。网络本身已经通过 Tailscale 隔离，所以这一项优先级低。
- **vLLM 部署**：命令见验证项目 `distributed/README.md` 里的"用 Brev 上的 vLLM"一节。Phase 4 时把它搬到本项目的 README。

---

## 10. 分批实施

| 批次 | 内容 | 验收 | 是否需要 GPU |
|---|---|---|---|
| **0 地基和数据** | 见下方清单 | 三份 CSV、data card，以及一页 EDA 结论（作为 ground truth，不进 prompt） | 否 |
| **1 数据层、Skills、工具** | `core/departments`、`core/data`、7 个 skills、`_skills.py`、`_shell_executor.py`、`descriptions/skills.py`、`bundles/department.py`、`egress_guard.py` 及其测试 | pytest 全部通过；手动运行每个 skill 的命令都能出结果；`cat`、管道、越权 skill、导出申请都被拒绝 | 否 |
| **2 部门 worker 图** | 复制 worker 子图；写部门 prompt；`scripts/run_department.py`；扩展 `test_tool_calling.py` | 每个部门都能回答 PRD §4 的问题，数字和 EDA 一致；隐私请求被拒绝 | 是（可以先用托管 API） |
| **3 Orchestrator 本地模式** | 复制主图、state、orchestrator、announce、plan 和 fanout 工具；写新的 prompt；`scripts/run_local.py` | 输入 CEO 问题，输出包含五部分的完整报告 | 是 |
| **4 分布式** | 复制 `distributed/*`，加入 capabilities；先在一台机器上开 4 个终端，再上 4 台机器（Tailscale 加 Brev 上的 vLLM）；故障注入 | 4 台机器跑通；运行中停掉一个 Agent，报告里出现 Missing Information | 是（vLLM） |
| **5 Demo 打磨** | `--interactive`、隐私 Demo 的脚本、console 美化、展示数据来源、彩排计时、录一段备用视频 | 完整 Demo 能稳定跑通 3 次 | 是 |

Phase 0 的清单：

- [x] 精简 `requirements.txt`
- [ ] `.gitignore`：`.venv/`、`.env`、`data/raw/`、`data/departments/`、`logs/`、`__pycache__/`
- [ ] `.env.example`
- [ ] 复制 `utils/`，并精简 settings
- [ ] 精简 `core/agents/model.py` 和 `constants.py`
- [ ] `scripts/download_dataset.py`、`eda_find_decline.py`、`build_department_views.py`
- [ ] `data/README.md`

Phase 1 不需要 GPU，可以和 vLLM 的部署同时进行。GPU 按小时计费，等到 Phase 2 真正需要时再租。

---

## 11. 测试

| 测试文件 | 覆盖 |
|---|---|
| `test_data_metrics.py` | 比率按总和之比计算、过滤器白名单、时间窗口边界 |
| `test_data_policy.py` | PII 列被拒绝、k-匿名隐藏、行数截断、`check_output` 能识别本地 customer_id |
| `test_skills_*.py` | 用一份小 fixture CSV（几十行，构造的数据）直接 import 每个脚本的 `run()`；再用子进程跑一遍完整命令 |
| `test_shell_executor.py` | 合法命令能通过；`cat`、`;`、`|`、`$()`、`../` 越界路径、本部门不能用的 skill、超时、非 JSON 输出都被拒绝 |
| `test_skills_registry.py` | 解析 frontmatter、按部门过滤、`load_skill` 的返回内容 |
| `test_egress_guard.py` | 脱敏和拦截的阈值、长度上限 |
| `test_plan_*`、`test_orch_control_*`、`test_orchestrator_no_tool_call_guard` | 从验证项目复制，改成新的角色前缀 |
| `test_distributed_runtime.py` | 从验证项目复制，加上 capabilities 的往返 |

所有测试都不需要模型。需要模型的验证放在 `scripts/test_tool_calling.py` 和 `run_department.py` 里手动执行。

---

## 12. 待定事项与风险

**待定事项**

1. `shell_executor` 是否只允许运行 Skill 脚本（本文的方案），"临时 Python 模式"是否放到以后再做（§5.5）。
2. 是否保留 `data-access-request` 这个 skill。不保留的话，隐私 Demo 里的拒绝就完全取决于模型自己的判断，措辞和时机都不稳定。
3. `products.csv` 是否加国家维度（Phase 0 看数据量后再定）。
4. 找主办方确认 33B 的计数口径（§1）。

**风险**

| 风险 | 应对 |
|---|---|
| 小模型调用工具不稳定 | 每个部门只有 2 个工具；参数用 enum；SKILL.md 给出可以直接照抄的用法行；用 `test_tool_calling.py` 量化成功率 |
| 数据里的"下降"不明显，或者被季节性掩盖 | Phase 0 的 EDA 先确定窗口；问题里写明时间段；data card 标注季节性和不完整的月份 |
| 现场网络不稳定 | 所有设备连 Tailscale；hub 有断线重连；提前录好备用视频 |
| GPU 费用 | Phase 0 和 1 不租；不用时在 Brev 控制台停机 |
| langgraph 升级导致 `ControlAwareToolNode` 失效 | `requirements.txt` 锁定 `langgraph==1.2.10` |
