# Quantifiction 产品需求文档 v0.1

> 加密货币量化交易平台 · 币安 U 本位永续
> 版本：v0.1 ｜ 日期：2026-07-20 ｜ 状态：待评审

---

## 0. 一句话定位

**一个以资本保全为第一约束的个人量化研究平台**，以 $1000 实盘账户作为活体测试装置（live test harness），验证「LLM 认知层 + 盘口量化信号」融合策略的有效性，并沉淀可长期增值的订单簿数据资产。

---

## 1. 背景与定位

### 1.1 关键约束（不可协商）

| 约束 | 值 | 影响 |
|---|---|---|
| 初始本金 | $1000 | 决定频率上限、标的数量、策略并发数 |
| 后续追加 | **无** | 没有第二次机会，爆仓 = 项目终止 |
| 硬地板 | **$850**（-15%） | 触及即全平停机，需人工复盘后重启 |
| 盯盘时间 | **接近 0** | 系统必须全自动 + 自愈 + 远程刹车 |
| 开发时间 | 全职 | 研究与数据层可以做深 |

### 1.2 定位推论

开发投入（全职 3 个月，市场价 $15k-30k）是本金的 **20 倍以上**。

> **推论：任何「为多赚一点而增加系统风险」的决策都是亏的。**

因此：
- 系统健壮性 **优先于** 策略收益率
- 数据与研究能力 **优先于** 执行性能
- 避免坏交易 **优先于** 抓住好交易

### 1.3 非目标（明确不做）

- ❌ 微秒级高频交易（币安 WS 推送 100ms 已锁死上限）
- ❌ 做市 / 高频套利（$1000 + VIP0 费率结构下数学上不可能盈利）
- ❌ 多交易所（只做币安）
- ❌ A 股（本期不做，仅预留接缝，见 §9）
- ❌ 对外服务 / 多用户（个人自用）

---

## 2. 成功标准

### 2.1 阶段划分

| 阶段 | 资金 | 周期 | 成功标准 |
|---|---|---|---|
| **A** Testnet | $0 | 4 周 | 连续 7 天：零对账偏差、零丢单、看门狗演练通过 |
| **A+** 微额冒烟 | **$100** | 2-3 周 | **真实链路跑通**：真实成交/对账/告警/刹车，非策略验证 |
| **B** 实盘验证 | $1000 | 12 周 | **不爆仓、不触及硬地板**；实际滑点 vs 回测偏差 < 30%；完成 ≥ 50 笔交易样本 |
| **C** 追求 alpha | $1000 | 持续 | 夏普 > 1.0，最大回撤 < 12%，LLM 层归因为正 |

> **A+ 阶段的特殊性**：$100 ≈ BTCUSDT MIN_NOTIONAL，无法交易 BTC，仅可用 ETH/SOL 等 MIN_NOTIONAL=20 的标的开单个小仓位。
> **此阶段不追求任何策略表现**，目的是用最小真金验证：真实 API Key 下单、成交回报、对账、飞书告警、Web 刹车是否全链路可用。资金分层等比缩放（硬地板 $85 / 工作资金 $15）。跑通后再注资至 $1000 进入 B 阶段。

### 2.2 B 阶段 KPI（重要）

**B 阶段的 KPI 是「活着且数据对得上」，不是收益率。**

| 指标 | 目标 |
|---|---|
| 账户存活 | 100%（权益始终 > $850） |
| 系统可用性 | > 99%（月度停机 < 7h） |
| 对账偏差事件 | 0 |
| 丢单 / 幽灵仓位 | 0 |
| 实际滑点 vs 回测 | 偏差 < 30% |
| 交易样本量 | ≥ 50 笔 |
| 收益率 | **不做要求**（-15% ~ +∞ 均视为通过） |

---

## 3. 市场与交易规格

### 3.1 交易标的

| 项 | 值 |
|---|---|
| 交易所 | Binance USDⓈ-M Futures |
| 标的 | 可配置，见 §8.5 币种池；B 阶段 live 层建议 BTCUSDT、ETHUSDT |
| 杠杆 | **1x（锁死）** |
| 保证金模式 | 全仓（Cross） |
| 单向/双向 | 单向持仓（One-way） |

**为何 1x 永续而非现货：**
- 保留做空能力
- 手续费更低（taker 0.05% vs 现货 0.1%）
- 1x 全仓下强平价距离极远，实际风险接近现货
- 可直接使用永续独有信号（资金费率、爆仓流、持仓比）

### 3.2 成本结构

```
Taker 0.05% / Maker 0.02%（VIP0，未开 BNB 抵扣）
完整往返（taker 进出）= 0.10%
资金费率：每 8h 结算，多空方向随市场，需计入持仓成本
```

**频率上限反推：**

| 日均交易次数 | 日手续费占本金 | 结论 |
|---|---|---|
| 1-3 | 0.1-0.3% | ✅ 可行 |
| 5-10 | 0.5-1.0% | ⚠️ 需单笔 edge > 0.15% |
| 20+ | > 2% | ❌ 不可行 |

> **目标频率：日均 1-3 笔，持仓 1-6 小时。**

### 3.3 交易所约束

| 项 | BTCUSDT | ETHUSDT |
|---|---|---|
| MIN_NOTIONAL | 100 USDT | 20 USDT |
| 价格精度 | 0.1 | 0.01 |
| 数量精度 | 0.001 | 0.001 |

> 运行时从 `GET /fapi/v1/exchangeInfo` 动态读取，不硬编码。

---

## 4. 资金管理与风控

