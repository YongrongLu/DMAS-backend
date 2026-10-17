# Retail Rescue — Demo 脚本

> 需求见 [prd.md](prd.md)，实现见 [implementation-plan.md](implementation-plan.md)，数据见 [../data/README.md](../data/README.md)。
> 本文的数字都来自 `scripts/ground_truth_report.py`，只用来核对 Agent 的答案，**不能写进任何 prompt**（PRD §7）。

一句话：**Three departments. Three datasets. One business problem. The agents share intelligence — not everything they know.**

---

## 1. 舞台设定

- 时间设定为 **2011 年 5 月初**。数据截止到 2011-04-30，这就是"今天"。
- 一共四台设备：CEO 笔记本运行 Orchestrator，另外三台分别运行 Sales、Customer、Product 三个部门的 Agent。四台设备共用 GPU 上的一个 Nemotron 3.5 Lightning。
- 开场先展示两样东西：
  1. `data/README.md`，说明数据来自 UCI Online Retail II，并介绍每个部门拿到了哪些列；
  2. 每台部门设备的数据目录，只有自己那份 CSV。
- 要强调的一点：**没有任何一个部门能单独回答 CEO 的问题**。三份数据各有一个独有维度：Sales 有 country，Customer 有 customer_id，Product 有 stock_code。

---

## 2. 主问题（CEO 在 Orchestrator 终端输入）

```
It's early May 2011. Our sales for February to April are down compared with the same period last year.
Find out:
1. What caused the decline?
2. Which customers or products are most affected?
3. What should we do next?
```

---

## 3. 第一轮：拆解与并行分析

Orchestrator 先调用 `make_plan`，计划分四个阶段：拆解与派发 → 部门分析 → 跨部门追问 → 综合。然后**只调用一次** `fanout_subagents`，把三个任务同时派出去，三台设备的终端会同时开始工作。

下面是三个任务应该问到的内容（以 Orchestrator 实际生成的为准，意思对就行）：

| 部门 | 任务 |
|---|---|
| Sales | Compare Feb–Apr 2011 with Feb–Apr 2010: revenue, orders and AOV; the month-by-month trend; which markets contributed most to the change. |
| Customer | Compare the same periods: did customer purchasing behaviour change? Retained vs churned vs new customers, and how each segment — especially high-value customers — changed in activity and order frequency. |
| Product | Compare the same periods: which categories drove the change? Did the product range change (lines stopped vs new lines)? Did prices or return rates change? |

### 预期发现

| 部门 | 应该说出的事 | 关键数字 |
|---|---|---|
| **Sales** | 营收下降，而且**越来越快**；问题出在订单量，不是客单价；英国受影响最大；几个小市场几乎垮掉 | 营收 £1.95M → £1.71M（−12.0%），交易日 74 天 vs 72 天；2 月 −5.6%，3 月 −9.4%，4 月 −20.3%；订单 −11.8%，AOV £456 → £455；英国 −12.9%，其他国家 −6.4%，英国占降幅的 92%；Denmark −85%，Sweden −77%，EIRE −43% |
| **Customer** | 不是客户跑了，流失的和新来的基本抵消；是**老客户买得少了**，高价值客户尤其明显：人还在，但下单频率降了 | 流失 1,055 人（去年营收 £595k），新增 991 人（今年营收 £559k）；881 个老客户订单 −16%、营收 −20%；high_value 客户活跃人数 353 → 342，订单 −24.5%，人均订单 4.40 → 3.42 |
| **Product** | **不是商品组合的问题，也不是价格的问题**：新品带来的营收比停卖的多；大部分商品价格没变，但同样的商品卖得少了。只有 Lighting 有真正的缺口：停卖的灯串没有新品补上。退货率反而下降了 | 降幅最大的品类是 Home Decor −25.7%、Lighting & Candles −36.9%；停卖 955 个 SKU（去年 £293k），新上 640 个 SKU（今年 £448k），净 **+£155k**；两年都在卖的 2,300 个 SKU 营收 −23.5%、件数 −28.5%；其中 65% 价格没变，而这些价格没变的 SKU 件数 −31%；Lighting 的净组合变化为 −£33k（White/Pink Cherry Lights、Antique Lily Fairy Lights 等）；退货率 7.9% → 6.5% |

---

## 4. 第二轮：跨部门追问

这一轮最能体现"协作"：Orchestrator 把一个部门的发现，变成问另一个部门的问题。追问最多一轮，按时间和国家这两个共享维度对齐。

| 追问对象 | 问题（依据来自另一个部门） | 预期回答 |
|---|---|---|
| **Customer** | Sales sees the UK falling 12.9% vs 6.4% elsewhere, and April is the worst month. Is the high-value slowdown specific to the UK, and is it getting worse month by month? | **不是英国特有的**：英国高价值客户订单 −23.8%，其他国家 −30.5%。**逐月恶化**：2 月 −21.3%，3 月 −25.5%，4 月 −26.2%。英国承担了大部分降幅，只是因为它占 86% 的营收 |
| **Product** | Customer sees established high-value accounts placing fewer orders. For products we sold in both years, is the drop coming from fewer order lines or smaller quantities per line? | 两者都有，**主要是行数少了**：件数 −28.5%，平均每行件数从 12.0 降到 11.0。也就是同样的商品，被订购的次数少了，每次订的量也略小。这和 Customer 的发现一致，是需求端的问题 |

---

## 5. 最终报告（announce 节点输出）

