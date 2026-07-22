---
description: "Task list for 加密量化交易平台（币安永续 + LLM 认知层）"
---

# Tasks: 加密量化交易平台（币安永续 + LLM 认知层）

**Input**: Design documents from `/specs/001-crypto-quant-trading/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅
**Constitution**: v1.0.0（7 原则，I/II/III/V 为 NON-NEGOTIABLE）

**Tests**: 包含契约测试与关键单测——由宪法 II/III「工程固化」与 quickstart「contracts 测试为合并门禁」显式要求。

**Organization**: 按用户故事分组（US1/US2 = P1，US3/US4 = P2，US5 = P3）。

## Format: `[ID] [P?] [Story] Description with file path`
- **[P]**: 可并行（不同文件、无未完成依赖）
- 阶段闸门（宪法 VI）：Phase A 全绿→A+，A+→B，B→C

---

## Phase 1: Setup（共享基础设施）

- [x] T001 创建仓库目录骨架（core/ markets/ strategy/ cognitive/ research/ ops/ webui/ config/ tests/）per plan.md
- [x] T002 初始化 Python 3.12 项目：pyproject.toml + 依赖（binance-futures-connector, redis, psycopg, langgraph, langgraph-checkpoint-postgres, anthropic, fastapi, uvicorn, pyarrow, oss2, pytest, pytest-asyncio）
- [x] T003 [P] 配置 ruff + black + mypy + pre-commit 于 pyproject.toml
- [x] T004 [P] docker-compose：本地 Postgres + Redis（供开发与集成测试）
- [x] T005 [P] 密钥管理约定：Key 从环境变量读，`config/binance.yaml` 不含明文（写 .env.example + README）；**显式列出两把 Key——主交易 Key 与 Watchdog 第二把受限 Key（仅只读+平仓，C6）**
- [x] T006 [P] 香港节点 Testnet 冒烟脚本 `tests/integration/test_r1_smoke.py`（REST 下单 + WS 订阅，坐实 R1）

---

## Phase 2: Foundational（阻塞性前置，所有故事之前必须完成）

**⚠️ CRITICAL**: 本阶段完成前，任何用户故事不得开工。

- [x] T007 [P] 实现 `src/quant/core/symbol.py`：Symbol(market, raw)→uid（接缝1，宪法 VII）
- [x] T008 [P] 实现 `src/quant/core/types.py`：OrderRequest/OrderAck/Position/Fill/MarketCaps/Signal/LLMSignal（data-model A 节）
- [x] T009 实现 `src/quant/core/bus.py`：Redis Streams 封装 + 半衰期衰减读取（contracts/signal-bus.md）
- [x] T010 Postgres schema + 迁移：trade_ledger / llm_decisions / config_changes / positions_snapshot / system_events（data-model B 节）
- [x] T011 [P] OSS Parquet 写入器基础 `src/quant/research/recorder.py` 骨架（data-model D 节 schema，按天分区）
- [x] T012 [P] 结构化日志 + system_events 落库工具 `src/quant/core/events.py`
- [x] T013 定义协议接口 `src/quant/markets/base.py`：ExecutionGateway / MarketDataFeed（接缝2，contracts/execution-gateway.md）
- [x] T014 定义 `src/quant/risk/gate.py`：RiskGate 协议 + GateResult(PASS/REJECT/HALT) + 链执行器（接缝3，contracts/risk-gate.md）
- [x] T015 [P] 契约测试骨架 `tests/contract/`：为 5 份 contracts 建空测试文件与 fixtures

**Checkpoint**: 基础类型、总线、存储、三接缝协议就绪。

---

## Phase 3: User Story 1 — 安全执行与自愈（P1）🎯 MVP

**Goal**: 无人值守下安全下单/平仓，任何组件故障不亏本金。
**Independent Test**: Testnet 逐条跑 quickstart 阶段 A 的 7 场景，交易所止损常驻、对账一致、无丢单双仓。

### 契约测试（先行）
- [x] T016 [P] [US1] 契约测试 `tests/contract/test_execution_gateway.py`：CT-EG-1..6（幂等/止损兜底/对账/caps/官方库签名/**杠杆锁定**）
- [x] T017 [P] [US1] 契约测试 `tests/contract/test_market_feed.py`：CT-MD-1..3（pu 校验重建/StaleData/心跳失联）
- [x] T017a [P] [US1] 契约测试 `tests/contract/test_signal_bus.py`：CT-SB-1..4（快慢信号同轴/生产者停发自然衰减降级/uid 索引/evidence 非空）【C2】
- [x] T018 [P] [US1] 契约测试 `tests/contract/test_risk_gate.py`：G1/G7/G11/G12 + 链无旁路 + STOP 强制（CT-RG-1..4）

### 实现
- [x] T019 [US1] 实现 `src/quant/markets/binance_ums/gateway.py`：封装官方库 + 订单状态机（NEW→SUBMITTED→FILLED/REJECT）+ 幂等 client_order_id（CT-EG-1）
- [x] T019a [US1] gateway 启动时在交易所侧设置 **杠杆=1（POST /fapi/v1/leverage）+ marginType=CROSSED + 单向持仓**，并断言交易所返回值一致；不一致则拒绝启动（CT-EG-6，宪法 III/IV「最终防线 F7」）【C1】
- [x] T020 [US1] 在 gateway 实现 `place_protective_stop` + 「挂失败即市价平仓」（CT-EG-2，宪法 III）
- [x] T021 [US1] 实现 `src/quant/markets/binance_ums/feed.py`：WS 订阅 + 本地订单簿 5 步同步 + pu 校验重建（CT-MD-1，R3）
- [x] T022 [US1] 实现 `src/quant/markets/binance_ums/reconcile.py`：userDataStream ACCOUNT_UPDATE + 30s 对账 → positions_snapshot（CT-EG-3）
- [x] T023 [P] [US1] 实现 `src/quant/markets/binance_ums/caps.py`：币安 MarketCaps 实例（动态读 exchangeInfo min_notional）
- [x] T024 [US1] 实现风控闸门子集 `src/quant/risk/common_gates.py` 之 G1/G7/G11/G12（HardFloor/HourlyLoss/Reconcile/StaleData）
- [x] T025 [US1] 实现 `src/quant/strategy/engine.py` 最小主循环：接信号→过闸门链→下单→挂止损→心跳（无策略/无 LLM）
- [x] T026 [US1] 实现带仓重启恢复：启动检查既有仓位+STOP，不重复挂单（quickstart A-场景4）
- [x] T027 [US1] 实现 `src/quant/ops/watchdog.py`：独立进程 + 独立只读+平仓 Key；心跳丢失/对账失配/破地板/单小时亏损 → 全平停机（FR-014，宪法 IV）
- [x] T028 [P] [US1] 实现 `src/quant/ops/feishu.py`：出站告警 + 加急消息双通道（致命告警，FR-016）

### 混沌演练（阶段 A 门禁）
- [ ] T029 [US1] 集成测试 `tests/integration/test_chaos.py`：kill -9 / 断网60s / Redis宕机 / 时钟偏移 / 手动失配（§5.6 DoD）
- [ ] T030 [US1] 阶段 A 验收：Testnet 连续 7×24h，positions_snapshot 全 consistent，丢单=0（SC-001）

**Checkpoint**: US1 独立可用——安全执行核心成立，即使无策略无 LLM 也不会爆仓。**这是 MVP。**

---

## Phase 4: User Story 2 — 币种池与风险预算下单（P1）

**Goal**: YAML 配置 live/shadow/observe 三层，按 $150/$15 风险预算在容量内自动算仓。
**Independent Test**: 加载 universe.yaml，U1-U5 校验；live 下单量落在约束内，shadow 只记账。

### 契约/单元测试
- [x] T031 [P] [US2] 单元测试 `tests/unit/test_universe_validation.py`：U1-U5（含 $100 拒 BTC，US2-AS2）
- [x] T032 [P] [US2] 单元测试 `tests/unit/test_sizing.py`：风险预算=$150→名义敞口计算 + MinNotional 边界

### 实现
- [x] T033 [US2] 实现 `src/quant/strategy/spec_loader.py`：universe.yaml + strategies/*.yaml + **cognitive.yaml** 加载 + 启动硬校验 U1-U5 **及 cognitive 预算≤硬上限/max_per_day 存在（C4）**；改配置需重启生效（C3）（FR-006）
- [x] T034 [US2] 实现 `src/quant/strategy/sizing.py`：以工作资金风险预算为基数→目标仓位（FR-007，宪法 I）
- [x] T035 [US2] 补全闸门 G2/G3/G4/G5/G6/G8/G9/G10/G13/G14 于 `src/quant/risk/common_gates.py`
- [x] T036 [US2] 实现 `src/quant/strategy/shadow.py`：shadow 层假想成交→trade_ledger(tier=shadow)，不下单（FR-008，CT 分离）
- [x] T037 [US2] engine 接入 sizing + 完整闸门链 + universe（live 实盘 / shadow 记账 / observe 只录）
- [x] T038 [P] [US2] 配置样例 `config/universe.yaml` + `config/strategies/liq_reversal.yaml`

**Checkpoint**: US1+US2 = 完整安全的自动执行（含正确仓位与多层币种池）。

---

## Phase 5: User Story 3 — 全量留存与每币每日归因（P2）

**Goal**: 查看 (币×策略×日) 净收益（成本拆解），回放任一笔交易的完整依据。
**Independent Test**: 跑批 live+shadow 成交，按维度聚合 gross/fee/funding/net；抽一笔取到当时决策全文。

- [x] T039 [P] [US3] 单元测试 `tests/unit/test_ledger_attribution.py`：net=gross-fee+funding；(币×策略×日) 聚合
- [x] T040 [US3] 完善 trade_ledger 写入：fee/funding/gross 分列 + config_version 关联（FR-010，宪法 V）
- [x] T041 [US3] 实现 `src/quant/research/recorder.py` 全量落盘：orderbook_delta/agg_trades/force_orders/funding_mark→OSS（FR-009，R11）
- [x] T042 [US3] 实现 `src/quant/research/attribution.py`：(币×策略×日) 报表 + live/shadow 并排 + LLM 贡献占位
- [x] T043 [US3] 实现每日报告生成（UTC0）→ 飞书日报群卡片（含成本拆解，US3-AS1）
- [x] T044 [P] [US3] config_changes 留痕：YAML 变更→git_sha+diff 落库（宪法 V）

**Checkpoint**: 具备数据驱动决策能力——能判断跑得好不好、为什么。

---

## Phase 6: User Story 4 — LLM 认知层受约束地提供方向与否决（P2）

**Goal**: LangGraph 多智能体在受控频率/预算内产出 stance/veto，输出层层受约束，绝不发起或放大风险。
**Independent Test**: 断 LLM→降级纯量化正常；注入越界输出→校验/熔断处置；veto 硬否决、反向仅削弱。

### 契约测试（宪法 II 固化）
- [x] T045 [P] [US4] 契约测试 `tests/contract/test_llm_output.py`：CT-LLM-1..5 穷举越界（veto/反向不反转/±50%上限/None降级/clamp）
- [x] T046 [P] [US4] 单元测试 `tests/unit/test_validator.py`：V1-V5 校验链
- [x] T047 [P] [US4] 单元测试 `tests/unit/test_breaker.py`：连续亏损 5/8/12 熔断 + veto 精确率

### 实现
- [x] T048 [US4] 实现 `src/quant/strategy/fusion.py`：final_score 纯函数（contracts/llm-output.md，宪法 II）
- [x] T049 [US4] 实现 `src/quant/cognitive/validator.py`（V1-V5）+ `src/quant/cognitive/breaker.py`（§6.6）
- [x] T050 [US4] 实现 `src/quant/cognitive/budget.py`：$1.20/天预算守卫 + 超支降级纯量化（FR-012，CT-LLM-4）
- [x] T051 [US4] 实现 `src/quant/cognitive/graph.py`：LangGraph 图（sentinel→analysts→bull/bear→trader→risk）+ 哨兵短路（R5）
- [x] T052 [US4] 配置 `src/quant/cognitive/checkpointer.py`：PostgresSaver + graph_run_id（FR-011，宪法 V）
- [x] T053 [P] [US4] 实现 `src/quant/cognitive/datasource/crypto/`：news/sentiment/onchain/derivatives/macro
- [x] T054 [US4] 实现 `src/quant/cognitive/recorder.py`：llm_decisions 全文（full_prompt/output/bull/bear）落库（FR-009）
- [x] T055 [US4] 频率三档调度（哨兵15min/定时3次/事件）+ 模型分层（Haiku/Sonnet/Opus）+ prompt caching（R7）
- [x] T056 [US4] engine 接入 fusion：LLM 信号经 validator→breaker→fusion→sizing→闸门（宪法 II 全链）

**Checkpoint**: 认知层上线且完全受控；LLM 挂掉系统降级纯量化。

---

## Phase 7: User Story 5 — 远程监控与紧急刹车（P3）

**Goal**: 飞书告警/日报；经 Tailscale 进 Web 控制台暂停/全平；风控参数 UI 不可改。
**Independent Test**: 致命条件→双通道送达；控制台点全平→经 Redis 执行；改地板→403。

### 契约测试
- [x] T057 [P] [US5] 契约测试 `tests/contract/test_webui_api.py`：CT-WEB-1..5（无交易Key/禁改403/Redis中转/Tailscale/唯一入站）

### 后端（先行，最小控制页不可砍）
- [x] T058 [US5] 实现 `src/quant/webui/api/control.py`：pause/resume/flat 写 Redis control:cmd（CT-WEB-3，FR-015）
- [x] T059 [US5] 实现 `src/quant/webui/api/guards.py`：禁改清单→403 + system_events（CT-WEB-2，宪法 III）
- [x] T060 [US5] 实现只读端点 `src/quant/webui/api/routes/`：status/symbols/strategies/trades/cognitive/health + WS /stream
- [x] T061 [US5] engine 消费 control:cmd 执行 pause/resume/flat（strategy 为唯一执行者）

### 前端
- [x] T062 [P] [US5] React 脚手架 Vite + shadcn/ui + Tailscale 部署说明
- [x] T063 [P] [US5] Dashboard 页：权益曲线(含地板线) + 刹车按钮（**最小控制页，实盘前必须**）
- [x] T064 [P] [US5] Symbols/Strategies/Trades 页（Trades 可展开 LLM reasoning，SC-005）
- [x] T065 [P] [US5] Cognitive/Health 页 + Config 页（Monaco YAML 编辑，二次确认）

**Checkpoint**: 全部用户故事完成。

---

## Phase 8: Polish & 阶段闸门验收（宪法 VI）

- [ ] T066 [P] 阶段 A+ 验收：$100 真金链路冒烟（ETH/SOL，成交/对账/告警/刹车各≥1次，SC-002）
- [x] T067 实现 `src/quant/research/replay.py`：基于自录 tick 的订单簿回放回测引擎（R11，M2 能力）
- [x] T068 [P] Freqtrade 历史 K 线下载脚本（辅助回测数据）
- [ ] T069 阶段 B 验收：$1000 实盘，equity>$850 全程，滑点偏差<30%，≥50 笔（SC-003）
- [x] T070 [P] A 股接缝自检：ashare/ 仅 README；caps 驱动分支测试（宪法 VII，FR-017）
- [x] T071 运行 `/speckit-analyze` 跨工件一致性审计 + 全量 pytest 回归门禁
- [ ] T072 阶段 C 入口：attribution 出 LLM 净贡献结论，决定认知层去留（SC-004，US4-AS4）

---

## Dependencies & 执行顺序

```
Phase 1 Setup → Phase 2 Foundational（阻塞全部）
    ↓