### 4.1 资金分层（核心设计，不可变更）

```
初始本金 $1000
├─ 硬地板  $850   ← 全平 + 停机 + 人工复盘方可重启
├─ 软地板  $900   ← 单笔风险减半、暂停新策略
└─ 工作资金 $150  ← 真正允许亏损的部分
```

> **实际风险预算是 $150，不是 $1000。所有仓位计算基于 $150。**

### 4.2 仓位计算

```
单笔风险 = 工作资金 × 10% = $15
止损幅度 = 1.5%（默认）
名义敞口 = $15 / 1.5% = $1000  → 1x 杠杆

连续亏损 10 笔才触及硬地板 → 样本量充足且不会归零
```

软地板触发后：单笔风险降至 $7.5，名义敞口降至 $500。

### 4.3 风控闸门链（下单前逐条校验，任一不过即拒单）

| # | 闸门 | 规则 |
|---|---|---|
| G1 | HardFloorGate | equity < $850 → 拒单 + 触发全平停机 |
| G2 | SoftFloorGate | equity < $900 → 风险参数减半 |
| G3 | MaxExposureGate | 总名义敞口 ≤ equity × 1.0 |
| G4 | PerSymbolGate | 单标的敞口 ≤ equity × 0.7 |
| G5 | CorrelationGate | BTC+ETH 同向合计 ≤ equity × 1.0 |
| G6 | DailyDrawdownGate | 当日亏损 > 3% → 停止开仓至次日 UTC 0 点 |
| G7 | HourlyLossGate | 单小时亏损 > 3% → 全平 + 停机 |
| G8 | OrderRateGate | 单小时下单 ≤ 10 笔；单日 ≤ 20 笔 |
| G9 | MinNotionalGate | 名义敞口 ≥ 交易所最小值 × 1.1 |
| G10 | RateLimitGate | X-MBX-USED-WEIGHT-1M > 80% → 降频 |
| G11 | ReconcileGate | 本地仓位与币安不一致 → 拒单 + 告警 |
| G12 | StaleDataGate | 行情最后更新 > 5s → 拒单 |
| G13 | LLMVetoGate | 认知层 veto = true → 拒单（见 §6.3） |
| G14 | SymbolCapGate | 单标的敞口 ≤ equity × capital_weight（见 §8.5） |

### 4.4 强制止损

**每笔仓位建仓成功后，立即在交易所挂 STOP_MARKET 止损单。**

理由：本地进程崩溃时，交易所侧的止损单仍然有效。这是无人值守的最后一道防线。

```
入场成交 → 立即 POST /fapi/v1/order
  type=STOP_MARKET, closePosition=true, stopPrice=入场价×(1∓1.5%)
```

止损单挂失败 → 立即市价平仓，不允许裸持仓。

---

## 5. 系统架构

### 5.1 总体分层

```
┌─ L3 认知层（15min ~ 8h）──────────────────────┐
│  TradingAgents 改造版（LangGraph 编排）        │
│  宏观 / 情绪 / 新闻 / 链上 / 衍生品数据        │
│  输出：stance + conviction + veto（带 TTL）    │
└──────────────┬────────────────────────────────┘
               │ Redis Streams（signals，半衰期衰减）
┌──────────────▼─ L2 决策层（秒级，自研核心）───┐
│  信号融合 → 仓位计算 → 风控闸门链 → 订单指令   │
└──────────────┬────────────────────────────────┘
               │
┌──────────────▼─ L1 执行层（100ms）────────────┐
│  币安 WS 行情 + 本地订单簿 + REST 下单 + 对账   │
└───────────────────────────────────────────────┘
        ▲
        │ 独立进程、独立只读+平仓 API Key
┌───────┴─ Watchdog ────────────────────────────┐
│  心跳监控 / 权益监控 / 强制平仓 / 飞书告警    │
└───────────────────────────────────────────────┘
```

### 5.2 进程划分

| 进程 | 职责 | 崩溃影响 |
|---|---|---|
| `feed` | WS 订阅、订单簿维护、信号计算 | 策略无数据 → StaleDataGate 拒单 |
| `strategy` | 融合、仓位、风控、下单 | 停止交易，仓位由交易所止损保护 |
| `cognitive` | TradingAgents | 降级为纯量化 |
| `watchdog` | 监控与紧急平仓 | **告警到飞书（含加急消息，必须独立部署）** |
| `recorder` | tick 数据落盘 | 数据缺口，不影响交易 |

### 5.3 部署拓扑

```
阿里云香港轻量（¥24/月）        阿里云国内（已有）
├─ feed                        ├─ 数据归档（对象存储同步）
├─ strategy                    ├─ 回测 / 研究环境
├─ cognitive                   ├─ Grafana 看板
├─ watchdog                    └─ 飞书告警中继（可选）
├─ recorder
└─ Redis
```

> **执行节点必须在境外**：阿里云国内 IP 直连币安 API 受限；代理方案在无人值守场景下 WS 断线风险不可接受。

### 5.4 Connector 分层方案

#### 5.4.1 基本立场

> **不存在「安全稳定有保证」的 connector——包括 Hummingbot 与币安官方库。**
> 正确的设计前提是：**假设 connector 一定会出错，系统在其出错时仍不得亏光本金。**

安全性由 §5.5 的防御纵深提供，而非由 connector 质量提供。

#### 5.4.2 分层

```
┌─ 业务层：订单状态机 / 仓位对账 / 幂等 ──┐  ✅ 自研
├─ 传输层：签名 / REST / WS 重连 ────────┤  ❌ 官方库
└─ 协议层：HTTP / WSS ──────────────────┘  ❌ 标准库
```

