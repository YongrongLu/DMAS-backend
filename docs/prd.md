# PRD — Retail Rescue

## 1. 产品概述

### 产品名称
**Retail Rescue**

### 核心概念
一个面向团队的隐私保护型跨设备 AI 协作系统。

公司的数据分散在不同部门、不同设备上。用户可以提出一个需要多个部门共同回答的问题，系统会让各设备上的 AI Agent 分别使用自己本地的数据完成分析，再把必要的分析结果汇总起来。

核心原则：

> AI agents can collaborate without centralizing the underlying data.

系统的重点不是让一个 AI 获得所有电脑的数据，而是让每台设备上的 Agent 保留自己的数据边界，并只贡献完成任务所需要的信息。

---

# 2. Hackathon Demo 场景

一家零售公司最近的销售表现出现异常。

CEO 提出：

> Our sales are declining. Find out what is happening, why it is happening, and what we should do next.

回答这个问题需要三个不同部门的信息。

三个部门的数据分别存在三台不同设备上。

---

# 3. Open Dataset

使用：

**UCI Online Retail II Dataset**

基于原始 Open Dataset 生成三个不同的部门数据视图：

- `sales.csv`
- `customers.csv`
- `products.csv`

三个 CSV 都来源于同一个 UCI Open Dataset，只是根据不同部门的需求进行了重新整理和聚合。

Demo 中需要明确展示数据来源。

---

# 4. 三个部门

## Sales Department

拥有：

`sales.csv`

主要包含销售相关数据，例如：

- 时间
- 国家 / 市场
- 订单数量
- 销售数量
- Revenue
- Average Order Value

Sales Agent 负责回答：

- 销售什么时候开始下降？
- 哪个时间段变化最大？
- 哪些市场贡献了主要下降？
- 是订单数量下降还是订单金额下降？
- 是否存在明显异常趋势？

---

## Customer Department

拥有：

`customers.csv`

主要包含客户行为相关数据，例如：

- Customer ID
- Purchase Count
- Total Spend
- Average Order Value
- Last Purchase Date
- Repeat Purchase Information
- Customer Segment

Customer Agent 负责回答：

- 是否正在失去重要客户？
- Repeat customers 的行为是否发生变化？
- 哪类客户变化最大？
- 高价值客户是否减少购买？
- 客户行为是否能够解释销售下降？

---

## Product Department

拥有：

`products.csv`

主要包含商品表现相关数据，例如：

- Product / Stock Code
- Product Description
- Units Sold
- Revenue
- Returns
- Return Rate
- Sales Trend

Product Agent 负责回答：

- 哪些商品销售下降最明显？
- 是否有高销量商品出现异常？
- 哪些商品退货率较高？
- 是否少数几个 SKU 对整体销售下降影响特别大？
- 产品表现是否能够解释销售变化？

---

# 5. 核心用户故事

作为公司的负责人：

> 我希望只提出一个业务问题，就能够同时利用不同部门的数据得到完整分析，而不需要把所有部门的原始数据集中到我的电脑。

例如：

> Our sales are declining. Find out what's wrong and give me a recovery plan.

系统应该自动判断这个问题涉及：

- Sales
- Customer
- Product

并让对应部门分别进行分析。

---

# 6. 核心业务流程

正常链路：

User asks one high-level question

↓

System understands what information is required

↓

System identifies which departments / agents are relevant

↓

The task is divided into several department-specific questions

↓

Sales Agent analyzes local sales data

Customer Agent analyzes local customer data

Product Agent analyzes local product data

↓

Each Agent returns only the findings required for the task

↓

The system combines the findings

↓

User receives one final business diagnosis and action plan

---

# 7. Demo 示例

用户输入：

> Our sales are declining. Find out:
>
> 1. What caused the decline?
> 2. Which customers or products are most affected?
> 3. What should we do next?

系统应该大致拆解成：

### Sales Agent

分析：

> What happened to revenue and order volume?

### Customer Agent

分析：

> Did customer purchasing behavior change?

### Product Agent

分析：

> Did particular products contribute to the decline?

三个 Agent 独立分析。

最后系统综合回答：

> Sales declined primarily because of X.
>
> Customer behavior shows Y.
>
> Product analysis shows Z.
>
> Based on these findings, the company should prioritize A, B and C.

实际 Demo 中的 X/Y/Z 必须根据真实 CSV 分析结果产生，不能提前硬编码。

---

# 8. 隐私需求

这是产品最重要的区别之一。

每个部门的数据归该部门自己的 Agent 管理。

主控 AI 不应该默认拥有远程设备所有文件的访问权限。

例如：

Customer Agent 可以回答：

> Are high-value customers becoming inactive?

但如果用户要求：

> Give me the entire customer database.

系统应该拒绝提供原始客户数据。

核心原则：

> The system can ask questions about the data without automatically gaining access to the data itself.

