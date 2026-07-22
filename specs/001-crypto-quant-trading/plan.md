# Implementation Plan: 加密量化交易平台（币安永续 + LLM 认知层）

**Branch**: `001-crypto-quant-trading` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-crypto-quant-trading/spec.md`
**Constitution**: `.specify/memory/constitution.md` v1.0.0

## Summary

构建一个以**资本保全为第一约束**的个人量化交易平台，连接币安 USDⓈ-M 永续（1x 锁定）。技术路径：Python 事件驱动，传输层复用币安官方库、仅自研可审计业务层（订单状态机 / 本地订单簿 / 对账，~1000 行）；确定性风控闸门链为最终裁决者；LangGraph 编排的 LLM 认知层只能软加成/硬否决、不能发起交易；全量数据永久留存供回放与再分析。分阶段解锁：Testnet 混沌演练 → $100 链路冒烟 → $1000 摩擦标定 → 追求 alpha。

## Technical Context

**Language/Version**: Python 3.12（与 spec-kit 环境一致；asyncio 事件驱动）

**Primary Dependencies**:
- 执行/行情：`binance-futures-connector`（官方，传输层）、`aiohttp` / `websockets`（官方库内部）
- 总线/缓存：Redis（Redis Streams 信号总线 + 热态）、`redis-py`
- 存储：PostgreSQL（温层）、Parquet + 阿里云 OSS SDK（冷层）
- 认知层：LangGraph + LangChain、`langgraph-checkpoint-postgres`（PostgresSaver）
- LLM：Anthropic SDK（Opus 4.8 / Sonnet 5 / Haiku 4.5 分层）
- Web：FastAPI + Uvicorn（后端）、React + Vite + TanStack Query + Recharts（前端）
- 通知：飞书自定义机器人 Webhook + 自建应用（加急消息）
- 回测：自研 tick 回放引擎；Freqtrade 仅用于历史 K 线下载

**Storage**: PostgreSQL（trade_ledger / config_changes / llm_decisions / positions_snapshot）；Redis（signals 流 / 心跳 / 持仓热态，TTL）；OSS Parquet（订单簿增量 / 逐笔 / 爆仓流，按天分区，永久）

**Testing**: pytest（单元 + 契约）；pytest-asyncio；混沌演练脚本（进程 kill / 断网 / Redis 宕机注入）；Testnet 集成测试

**Target Platform**: Linux 服务器。执行节点：阿里云香港轻量（境外，稳定连币安）；研究/归档/可视化节点：阿里云国内（已有）

**Project Type**: Web（多进程后端服务 + React 前端控制台）

**Performance Goals**: 非低延迟。信号计算 < 1ms；下单 REST 往返 10-30ms；系统级目标是**正确性与可用性**（对账偏差 0、丢单 0、可用性 > 99%），而非吞吐/延迟

**Constraints**:
- 硬地板 $850（$100 阶段 $85）；1x 杠杆锁定；工作资金风险预算 $150/$15
- 认知层预算 $1.20/天、$25/月；WS 深度推送 100ms 硬下限
- 执行节点不暴露公网；风控参数不可经 UI 修改

**Scale/Scope**: 单用户；live 标的 1-2 个 + shadow ≤ 8；日均 1-3 笔；模块规模自研业务层 ~1000 行，全平台 MVP 约 5 个 P1/P2 用户故事

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | 宪法原则 | 本计划的落实 | 门禁 |
|---|---|---|---|
| I | 资本保全优先 | 硬地板闸门 G1 + 交易所侧 STOP_MARKET + 风险预算基数 = 工作资金 | ✅ PASS |
| II | LLM 不对称边界 | 融合公式硬编码（veto 硬否决 / stance ×0.3 反向削弱 / ±50% 上限）；LangGraph 出口过校验器→边界→熔断 | ✅ PASS |
| III | 确定性风控最终裁决 | G1-G14 闸门链在下单前强制执行；风控参数仅配置文件可改（webui/api/guards.py 拦截） | ✅ PASS |
| IV | 防御纵深 | Watchdog 独立进程+独立 Key；Web API 无交易 Key；对账 30s；致命告警双通道 | ✅ PASS |
| V | 全量留存可回放 | 三层存储；llm_decisions 存 full_prompt/output；PnL 拆解 (币×策略×日)；config 版本关联 | ✅ PASS |
| VI | 先验证后加码 | 阶段闸门（M0→M4.8→M5→C）编码为里程碑 DoD；shadow 数据驱动升级 | ✅ PASS |
| VII | 必要接缝抽象 | 仅三接缝（Symbol/Gateway+Caps/Gate 链）；明确不做通用行情/账户/回测 | ✅ PASS |

**初评结论**：无违反项。Complexity Tracking 表留空。

**设计后复评**：见文末「Post-Design Constitution Re-Check」。

## Project Structure

### Documentation (this feature)

```text
specs/001-crypto-quant-trading/
├── plan.md              # 本文件
├── research.md          # Phase 0：关键技术决策
├── data-model.md        # Phase 1：实体与表结构
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/           # Phase 1：接口契约
│   ├── signal-bus.md         # Redis Streams 信号消息契约
│   ├── execution-gateway.md  # ExecutionGateway 协议 + MarketCaps
│   ├── risk-gate.md          # RiskGate 协议 + G1-G14
│   ├── llm-output.md         # LLMSignal schema + 融合契约
│   └── webui-api.md          # 控制台 REST/WS + guards 禁改清单
└── tasks.md             # 由 /speckit-tasks 生成，本命令不创建
```

### Source Code (repository root)

```text
src/quant/                       # src-layout 单包，统一命名空间
├── core/                        # 市场无关（A股复用）
│   ├── symbol.py                # 接缝1：Symbol(market, raw)→uid
│   ├── types.py                 # Order/Position/Fill/MarketCaps/OrderBook/Signal/LLMSignal
│   ├── bus.py                   # Redis Streams 封装（半衰期衰减）
│   └── events.py                # 结构化事件 → system_events
├── risk/                        # 接缝3（提为顶层子包）
│   ├── gate.py                  # RiskGate 协议 + 链执行器
│   └── common_gates.py          # G1-G14
├── markets/
│   ├── base.py                  # 接缝2：ExecutionGateway / MarketDataFeed 协议
│   ├── okx_swap/                # ★ 当前主用（R13）：签名客户端/网关/订单簿/信号/REST轮询
│   │   ├── okx_client.py · gateway.py · feed.py · caps.py
│   │   ├── signals.py           # OBI/CVD/挂单墙/资金费率
│   │   └── ws_feed.py           # WS解析(生产) + RestPoller(本地代理阶段)
│   ├── binance_ums/             # 保留扩展（feed/gateway/reconcile/caps 完整）
│   └── ashare/                  # 空目录 + README（不实现）
├── strategy/
│   ├── fusion.py                # 融合公式（按 caps 过滤 + LLM 约束）
│   ├── sizing.py                # 风险预算 → 目标仓位
│   ├── engine.py                # L2 决策主循环 + 心跳
│   ├── spec_loader.py           # YAML 加载 + 启动校验（改配置需重启）
│   └── shadow.py                # 影子模式
├── cognitive/                   # LangGraph 认知层
│   ├── graph.py                 # 图（sentinel→analysts→bull/bear→trader→risk）
│   ├── checkpointer.py          # PostgresSaver
│   ├── nodes/ · datasource/crypto/
│   ├── validator.py · breaker.py · budget.py
│   └── recorder.py              # llm_decisions 全文落库
├── research/
│   ├── recorder.py              # tick 全量落盘 → Parquet/OSS
│   ├── replay.py · attribution.py
│   ├── shadow_engine.py         # 影子多策略对比（扣费/持久化/Agent增强）
│   └── strategy_registry.py     # 策略快照/版本哈希/provenance（P2 留痕）
├── cognitive/（补）
│   └── agent_runner.py          # 极简 agent 独立进程（gemini 辩论→stance/veto，预算硬闸）
├── webui/（补）
│   └── live_dashboard.py        # 本地实时看板（影子对比/成交分页/agent面板）
├── experiments/（仓库根）        # 禁止实盘的演示代码（live_runner_demo，C1 处置）
├── ops/
│   ├── watchdog.py              # 独立进程 + 独立 Key
│   └── feishu.py                # 告警/日报 + 加急消息
└── webui/
    ├── api/                     # FastAPI，★ 无交易 Key（control.py / guards.py / routes/）
    └── frontend/                # React + Vite