| 组件 | 方案 | 理由 |
|---|---|---|
| REST 签名与调用 | `binance-futures-connector`（官方） | 时间戳同步、限速头解析等边界情况已处理 |
| WS 连接与重连 | 官方库 + 自研健康检查包装 | 心跳与重连逻辑复用 |
| **订单簿维护** | **自研** | 官方库不提供；`pu` 校验必须自主控制 |
| **订单状态机** | **自研** | 承载风控语义 |
| **仓位对账** | **自研** | 系统安全的核心 |

> 自研部分约 **800-1200 行**，属可完整测试与审计的规模。

#### 5.4.3 为何不采用 Hummingbot

**须承认**：Hummingbot 的币安 connector 实战里程远超本项目可能达到的水平，这是其真实优势。

不采用的理由是 **不可审计性**：

- 继承链过深（`ConnectorBase` → `ExchangeBase` → `ExchangePyBase` → `BinancePerpetualDerivative`），故障定位困难
- 订单状态机与其自身策略框架耦合，独立使用成本高
- 版本升级可能引入行为变更，本项目无能力评估影响

> 在**无人值守 + 不可亏损本金**的场景下，「完全理解每一行」优于「久经考验但无法读懂」。
> 可审计的 1000 行代码，故障时 10 分钟可定位；不可读的 50000 行框架，故障时只能等待——而此时正持有仓位。

**此结论依赖「全职开发」这一前提。若开发投入不足，则应反向选择 Hummingbot。**

### 5.5 防御纵深（故障矩阵）

每类故障均配备**相互独立**的兜底机制：

| # | 故障 | 后果 | 兜底机制 | 独立性 |
|---|---|---|---|---|
| F1 | 进程崩溃 | 裸持仓 | **交易所侧 STOP_MARKET**（§4.4） | ✅ 运行于币安服务器 |
| F2 | WS 断线未察觉 | 用陈旧数据交易 | StaleDataGate（>5s 拒单） | ✅ 依赖本地时钟 |
| F3 | 下单成功但回包丢失 | 幽灵仓位 | 30s 对账 + `ACCOUNT_UPDATE` | ✅ 以交易所为准 |
| F4 | 订单簿静默错位 | 信号失真 | `pu` 校验 + 定期快照重建 | ✅ 序列号自证 |
| F5 | 策略逻辑失控 | 连续下单 | OrderRateGate（10 笔/小时） | ✅ 独立计数器 |
| F6 | 交易进程整体失联 | 仓位无人管理 | **Watchdog 独立进程 + 独立 Key** | ✅ 独立部署 |
| F7 | 全部软件失效 | — | 交易所止损 + **1x 杠杆无强平风险** | ✅ 最终防线 |

> **F7 是本项目真正的安全保证。**
> 1x 杠杆 + 交易所侧止损意味着：即使全部代码同时失效、服务器宕机、操作者失联，最坏结果仅为止损成交，亏损约 1.5%。
> **这是坚持 1x 杠杆的根本原因**——3x 时，软件故障可升级为强制平仓。

### 5.6 M0 验收标准（DoD）

> **M0 的验收不是「能够下单」，而是「全部故障演练通过」。** 全程在 Testnet 执行。

**混沌测试**

- [ ] 随机 `kill -9` strategy 进程 → 交易所止损单仍存在？Watchdog 平仓成功？
- [ ] 断网 60s → 恢复后订单簿正确重建？仓位对账一致？
- [ ] Redis 宕机 → 系统停止交易，而非带错误状态继续运行？
- [ ] 时钟偏移 2s → 签名失败后正确重试？

**边界测试**

- [ ] 下单量低于 MIN_NOTIONAL → 拒单，而非异常崩溃
- [ ] 触发 -1003 限频 → 指数退避重试，而非死循环
- [ ] 相同 `clientOrderId` 重复提交 → 幂等，不产生双重仓位

**对账测试**

- [ ] 在币安网页端手动开仓 → 系统 30s 内发现不一致并停机
- [ ] 连续 7×24 小时运行 → 对账偏差事件 = 0

**恢复测试**

- [ ] **持仓状态下重启 strategy → 正确恢复仓位与止损单，不重复挂单**

> 最后一项为高频缺陷点：重启后若未检查既有止损单，将挂出第二张；其后一张成交、另一张转为反向开仓。

---

## 6. 认知层（TradingAgents 改造 · LangGraph 编排）

### 6.0 编排框架：LangGraph

TradingAgents 原版即基于 **LangGraph** 编排 analyst → researcher → trader 状态流，本项目沿用并改造，不引入其它框架。

**选用理由（贴合本场景）：**

| 能力 | 用途 |
|---|---|
| 有状态多智能体 | bull vs bear 多轮辩论 |
| 条件分支 | 哨兵无变化 → 短路直接结束，省钱 |
| **Checkpointer** | 状态可回放、可审计、预算中断可恢复 |
| 可中断/可恢复 | 图执行中途降级不丢状态 |

**Checkpointer 必须启用并落 Postgres（`PostgresSaver`）**，与交易记录同库，`graph_run_id` 关联 §10.4.1 的 `llm_decisions` 表，形成完整决策链路。

#### 6.0.1 图结构

