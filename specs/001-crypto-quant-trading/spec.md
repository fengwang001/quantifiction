# Feature Specification: 加密量化交易平台（币安永续 + LLM 认知层）

**Feature Branch**: `001-crypto-quant-trading`

**Created**: 2026-07-21

**Status**: Draft

**Input**: 由 `docs/PRD-v0.1.md` 依据 Spec Kit 方法论重构而来。宪法见 `.specify/memory/constitution.md`。

---

## User Scenarios & Testing *(mandatory)*

> 用户 = 平台的唯一操作者（本人）。每个故事按「若只实现它，是否仍构成有价值的可用切片」来排优先级并可独立测试。

### User Story 1 - 安全执行与自愈（Priority: P1）

作为无人值守的操作者，系统能自主、安全地在币安永续下单/平仓，并在任何组件故障时保护本金，使我不必盯盘。

**Why this priority**: 这是资本保全（宪法 I/III/IV）的直接载体。没有它，其余一切都建立在会亏光本金的地基上。它本身即构成 MVP——即使没有任何 alpha，一个「能安全下单、故障自愈、绝不爆仓」的执行核心已有价值（可作为手动/半自动交易的安全底座）。

**Independent Test**: 在 Testnet 上手动注入信号触发下单，逐条执行 §5.6 混沌演练（kill 进程 / 断网 / Redis 宕机 / 带仓重启），验证交易所止损单常驻、对账一致、无丢单无双仓。全程无需策略层与认知层。

**Acceptance Scenarios**:

1. **Given** 已建仓，**When** `kill -9` strategy 进程，**Then** 交易所侧 STOP_MARKET 仍存在，Watchdog 在 60s 内完成兜底平仓并告警。
2. **Given** 正常运行，**When** 断网 60s 后恢复，**Then** 订单簿依据 `pu` 序列重建，本地仓位与 `ACCOUNT_UPDATE` 对账一致。
3. **Given** 持仓状态，**When** 重启 strategy 进程，**Then** 正确恢复仓位与既有止损单，不重复挂单、不产生反向开仓。
4. **Given** 权益跌至 $850，**When** 触发任一下单，**Then** HardFloorGate 拒单并触发全平停机，需人工重启。

---

### User Story 2 - 可配置币种池与风险预算下单（Priority: P1）

作为操作者，我能以 YAML 配置 live/shadow/observe 三层币种池与单笔风险预算，系统据此在容量约束内自动计算并执行仓位。

**Why this priority**: 与 US1 并列 P1，因为「按 $150 风险预算、1x、MIN_NOTIONAL 约束正确算仓」是安全下单不可分割的一半。US1 保证「下单安全」，US2 保证「下多少安全」。

**Independent Test**: 加载含 live+shadow 的 universe.yaml，启动时校验 U1-U5 全过；注入信号，验证 live 币实盘下单量落在 [MIN_NOTIONAL×1.1, equity×capital_weight] 内，shadow 币只记账不下单。

**Acceptance Scenarios**:

1. **Given** universe.yaml 中 live 层 capital_weight 之和 ≠ 1.0，**When** 启动，**Then** 拒绝启动并报出具体校验项。
2. **Given** $100 本金配置 BTCUSDT 为 live，**When** 启动校验，**Then** 因 max_notional < MIN_NOTIONAL×1.1 而拒绝（提示改用 ETH/SOL）。
3. **Given** SOLUSDT 配为 shadow，**When** 其策略触发信号，**Then** 生成假想成交并入账 trade_ledger（tier=shadow），不向交易所下单。

---

### User Story 3 - 全量留存与每币每日归因（Priority: P2）

作为操作者，我能查看每个币、每个策略、每一天的净收益（含成本拆解），并回放任一笔交易当时的完整决策依据。

**Why this priority**: 是「用数据决策」（宪法 VI）与「全量留存」（宪法 V）的载体。US1/US2 让系统能安全跑，US3 让我能判断「跑得好不好、为什么」。排 P2 是因为它依赖 US1/US2 先产生真实成交数据。

**Independent Test**: 跑一批 live+shadow 成交，查询 trade_ledger 能按 (币×策略×日) 聚合出 gross/fee/funding/net；随机抽一笔展开，能取到当时的 llm_decisions 全文与信号值。

**Acceptance Scenarios**:

1. **Given** 当日有 live 与 shadow 成交，**When** 生成日报，**Then** live 与 shadow 各币净收益并排呈现，且 fee 与 funding 单独列出。
2. **Given** 任一历史交易，**When** 在控制台展开，**Then** 显示当时 bull/bear 论点全文、trader stance/veto、量化信号值与 config 版本号。
3. **Given** 一次 LLM 决策，**When** 落库，**Then** full_prompt 与 full_output 完整留存且关联 graph_run_id。

---