---

# 9. Privacy Demo

Hackathon Demo 中需要专门展示一次越权请求。

例如：

用户：

> Send me the full customer CSV.

系统：

> Access denied.
>
> Raw customer-level data cannot be exported from this device.
>
> I can provide aggregate customer insights instead.

然后用户问：

> Are high-value customers becoming less active?

Customer Agent 正常完成分析并返回结果。

这个过程需要让观众非常直观地看到：

**分析是允许的，原始数据访问是不允许的。**

---

# 10. Agent 基础能力需求

目前已有的通用 Agent 工具可以保留，例如：

- `read_file`
- `write_file`
- `str_replace`
- `view_file`
- `glob_tool`
- `grep_tool`
- `web_search`
- `web_fetch`
- `shell_executor`
- `fanout_subagents`

但不同 Agent 不一定需要获得所有工具。

原则是：

> Each agent should only have the tools required for its role.

---

# 11. CSV / 数据分析能力

这个项目需要专门的数据分析能力。

不建议让 AI 直接把一个大型 CSV 全部读取进上下文再进行计算。

Agent 应该能够：

- 查看 CSV 有哪些字段
- 查看 CSV 基础统计信息
- 筛选数据
- 按字段分组
- 求和 / 平均值 / 数量
- 排序
- 获取 Top N
- 做时间趋势分析
- 比较两个时间段
- 找异常变化
- 回答针对 CSV 的业务问题

可以将这些能力统一理解为一个：

**CSV / Structured Data Analysis Skill**

具体由 Coding Agent 决定怎么实现。

---

# 12. Agent 协作能力

主控 Agent 需要能够：

- 知道目前有哪些远程 Agent
- 知道每个 Agent 擅长什么
- 把不同任务分配给不同 Agent
- 同时让多个 Agent 工作
- 等待和收集结果
- 如果某个 Agent 失败，可以识别失败
- 在结果不完整时继续完成任务或重新调整计划
- 将多个部门的结果综合起来

---

# 13. 本地 Agent 能力

每个部门 Agent 需要能够：

1. 接收到一个自然语言任务
2. 判断这个任务需要分析什么数据
3. 使用自己的 CSV 数据分析能力
4. 得出结论
5. 返回与任务相关的结果
6. 不发送完整原始 CSV
7. 不访问自己无权访问的数据

---

# 14. 最终输出要求

最终结果不应该只是三个 Agent 输出的简单拼接。

主控 AI 应该进行跨部门推理。

最终回答至少包含：

### What happened

发生了什么？

### Why

Sales、Customer、Product 三方面分别提供了什么证据？

### Key Drivers

哪些因素最可能导致当前问题？

### Recommended Actions

接下来最值得做的 2–4 个行动是什么？

### Missing Information

如果某个 Agent 没有完成任务或证据不足，需要明确说明。

---

# 15. MVP 必须完成

Hackathon MVP 至少需要实现：

- 3 个部门 Agent
- 3 个不同 CSV
- CSV 来源于 UCI Online Retail II
- Agent 运行在不同设备 / 独立环境
- 一个高层业务问题
- 自动拆解为多个任务
- 多 Agent 同时工作
- 每个 Agent 本地分析自己的 CSV
- 返回分析结果
- 汇总成最终 Recovery Plan
- 原始 CSV 不需要集中到主控设备
- 一次明确的隐私 / 越权访问拒绝 Demo

---

# 16. 非 MVP

本次 Hackathon 暂时不需要：

- 完整企业权限管理系统
- 用户账户系统
- 智能家居
- 手机 Agent
- 车载 Agent
- 大规模 Agent Marketplace
- 复杂的企业组织结构
- 完整数据库系统
- 真正的生产级安全体系

这些都可以作为未来扩展方向。

---

# 17. Demo 成功标准

当 Demo 结束时，观众应该清楚看到：

### 1. 这是一个真实的分布式系统

不是三个假 UI，而是多个 Agent 真正在完成任务。

### 2. 系统真的处理了 Open Dataset

不是预先写死答案。

### 3. 三个 Agent 分别拥有不同的数据视角

没有任何单一 Agent 一开始就知道全部信息。

### 4. AI 可以跨设备协作

多个局部分析可以组成一个完整业务判断。

### 5. 数据不需要全部集中

主控 AI 能利用数据产生的 intelligence，而不是直接获得所有数据。

### 6. 隐私边界是真实存在的

一个越权数据请求会被拒绝。

---

# 18. Demo 核心信息

不要把项目描述成：

> We built three AI agents that analyze CSV files.

应该描述成：

> We built a distributed AI collaboration system where agents on different devices can combine their intelligence without centralizing their underlying data.

最终希望评委记住：

> **Three departments. Three datasets. One business problem.**
>
> **The agents share intelligence — not everything they know.**