```
         ┌──────────┐
   START │ Sentinel │  哨兵：有无重大变化？
         └────┬─────┘
       changed? ──No──→ END（复用上次 stance，省钱）
              │Yes
         ┌────▼──────┐
         │ Analysts  │  并行节点：新闻 / 情绪 / 链上 / 衍生品
         └────┬──────┘
         ┌────▼───────┐
         │ Bull ⇄ Bear│  条件循环，最多 N 轮辩论
         └────┬───────┘
         ┌────▼──────┐
         │  Trader   │  裁决 → stance / conviction / veto
         └────┬──────┘
         ┌────▼───────┐
         │ Risk Review│  只读复核，可标记不可否决交易
         └────┬───────┘
              ▼ 出口
```

#### 6.0.2 硬约束：LangGraph 不改变权限边界

> **采用 LangGraph 不改变 §6.3-6.6 的任何约束。** 图内部无论多复杂，出口仅有受控字段。

```
LangGraph 图 → trader_verdict
   ↓ 必须依次通过
§6.5 校验器 → §6.3 权限边界 → §6.6 熔断器 → L2 决策层
```

LangGraph 是「如何产出观点」的工具，不触及「观点如何被约束」的规则。

### 6.1 频率控制：三档触发

| 档位 | 触发 | 模型 | 上限 |
|---|---|---|---|
| **哨兵** | 每 15min | Haiku 4.5 | — |
| **完整辩论** | 定时 3 次/天（UTC 0/8/16）+ 哨兵触发 | Haiku/Sonnet/Opus 分层 | ≤ 8 次/天，最小间隔 45min |
| **事件强制** | FOMC 4h 内 / 1h 涨跌 > 5% / 爆仓 > $50M | 同上 | ≤ 3 次/天 |

### 6.2 模型分层与成本

| Agent | 模型 | 频率 |
|---|---|---|
| 新闻/舆情摘要 | Haiku 4.5 | 30min |
| 链上数据解读 | Haiku 4.5 | 1h |
| 多头研究员 | Sonnet 5 | 辩论时 |
| 空头研究员 | Sonnet 5 | 辩论时 |
| 交易员裁决 | Opus 4.8 | 辩论时 |

**预算硬上限：$1.20/天，$25/月。超预算自动降级为纯量化模式（非报错）。**

优化手段：prompt caching（省 60-80% 输入）、事件触发跳过无变化时段、仅覆盖 2 个标的。

### 6.3 权限边界（不可协商）

```
LLM 可以：
  ✅ 输出 stance ∈ [-1, +1]      软权重
  ✅ 输出 veto = true            否决开仓（硬约束）
  ✅ 输出 conviction ∈ [0, 0.8]  上限 0.8，不允许"非常确定"

LLM 不可以：
  ❌ 直接产生订单
  ❌ 决定仓位大小
  ❌ 修改或取消止损
  ❌ 解除任何风控闸门
  ❌ 单独触发开仓（必须与量化信号同向）
```

**不对称原则：LLM 说「别做」是硬约束，说「要做」只是软加成。**

### 6.4 融合公式

```python
def final_score(quant: float, llm: LLMSignal) -> float:
    if llm.veto:
        return 0.0
    if quant * llm.stance <= 0:        # 方向不一致
        return quant * 0.3             # 削弱，不反转
    return quant * (1 + 0.5 * llm.stance * llm.conviction)
    # LLM 最多让信号强度 ±50%
```

时效衰减：`effective = stance * conviction * exp(-Δt·ln2/half_life)`

### 6.5 输出校验（安检链）

| # | 校验 | 失败处理 |
|---|---|---|
| V1 | JSON Schema | 丢弃（不重试、不猜测） |
| V2 | 数值 clamp | stance ∈ [-1,1]，conviction ∈ [0,0.8] |
| V3 | 跳变检测 | \|Δstance\| > 1.2 且间隔 < 1h → conviction 打 5 折 |
| V4 | 证据检查 | reasoning 含 < 2 条 evidence → 视为幻觉，丢弃 |
| V5 | 时效 | 超过 half_life → 失效 |

### 6.6 认知层熔断器

| 条件 | 动作 |
|---|---|
| 连续 5 次 LLM 加成的交易亏损 | boost 系数减半（0.5 → 0.25） |
| 连续 8 次 | 降级为 veto-only |
| 连续 12 次 | 完全关闭，纯量化，告警 |
| 30 日 veto 精确率 < 0.4 | veto 权限降为「仓位减半」 |
| 24h schema 失败率 > 20% | 关闭 + 告警 |

**veto 精确率**：每次 veto 记录影子 PnL（若做了会怎样），是证明 veto 价值的唯一依据。

---

## 7. 量化信号层

### 7.1 本地订单簿维护（币安合约特有流程）

```
1. 订阅 <symbol>@depth@100ms，缓存事件
2. REST GET /fapi/v1/depth?limit=1000 取快照
3. 丢弃 u < snapshot.lastUpdateId 的事件
4. 首个有效事件须满足 U <= lastUpdateId+1 <= u
5. 之后每个事件的 pu 必须等于上一事件的 u —— 不等即重建
```

> 第 5 步的 `pu` 校验为合约独有（现货无此字段），遗漏会导致订单簿静默错位。

### 7.2 信号清单

| 信号 | 计算 | 用途 |
|---|---|---|
| OBI | (Vbid - Vask)/(Vbid + Vask)，前 20 档 | 短期方向压力 |
| 挂单墙 | 单档量 > 3× 档均量，存活 > 30s | 支撑/阻力 |
| 爆仓流 | `@forceOrder` 5min 滚动净额 | 强平级联，反转 |
| 资金费率偏离 | funding vs 8h 均值 | 多空拥挤度 |
| CVD | 主动买卖成交量累计差 | 资金"能量" |
| OBI 变化率 | d(OBI)/dt | 大单抢跑 |
| 持仓量变化 | OI 5min 变化率 | 增减仓性质 |