Phase 3 US1（P1，MVP）──→ 阶段 A 门禁（T030）
    ↓
Phase 4 US2（P1，依赖 US1 的 engine/闸门）
    ↓
    ├─ Phase 5 US3（P2，依赖 US2 产出成交数据）
    └─ Phase 6 US4（P2，依赖 US2 engine；与 US3 可并行）
         ↓
Phase 7 US5（P3，依赖 US1-US4 的数据面）
    ↓
Phase 8 Polish + 阶段 A+/B/C 闸门
```

**故事间独立性**：US1 独立可交付（MVP）；US2 依赖 US1 的 engine；US3/US4 依赖 US2 但彼此可并行；US5 依赖前四者的读模型。

## 并行机会（[P] 任务）

- Setup：T003/T004/T005/T006 并行
- Foundational：T007/T008/T011/T012/T015 并行
- US1 契约测试：T016/T017/T017a/T018 并行；T023/T028 与主链并行
- US4 测试：T045/T046/T047 并行；数据源 T053 并行
- US5 前端：T062/T063/T064/T065 并行
- Polish：T066/T068/T070 并行

## Implementation Strategy（MVP 优先，增量交付）

1. **MVP = Phase 1+2+3（US1）**：一个「能安全下单、故障自愈、绝不爆仓」的执行核心。即使到此为止，也是有价值的半自动交易安全底座。
2. **增量 2 = +US2**：加正确仓位与币种池 → 完整自动执行。
3. **增量 3 = +US3+US4**：加归因与受控 LLM → 完整平台（此时才碰 $1000）。
4. **增量 4 = +US5**：加 Web 控制台（Dashboard+刹车最小页在实盘前随 US1 数据面补齐）。
5. 每个增量后跑对应阶段闸门（A→A+→B→C），前一阶段不达标不进下一阶段。

**总计 74 任务**（含 analyze 修订 T017a/T019a）。