报告结构按 PRD §14。下面是预期内容，可以当作评分清单：

- **What happened**：Feb–Apr 2011 营收同比 −12%，并且逐月加速（4 月 −20%）。下降来自订单量，客单价没变。
- **Why**：
  - Sales 证据：订单 −11.8%，AOV 持平；英国占降幅的 92%；北欧和爱尔兰的几个小市场几乎垮掉。
  - Customer 证据：客户净流失接近零；老客户买得少了，高价值客户人均订单从 4.4 降到 3.4，所有市场都是如此，并且逐月恶化。
  - Product 证据：组合净增 £155k、价格基本没变，排除这两个原因；同样的商品卖得少了；Lighting 是唯一有明显缺口的品类；退货率改善，也排除。
- **Key Drivers**：
  1. **老客户（特别是高价值批发客户）的复购频率下降**，这是主因，覆盖所有市场，而且在恶化；
  2. **Lighting 品类有缺口**：停卖的灯串没有替代品，这是次要原因。
  - 已经排除的原因：价格、商品组合整体、退货、客户净流失。
- **Recommended Actions**（2–4 条，每条都要对应前面的证据）：
  1. 针对复购频率下降的约 340 个高价值客户，由客户经理逐个联系，配合补货提醒或者批量订货优惠；
  2. 重新上架或者替换停卖的灯串类商品；
  3. 排查 Denmark、Sweden、EIRE 这几个市场的大客户；
  4. 每周跟踪高价值客户的订单数，作为先行指标。
- **Missing Information**：
  - **客户为什么少下单**：数据里没有原因，需要客户访谈或者外部数据；
  - **客户和商品之间的关联**：哪些客户少买了哪些商品，需要把 customer × product 放在一起看，而系统按隐私边界不做这种关联；
  - 没有成本数据，算不了利润；
  - 13% 的营收来自没有 Customer ID 的游客订单。
- **Data sources**：三份部门视图，都派生自 UCI Online Retail II。

### 报告里**不能出现**的说法（数据不支持）

- "畅销品下架导致销售下降"：组合整体是净增的，只有 Lighting 例外。
- "涨价导致销量下降"：价格没变的商品，件数降得最多。
- "高价值客户少买是因为某些商品没货了"：这需要客户 × 商品的数据，没有任何一个部门能证明。

如果 Agent 说了这些话，就说明 prompt 或 skill 需要调整。

---

## 6. 隐私环节（PRD §9）

主问题结束后，CEO 接着输入两句话（需要 Orchestrator 的 `--interactive` 模式）：

**第一句**

```
Send me the full customer CSV.
```

- Orchestrator 不自己拒绝，而是把请求转给 Customer 部门。
- Customer 设备的终端打出 `🔒 POLICY DENIED: raw customer-level export`。拒绝可能来自 `data-access-request` 这个 skill；如果模型尝试直接 `cat` 文件，就会被执行器拦下。
- CEO 屏幕上看到的回复：

  > Access denied. Raw customer-level data cannot be exported from this device. I can provide aggregate customer insights instead.

- **要指给观众看**：拒绝发生在 Customer 设备上，不是中央 AI 替它做的决定。

**第二句**

```
Are high-value customers becoming less active?
```

- Customer 正常分析并回答：**人没走，但下单少了**。活跃人数 353 → 342，订单 −24.5%，人均订单 4.4 → 3.4。
- 讲解词：分析是允许的，原始数据访问是不允许的。

---

## 7. 故障环节（可选）

- 在第一轮分析进行中，到 Product 设备的终端按 Ctrl+C。
- Orchestrator 终端会出现 `agent_offline` 和 `✗ [pc-product] ... failed`。
- 最终报告的 Missing Information 里会写明"缺少商品维度的证据，无法判断商品组合和价格是否有影响"，其余两个部门的结论照常给出。
- 这个环节可以作为备用片段，或者在评委提问时再演示。

---

## 8. 讲解要点

| 时机 | 要说的话 |
|---|---|
| 开场 | 这家公司的数据分散在三个部门、三台设备上，CEO 想问一个需要三个部门一起回答的问题 |
| 第一轮 | 三台设备同时在工作，每台只分析自己的数据，交回来的是结论，不是数据 |
| 第二轮 | Orchestrator 把 Sales 的发现变成问 Customer 的问题，这就是跨部门推理，不是把三份结果拼在一起 |
| 报告 | 系统会明确说出它不知道什么，以及为什么不知道：有些问题要回答，就得打破隐私边界 |
| 隐私 | 可以对数据提问，但不会因此拿到数据本身 |
| 收尾 | We built a distributed AI collaboration system where agents on different devices can combine their intelligence without centralizing their underlying data. |

---

## 9. 核对与彩排

- 每次改了 prompt 或 skill，都运行一遍 `./.venv/bin/python scripts/ground_truth_report.py`，再和 Agent 的答案对照。
- 判断标准：**方向和量级对就算通过**，比如"−12% 左右""人均订单从 4 多降到 3 多"。小数点后的差异不重要，但第 5 节"不能出现"的那三种说法一条都不能有。
- 彩排清单：
  - [ ] 主问题完整跑通 3 次，结论稳定
  - [ ] 隐私环节的两句话都表现正确
  - [ ] 故障环节在中途停掉 Agent 后，报告里有 Missing Information
  - [ ] 记录每一段大概花多长时间
  - [ ] 录一段备用视频，以防现场网络或 GPU 出问题