**重要**：币安订单簿大墙 60%+ 为伪装单，会在价格接近时撤销。必须用「存活时长」+「被吃比例」过滤，禁止裸用。

### 7.3 信号的正确定位

盘口信号 **不作为独立开仓依据**，而是：
1. 提供短周期方向压力，与 LLM stance 融合
2. **择时优化**：方向确定后，选择滑点最小的入场点

---

## 8. 策略框架

### 8.1 两层分离

| 层 | 内容 | 可编辑性 |
|---|---|---|
| **策略规格** | 信号组合、阈值、进出场条件 | ✅ YAML 热加载 |
| **信号计算** | 订单簿维护、CVD、爆仓流聚合 | ❌ 代码，需 review |

### 8.2 策略规格示例

```yaml
# strategies/liq_reversal.yaml
name: liquidation_reversal
version: 3
enabled: true
symbols: [BTCUSDT]
timeframe: 5m

entry:
  all:
    - liq_flow_5m.abs > 2_000_000
    - liq_flow_5m.side == "long"
    - rsi_14 < 30
    - obi_20 > 0.15
exit:
  any:
    - pnl_pct > 1.5
    - pnl_pct < -0.8          # 与交易所止损单冗余
    - holding_minutes > 240

sizing:
  risk_usd: 15
  max_leverage: 1
```

### 8.3 策略并发限制

> **B 阶段仅启用 1 个策略实盘。**

$1000 本金下多策略会导致：仓位低于 MIN_NOTIONAL、互相抢资金、产生非预期净敞口。

**影子模式（Shadow Mode）**：其余策略并行运行，记录完整信号与假想成交，但不下单。用于低成本收集对比样本。此机制为框架内建。

### 8.4 配置变更留痕

所有 YAML 变更写入 `config_changes` 表；每笔交易关联当时的 config 版本号。

> 否则三个月后无法区分「收益变化」是策略效应还是参数改动。

### 8.5 币种池（三层分级）

#### 8.5.1 容量约束

```
1x 杠杆，总敞口 ≤ $1000
BTCUSDT MIN_NOTIONAL = 100 USDT
单笔风险 $15 / 止损 1.5% → 单仓名义 $1000
```

> **同时最多持有 1 个 BTC 仓位，或 2-3 个 MIN_NOTIONAL=20 的小仓位。**

若配置过多币种同时实盘，将出现：仓位摊薄至低于最小下单量而静默拒单，或互相抢资金导致「先到先得」——**执行结果由信号到达顺序决定，而非信号质量决定**，这是必须避免的失败模式。

#### 8.5.2 三层分级

| 层 | 建议数量 | 行为 | 成本 |
|---|---|---|---|
| `live` | 1-2 | 实盘下单 | 手续费 + 风险 |
| `shadow` | ≤ 8 | 全量信号 + 假想成交，**不下单** | 带宽/CPU |
| `observe` | 不限 | 仅录制数据，不计算信号 | 存储 |

**币种升降级由数据驱动**：shadow 层连续 30 日净收益优于 live 层 → 提请升级。禁止凭主观判断调整 live 名单。

#### 8.5.3 配置

```yaml
# config/universe.yaml
universe:
  BTCUSDT:
    tier: live
    strategies: [liq_reversal, obi_momentum]
    capital_weight: 0.7
    max_notional_usd: 700
    leverage: 1

  ETHUSDT:
    tier: live
    strategies: [liq_reversal]
    capital_weight: 0.3
    max_notional_usd: 300

  SOLUSDT:
    tier: shadow
    strategies: [liq_reversal, funding_skew]

  DOGEUSDT:
    tier: observe

constraints:
  max_live_symbols: 2
  max_concurrent_positions: 2
  sum_capital_weight: 1.0
```

**启动时硬校验（不通过则拒绝启动，不允许运行时才暴露）：**

| # | 校验 |
|---|---|
| U1 | `live` 层数量 ≤ `max_live_symbols` |
| U2 | `live` 层 `capital_weight` 之和 == 1.0 |
| U3 | 每个 `max_notional_usd` ≥ 该标的 MIN_NOTIONAL × 1.1 |
| U4 | 引用的 strategy 均存在且 enabled |
| U5 | 所有 symbol 在 `exchangeInfo` 中存在且状态为 TRADING |

新增闸门 **G14 SymbolCapGate**：单标的敞口 ≤ `equity × capital_weight`。

### 8.6 归因账本与报表

#### 8.6.1 交易账本

每笔 PnL 必须可拆解到 **(币 × 策略 × 日)** 三个维度。

```sql
CREATE TABLE trade_ledger (
  trade_id        TEXT PRIMARY KEY,
  symbol_uid      TEXT,        -- binance_ums:BTCUSDT
  strategy        TEXT,
  tier            TEXT,        -- live | shadow
  open_ts         TIMESTAMPTZ,
  close_ts        TIMESTAMPTZ,
  side            TEXT,
  entry_px        NUMERIC,
  exit_px         NUMERIC,
  qty             NUMERIC,
  notional_usd    NUMERIC,
  gross_pnl       NUMERIC,     -- 毛盈亏
  fee             NUMERIC,     -- ★ 单独存
  funding_pnl     NUMERIC,     -- ★ 单独存
  net_pnl         NUMERIC,
  slippage_bps    NUMERIC,
  llm_stance      NUMERIC,
  llm_conviction  NUMERIC,
  llm_veto        BOOLEAN,
  quant_score     NUMERIC,
  config_version  INT
);
```