# 根目录其余（与 src/ 平级，职责清晰分离）
config/     # binance.yaml / universe.yaml / strategies/*.yaml / cognitive.yaml
db/migrations/   # 温层 schema
tests/      # contract/ · integration/ · unit/
docs/ · specs/ · vendor/（第三方参考，不依赖）
```

**Structure Decision**: 采用 **src-layout 单包**（`src/quant/`），根目录只保留 `src/config/db/tests/docs/specs/vendor` 与少量入口文件，应用代码与文档/第三方/工具清晰分离；统一 `quant.*` 命名空间避免与 vendor 包名冲突。运行时后端仍是多进程（`feed`/`strategy`/`cognitive`/`watchdog`/`recorder`/`webui-api` 独立，宪法 IV），经 Redis 解耦——进程边界与包结构正交。分层对应宪法：`core` 市场无关、`markets` 具体实现、`strategy` 仅依赖 `quant.core`+`quant.markets.base`（不依赖具体市场）、`cognitive` 输出必过 validator→breaker。三接缝（`core/symbol.py` / `markets/base.py` / `risk/gate.py`）为 A 股预留的唯一抽象点。

## Complexity Tracking

> 无宪法违反项，本表留空。

## Post-Design Constitution Re-Check

*Phase 1 设计完成后复评（见 research.md / data-model.md / contracts/）：*

| 原则 | 设计产物核验 | 结论 |
|---|---|---|
| I | data-model：equity 快照 + G1 地板；contracts/risk-gate 定义 STOP_MARKET 强制 | ✅ 保持 |
| II | contracts/llm-output：融合公式为纯函数契约，veto/stance 不对称固化；图出口单一 | ✅ 保持 |
| III | contracts/risk-gate：闸门链无旁路；webui-api 契约明列禁改字段返回 403 | ✅ 保持 |
| IV | contracts/webui-api：api 无交易 Key；data-model：watchdog 独立 Key 记录 | ✅ 保持 |
| V | data-model：llm_decisions/trade_ledger/config_changes 全字段；冷层 Parquet schema | ✅ 保持 |
| VI | quickstart：阶段闸门作为验证顺序；research：证伪优先顺序 | ✅ 保持 |
| VII | contracts/execution-gateway：MarketCaps 能力查询；ashare 仅 README | ✅ 保持 |

**无新增违反项。设计通过宪法门禁，可进入 /speckit-tasks。**