### User Story 4 - LLM 认知层受约束地提供方向与否决（Priority: P2）

作为操作者，我希望 LangGraph 编排的多智能体在受控频率与预算内产出 stance/veto，且其输出被校验、熔断、权限边界层层约束，绝不能自行发起或放大风险。

**Why this priority**: 认知层是差异化价值，但它是「增强项」——系统在无 LLM 时应能降级为纯量化正常运行（宪法 II）。故排 P2，晚于安全执行核心。

**Independent Test**: 断开 LLM，验证系统降级纯量化仍正常交易；恢复后注入构造的越界输出（stance=5 / conviction=0.99 / 无证据 / 幻觉），验证校验器与熔断器按 §6.5/6.6 处置；验证 veto 生效为硬否决、stance 与量化反向时仅削弱不反转。

**Acceptance Scenarios**:

1. **Given** LLM 预算当日耗尽，**When** 到达决策时点，**Then** 系统降级纯量化（非报错），信号自然衰减。
2. **Given** LLM 输出 veto=true，**When** 量化信号触发开仓，**Then** LLMVetoGate 拒单。
3. **Given** LLM stance 与量化信号反向，**When** 融合，**Then** 最终分数为量化分×0.3（削弱，不反转、不开反向仓）。
4. **Given** 连续 12 次 LLM 加成交易亏损，**When** 熔断评估，**Then** 认知层完全关闭并告警。

---

### User Story 5 - 远程监控与紧急刹车（Priority: P3）

作为操作者，我能通过飞书接收告警/日报，并经 Tailscale 进入 Web 控制台随时暂停或全平；风控参数在 UI 上不可修改。

**Why this priority**: 提升可运维性与响应速度，但最低限度的刹车可由 Watchdog 自动阈值 + 飞书告警覆盖，故排 P3。Dashboard+刹车的最小控制页不可全砍（飞书不提供入站控制）。

**Independent Test**: 触发一次致命条件，验证飞书群消息+加急消息双通道送达；经 Tailscale 打开控制台点「全平」，验证指令经 Redis 到 strategy 执行；尝试在 UI 修改硬地板，验证被 guards 拒绝。

**Acceptance Scenarios**:

1. **Given** 触及硬地板，**When** 告警发出，**Then** 飞书群机器人与加急消息均送达本人。
2. **Given** 在控制台点击「全平」，**When** 指令下发，**Then** API 进程（无交易 Key）写 Redis，strategy 消费并执行平仓。
3. **Given** 尝试经 UI 修改单笔风险/杠杆/地板，**When** 提交，**Then** guards 依 §11.2.1 拒绝，提示仅可改配置文件。

---

### Edge Cases

- $100 本金下所有 live 币的 max_notional 均低于 MIN_NOTIONAL×1.1 → 启动即拒绝，明确提示不可交易 BTC。
- 币安订单簿大墙在价格接近时撤单（伪装单）→ 信号必须用存活时长+被吃比例过滤，禁止裸用。
- 下单成功但 REST 回包丢失 → 依赖对账发现幽灵仓位，30s 内暴露并停机。
- LLM 返回非法 JSON / schema 不符 → 丢弃，不重试不猜测，本次降级纯量化。
- 香港执行节点整体故障 → 交易所侧 STOP_MARKET + 1x 无强平作为最终防线。
- 告警风暴触发飞书 100 条/分钟限流 → 本地去重聚合 + 加急消息保底致命告警。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 通过交易所官方/签名客户端连接 U 本位永续（**当前主用：欧易 OKX SWAP**，2026-07-21 切换；**币安保留供扩展**，代码与测试完整保留），自研订单状态机、本地订单簿维护（币安 `pu` / 欧易 `seqId+CRC32` 续接校验）与仓位对账。
- **FR-002**: 系统 MUST 在每笔建仓成功后立即于交易所侧挂 STOP_MARKET；挂失败 MUST 立即市价平仓。
- **FR-003**: 系统 MUST 在提交订单前依次通过风控闸门链 G1-G14；任一不过即拒单。
- **FR-004**: 系统 MUST 将杠杆锁定为 1x，且 UI/远程接口 MUST NOT 修改任何风控参数（地板/单笔风险/杠杆/并发上限/闸门阈值）。
- **FR-005**: 系统 MUST 每 30s 以交易所 `ACCOUNT_UPDATE` 为准对账，不一致立即停机。
- **FR-006**: 系统 MUST 支持 YAML 配置 live/shadow/observe 三层币种池，并在启动时硬校验 U1-U5。
- **FR-007**: 系统 MUST 以工作资金风险预算（$150 / $100 阶段 $15）为基数计算仓位，非以全部本金。
- **FR-008**: shadow 与 observe 层 MUST NOT 向交易所下单；shadow MUST 记录假想成交入账。
- **FR-009**: 系统 MUST 永久留存冷/温数据，其中 LLM 决策 MUST 留存 full_prompt 与 full_output。
- **FR-010**: 系统 MUST 使 PnL 可拆解到 (币×策略×日)，且 fee/funding/gross 分列存储。
- **FR-011**: 认知层 MUST 以 LangGraph 编排并启用 PostgresSaver checkpointer；其输出 MUST 依次经校验器→权限边界→熔断器。
- **FR-012**: 认知层 MUST 遵守频率三档与预算硬上限（$1.20/天，$25/月），超预算 MUST 降级纯量化而非报错。
- **FR-013**: LLM veto MUST 为硬否决；LLM stance 与量化反向时 MUST 仅削弱（×0.3）而不反转、不发起反向开仓。
- **FR-014**: Watchdog MUST 为独立进程 + 独立 API Key（仅只读+平仓），在心跳丢失/对账不一致/权益破地板/单小时亏损>3% 时执行相应兜底。
- **FR-015**: Web API 进程 MUST NOT 持有交易 Key，控制指令经 Redis 中转由 strategy 执行。
- **FR-016**: 系统 MUST 经飞书出站告警/日报，致命告警 MUST 走群机器人+加急消息双通道；MUST NOT 依赖飞书做入站控制。
- **FR-017**: 系统 MUST 提供 A 股扩展三接缝（Symbol 市场归属 / ExecutionGateway+MarketCaps / 可插拔闸门），且 MUST NOT 现在实现通用行情协议/账户模型/回测引擎。
- **FR-018**: 阶段推进 MUST 遵守闸门顺序（Testnet→$100→$1000→alpha），前阶段成功标准未达成 MUST NOT 进入下阶段。