> **`fee` 与 `funding_pnl` 必须与 `gross_pnl` 分离存储。**
> 在 0.10% 往返成本结构下，「方向正确但被手续费吃光」是高频出现的情形；不拆分会将其误判为策略无效。

#### 8.6.2 日报（飞书，UTC 0 点）

```
📊 2026-07-21 日报  | 权益 $1,003.20 (+0.32%)

LIVE
  BTCUSDT   2笔  净 +$4.10  (毛 +$6.10 费 -$2.00)  胜1/2
  ETHUSDT   1笔  净 -$0.90  (毛 -$0.30 费 -$0.60)  胜0/1

SHADOW
  SOLUSDT   4笔  净 +$8.20   ← 表现超过 live，考虑升级
  AVAXUSDT  1笔  净 -$1.10

策略维度
  liq_reversal   3笔 +$3.20
  obi_momentum   1笔 -$0.90

LLM: 辩论6次 veto 1次(避开 -$2.1 ✅) 成本 $0.87
```

**live 与 shadow 并排展示**是本报表的核心价值：可直接观察「未启用币种」的表现，驱动数据化的升降级决策。

#### 8.6.3 可视化

见 §11 Web 控制台。Grafana 作为补充用于系统级监控（可选）。

---

## 9. A 股扩展接缝（本期只留口，不实现）

只在三处留接缝，其余按币安具体实现编写。额外工作量约 2-3 天。

### 缝 1：Symbol 带市场归属

```python
@dataclass(frozen=True)
class Symbol:
    market: Market       # BINANCE_UMS | ASHARE
    raw: str             # "BTCUSDT" | "600519"
    @property
    def uid(self) -> str:
        return f"{self.market.value}:{self.raw}"
```

所有信号、仓位、日志、Redis key 一律用 `uid`。

### 缝 2：ExecutionGateway + MarketCaps

```python
@dataclass(frozen=True)
class MarketCaps:
    supports_short: bool          # 币安 True / A股 False
    settlement: Settlement        # T0 | T1
    price_limit_pct: float | None # 币安 None / A股 0.10
    min_lot: int                  # 币安 1 / A股 100
    has_l2_depth: bool
    has_liquidation_feed: bool    # 币安 True / A股 False
    trading_calendar: Calendar
```

策略层查询 `gw.caps.has_liquidation_feed`，禁止写 `if market == BINANCE`。

### 缝 3：风控闸门链可插拔

A 股接入时追加 `T1SellableGate` / `PriceLimitGate` / `LotSizeGate` / `CancelRatioGate`，币安侧不受影响。

### 明确不预留

- ❌ 通用行情协议（JSON vs C 结构体，语义差异过大）
- ❌ 通用账户模型（保证金账户 vs 股票账户）
- ❌ 通用回测引擎（tick 回放 vs 分钟 K 线）
- ❌ 插件化配置系统 / DI 容器

---

## 10. 运维与可观测

### 10.1 Watchdog（无人值守刚需）

**独立进程、独立 API Key（仅只读 + 平仓权限）。**

| 条件 | 动作 |
|---|---|
| 心跳丢失 > 60s | 撤单 + 市价平仓 + 告警 |
| 对账不一致 | 停止开新仓 + 告警 |
| 权益 < $850 | 全平 + 停机（需人工重启） |
| 单小时亏损 > 3% | 全平 + 停机 |
| API 连续错误 > 10 | 停止交易，保留仓位，告警 |

### 10.2 仓位对账

`ACCOUNT_UPDATE` 推送的仓位为唯一真相。本地每 30s 对账，不一致立即停机。

### 10.3 飞书通知（仅出站，不做控制）

#### 10.3.1 出站/入站分离

| 方向 | 用途 | 通道 |
|---|---|---|
| **出站** | 告警、日报、成交通知 | 飞书自定义机器人 Webhook（无公网需求） |
| **入站** | 全平/暂停等控制指令 | **Web 控制台（§11），不走飞书** |

> **飞书仅负责「通知你该去操作」，不负责执行操作。**
> 飞书交互按钮需公网 HTTPS 回调，与 §11.3「香港节点不暴露公网」的安全设计冲突。紧急刹车经 Tailscale 进 Web 控制台完成，安全边界更清晰。

#### 10.3.2 双群分级

| 群 | 内容 | 提醒策略 |
|---|---|---|
| **量化-告警** | 硬地板触及、全平停机、对账不一致、Watchdog 触发 | @所有人，不免打扰 |
| **量化-日报** | 每日报告、成交通知、LLM 成本 | 免打扰，静默 |

#### 10.3.3 消息形态

- 告警：飞书消息卡片（card），红/黄/绿色标区分严重度
- 日报（UTC 0 点）：卡片富文本，含 PnL、成交明细、信号命中率、LLM 成本、异常事件
- 加签验证：timestamp + HMAC-SHA256（飞书自定义机器人安全设置）

#### 10.3.4 告警可靠性约束（重要）

飞书自定义机器人限流 **100 条/分钟**。为防止告警风暴导致关键告警被限流丢失：

- **本地去重聚合**：同类告警 1 分钟内合并为一条
- **致命告警双通道**：硬地板触及、全平停机、Watchdog 触发等致命告警，除群机器人 Webhook 外，**并发飞书「加急消息」（buzz / urgent_phone）直达个人**，触发 App 弹窗乃至电话级提醒

> **致命告警单通道 = 单点故障。** 飞书群机器人限流或被忽略时，加急消息作为第二保险直达本人。
> 加急消息为飞书原生能力，**零额外成本**，故不引入阿里云短信。

### 10.4 数据资产（全量永久留存）

> **原则：所有日志、决策、成交、市场原始流全部永久保存，供日后回放、再分析、模型评测/微调使用。**

按访问模式分三层存储，禁止混存：

| 层 | 内容 | 存储 | 保留 |
|---|---|---|---|
| **冷** 市场原始流 | 订单簿增量 / 逐笔成交 / 爆仓流 / 资金费率 | Parquet 按天分区 → 阿里云 OSS | 永久 |
| **温** 交易与决策 | trade_ledger / config_changes / **llm_decisions（全文）** / 系统事件日志 | Postgres + 定期备份至 OSS | 永久 |
| **热** 运行态 | 心跳 / 持仓 / 信号快照 | Redis（TTL 过期） | 短期 |

> 币安不提供历史 L2 深度，第三方（Tardis.dev）需 $200-500/月。**自录冷数据是本项目最具长期价值的资产**，一年后不可复得。

#### 10.4.1 LLM 决策全文留存（关键）

**每次 LLM 决策必须留存完整 prompt 与 output，而不仅是结论。**

```sql
CREATE TABLE llm_decisions (
  decision_id     TEXT PRIMARY KEY,
  ts              TIMESTAMPTZ,
  symbol_uid      TEXT,
  trigger         TEXT,          -- scheduled | sentinel | event
  graph_run_id    TEXT,          -- 关联 LangGraph checkpoint
  model_versions  JSONB,         -- 各 agent 使用的模型
  full_prompt     TEXT,          -- ★ 完整输入（含当时数据快照）
  full_output     TEXT,          -- ★ 完整输出
  bull_argument   TEXT,          -- 多头研究员全文
  bear_argument   TEXT,          -- 空头研究员全文
  trader_verdict  JSONB,         -- stance / conviction / veto
  token_cost      NUMERIC,
  latency_ms      INT
);
```

> **为何存全文**：日后可用新模型重跑历史决策做 A/B 对比，或将 (prompt, output) 对用于小模型微调/评测。此数据现在不存，未来无法补回——这正是「供以后使用」的实质含义。
> **合规提示**：prompt 可能含新闻原文等第三方内容，仅限自用留存，不得对外分发。

---

## 11. Web 控制台

### 11.1 首要原则：UI 不进交易进程

```
ui (静态资源) → api 进程 → Redis / Postgres → strategy 进程
                    ↑
             只写控制指令，不直接下单
```

**`api` 进程不持有币安 API Key。** 它仅向 Redis 写入控制指令，由 `strategy` 进程消费执行。

> 即使 `api` 进程被攻破，攻击者无法获得交易权限，最坏结果为停机。

同时避免：UI 崩溃拖垮策略、UI 阻塞事件循环。

### 11.2 权限分级

| 操作 | 风险 | 控制 |
|---|---|---|
| 查看 PnL / 持仓 / 日志 / LLM 记录 | 低 | 直接可用 |
| 暂停 / 全平 | 低（仅降低风险） | 一次确认 |
| 修改策略阈值 | 中 | 二次确认 + 自动回测校验 + Git commit |
| 修改币种 tier（shadow→live） | 高 | 二次确认 + 24h 冷却期 |
| **修改风控参数** | **极高** | **UI 不可修改** |

#### 11.2.1 UI 禁止修改清单（硬边界）

```
❌ 硬地板 $850 / 软地板 $900
❌ 单笔风险 $15
❌ 杠杆倍数（锁定 1x）
❌ max_live_symbols / max_concurrent_positions
❌ 任何风控闸门 G1-G14 的阈值
❌ 认知层预算上限与熔断阈值
```

以上仅可通过修改服务器上的配置文件 + 重启生效。

> **理由**：这些参数存在的意义即是约束操作者本人。若可在移动端于数秒内修改，则不再构成约束。「浮亏时临时下调地板」是最典型的爆仓路径。

### 11.3 访问控制

| 方案 | 安全性 | 推荐 |
|---|---|---|
| **Tailscale / WireGuard** | 高，不暴露公网端口 | ✅ 采用 |
| Cloudflare Tunnel + Access | 高 | 备选 |
| 公网 + Nginx + 密码 | 低 | ❌ 禁用 |

采用 Tailscale：服务器不开放任何公网端口；额外保留一层应用密码作为兜底。

### 11.4 页面结构

| 页面 | 内容 |
|---|---|
| **Dashboard** | 权益曲线（含 $900/$850 参考线）、今日 PnL、当前持仓、健康灯、[暂停]/[全平] |
| **Symbols** | 币种表：tier / 今日 PnL / 累计 / 笔数；live 与 shadow 并排；tier 切换入口 |
| **Strategies** | 各策略净值曲线、胜率、盈亏比、最大回撤 |
| **Trades** | 交易明细，gross/fee/funding 拆解；**每笔可展开查看当时 LLM reasoning** |
| **Cognitive** | 辩论历史、veto 记录及其影子 PnL、今日成本与预算余量 |
| **Config** | YAML 编辑器 + diff 预览 + schema 校验 + 变更历史 |
| **Health** | 心跳、对账偏差、WS 重连次数、API 权重占用 |

> **Trades 页展开查看 LLM reasoning 为优先级最高的功能**：它是判断认知层是否值得保留的最直接依据，价值高于任何汇总指标。