### Key Entities

- **Symbol**：带市场归属的标的标识（market + raw → uid），全系统统一以 uid 索引。
- **MarketCaps**：市场能力声明（supports_short / settlement / price_limit / min_lot / has_l2_depth / has_liquidation_feed / calendar），策略层据此查询而非硬判断市场。
- **OrderRequest / OrderAck / Position / Fill**：执行层核心类型，承载幂等 clientOrderId 与对账依据。
- **RiskGate**：风控闸门协议，可组合为链（G1-G14，A 股追加 T1/涨跌停/整手/撤单率）。
- **Signal（总线消息）**：带 source/score/confidence/half_life/evidence 的衰减信号。
- **LLMSignal**：stance/conviction/veto + reasoning + 时效，经校验后进入融合。
- **trade_ledger / config_changes / llm_decisions**：温层核心表，承载全量归因与回放。
- **Strategy 规格（YAML）**：声明式 entry/exit/sizing，**改配置需重启生效**（与风控参数的重启模型统一，避免两套心智；低频交易重启近零成本）+ Git 留痕。**例外**：认知层辩论频率（非风控参数）允许经 UI 运行时调整（agent 每轮重读，范围夹 2min-2h）——风控参数禁改清单不受影响。
- **Universe（YAML）**：三层币种池 + constraints（max_live_symbols 等）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**（A/Testnet）：连续 7×24h 运行，对账偏差事件 = 0，丢单/幽灵仓位 = 0，§5.6 混沌演练全部通过。
- **SC-002**（A+/$100）：真实成交、对账、飞书告警、Web 刹车全链路各至少验证 1 次成功；本金不因系统缺陷（非市场波动）损失。
- **SC-003**（B/$1000）：全程权益 > $850（100% 存活）；实际滑点 vs 回测偏差 < 30%；累计 ≥ 50 笔可归因交易；收益率不作要求。
- **SC-004**（C/alpha）：夏普 > 1.0，最大回撤 < 12%，LLM 层归因净贡献为正（否则依熔断/归因决定去留）。
- **SC-005**（可观测）：任一历史交易可在控制台 100% 取到当时 LLM reasoning、信号值与 config 版本号。
- **SC-006**（成本）：认知层月度花费 ≤ $25；超预算时系统 100% 降级纯量化而非中断交易。
- **SC-007**（安全）：任意单一组件（strategy/feed/cognitive/网络/Redis）失效时，均不导致爆仓或裸持仓（由 1x + 交易所止损 + Watchdog 保证）。

## Assumptions

- 币安账户主体与 KYC 可用，且香港节点网络出口可稳定访问币安 API（R1，最高优先待确认）。
- 操作者全职投入开发、几乎不盯盘；系统以全自动 + 远程刹车运行。
- 初始试运行本金 $100，验证后注资至 $1000，后续无更多追加。
- 现货独有信号不可得，但永续独有信号（资金费率/爆仓流/持仓比）可订阅并用于择时。
- 币安不提供历史 L2 深度，故自录 tick 数据为回测唯一可信来源。
- 阿里云（含香港轻量）、飞书、LLM API、Tailscale、Glassnode 免费档等外部服务账号可获取。