### 11.5 技术选型

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + WebSocket（实时权益/持仓推送） |
| 前端 | React + Vite + TanStack Query + Recharts |
| 组件库 | shadcn/ui |
| 配置编辑 | Monaco Editor（YAML 高亮 + schema 校验） |
| 认证 | Tailscale 网络层 + 应用层单用户密码 |

**不引入**：Next.js（无 SSR 需求）、多用户 / RBAC（单人使用）。

### 11.6 工期与优先级

预计 **2-2.5 周**，排期于 M4 之后、M5 实盘之前，确保实盘首日即具备完整可视化。

> 若 M0-M4 出现延期，Web 控制台为**第一顺位下调项**——飞书告警（§10.3）已能满足最低限度的监控通知需求（注意：飞书仅出站通知，刹车仍需 Web 控制台，故 Web 只读页不可全砍，见 §11.6）。

---

## 12. 目录结构

```
quantifiction/
├── core/                    # 市场无关
│   ├── symbol.py            # 缝1
│   ├── types.py             # Order/Position/Fill/MarketCaps
│   ├── bus.py               # Redis Streams
│   └── risk/
│       ├── gate.py          # 缝3
│       └── common_gates.py
├── markets/
│   ├── base.py              # 缝2
│   ├── binance_ums/
│   │   ├── feed.py          # WS + 订单簿（含 pu 校验）
│   │   ├── gateway.py       # REST + userDataStream
│   │   ├── caps.py
│   │   └── signals.py
│   └── ashare/              # 空目录 + README
├── strategy/
│   ├── fusion.py
│   ├── sizing.py
│   └── shadow.py            # 影子模式
├── cognitive/
│   ├── graph.py             # LangGraph 图定义（§6.0.1）
│   ├── checkpointer.py      # PostgresSaver 配置
│   ├── nodes/               # sentinel/analysts/researchers/trader/risk
│   ├── datasource/crypto/
│   ├── validator.py         # §6.5
│   ├── breaker.py           # §6.6
│   ├── budget.py
│   └── recorder.py          # llm_decisions 全文落库（§10.4.1）
├── research/
│   ├── recorder.py
│   ├── replay.py
│   └── attribution.py       # LLM 归因分析
├── ops/
│   ├── watchdog.py
│   └── feishu.py            # 出站告警/日报 + 加急消息(致命告警第二通道)
├── webui/
│   ├── api/                 # FastAPI，★ 不持有交易 Key
│   │   ├── routes/
│   │   ├── control.py       # 写控制指令到 Redis
│   │   └── guards.py        # §11.2.1 禁改清单校验
│   └── frontend/            # React + Vite
└── config/
```

---

## 13. 里程碑

| 阶段 | 内容 | 周期 |
|---|---|---|
| M0 | Testnet 打通 + **混沌演练全过（DoD 见 §5.6）** | 2 周 |
| M1 | Tick 录制器 + 数据归档 | 1 周 |
| M2 | 信号库 + 回放回测引擎 | 3 周 |
| M3 | TradingAgents 改造（LangGraph + Checkpointer）+ 校验/熔断/预算 + 决策全文留存 | 3 周 |
| M4 | 策略开发 + 影子模式验证 | 3 周 |
| M4.5 | Web 控制台（§11） | 2-2.5 周 |
| M4.8 | **$100 微额冒烟（A+ 阶段）** | 2-3 周 |
| M5 | **$1000 实盘（B 阶段）** | 12 周 |
| M6 | 归因分析，决定 LLM 层去留 | — |

> **M1 不可跳过。** 无自录订单簿数据，M2 的全部回测结果均不可信。
> **M4.5 可部分下调**：Config/Cognitive 等页面可推迟，但 Dashboard + 刹车按钮的只读/控制页不可砍（飞书不提供入站控制，见 §10.3.1）。

---

## 14. 主要风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 币安账户合规/风控封禁 | 项目终止 | 主体与网络出口需提前确认 |
| R2 | 策略无 alpha | B 阶段亏至地板 | 硬地板保护；影子模式低成本试错 |
| R3 | LLM 层无正贡献 | 每月 $25 白花 | §6.6 熔断 + §10 归因，3 个月内出结论 |
| R4 | 香港节点故障 | 无法交易/平仓 | 交易所侧 STOP_MARKET 兜底（§4.4） |
| R5 | 订单簿静默错位 | 信号失真 | `pu` 校验 + 定期快照重建 |
| R6 | 手续费侵蚀 | 长期负收益 | 频率上限 3 笔/日；优先 maker 挂单 |
| R7 | **Web 控制台成为攻击面** | 交易系统被入侵 | api 进程无交易 Key（§11.1）+ Tailscale 不暴露公网（§11.3） |
| R8 | 通过 UI 临时放宽风控 | 绕过保护机制导致爆仓 | §11.2.1 禁改清单，风控参数仅可改文件 |
| R9 | **自研 connector 缺陷** | 丢单/幽灵仓位/裸持仓 | §5.5 七层防御纵深；§5.6 混沌演练；传输层复用官方库 |

---

## 15. 待确认

- [ ] 币安账户主体与 KYC 状态
- [ ] 阿里云香港轻量服务器开通
- [ ] 飞书自定义机器人 Webhook（告警群 + 日报群）+ 加签密钥
- [ ] 飞书自建应用（用于加急消息 / 应用消息直达个人）
- [ ] LLM API 账号与预算告警设置
- [ ] 数据源账号：Glassnode 免费档 / CryptoQuant
- [ ] Tailscale 账号（Web 控制台访问）

---

*文档结束 · v0.1*
