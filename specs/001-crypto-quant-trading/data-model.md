# Phase 1 Data Model: 实体与存储

**Feature**: 001-crypto-quant-trading | **Date**: 2026-07-21

> 三层存储（宪法 V）：冷=OSS Parquet；温=PostgreSQL；热=Redis。下列按层组织。

---

## A. 核心值对象（core/types.py，内存态）

### Symbol（接缝1）
| 字段 | 类型 | 说明 |
|---|---|---|
| market | Enum{BINANCE_UMS, ASHARE} | 市场归属 |
| raw | str | 交易所原生代码，如 BTCUSDT |
| uid | str（派生） | `{market}:{raw}`，全系统统一索引 |

**规则**：所有信号/仓位/日志/Redis key 一律用 uid。禁止裸字符串比较市场。

### MarketCaps（接缝2）
| 字段 | 类型 | 币安值 |
|---|---|---|
| supports_short | bool | True |
| settlement | Enum{T0,T1} | T0 |
| price_limit_pct | float\|None | None |
| min_lot | int | 1 |
| min_notional | Decimal | 动态读 exchangeInfo |
| has_l2_depth | bool | True |
| has_liquidation_feed | bool | True |
| trading_calendar | Calendar | 24/7 |

**规则**：策略层查询 caps，禁止 `if market==BINANCE`（宪法 VII）。

### OrderRequest / OrderAck / Position / Fill
| 实体 | 关键字段 | 不变量 |
|---|---|---|
| OrderRequest | symbol_uid, side, type, qty, price?, client_order_id, reduce_only | client_order_id 幂等唯一 |
| OrderAck | exchange_order_id, client_order_id, status, ts | 与请求 client_order_id 对应 |
| Position | symbol_uid, side, qty, entry_px, unrealized_pnl, leverage | leverage==1（锁定） |
| Fill | order_id, price, qty, fee, ts, is_maker | 累加得 Position |

### OrderBook（feed 本地维护，见 contracts/execution-gateway.md CT-MD-1）
| 字段 | 类型 | 说明 |
|---|---|---|
| symbol_uid | str | 归属标的 |
| bids | sorted[(price, qty)] | 买档 |
| asks | sorted[(price, qty)] | 卖档 |
| last_update_id | int | 快照/增量同步锚点（币安 u） |
| prev_update_id | int | 上一事件 u，用于 `pu==prev.u` 校验 |
| updated_at | int(ms) | 供 StaleDataGate 计算年龄 |

**规则**：维护须执行 5 步同步；`pu != prev_update_id` 即触发快照重建（合约特有，R3）。

### Signal（总线消息，见 contracts/signal-bus.md）
| 字段 | 类型 |
|---|---|
| symbol_uid, source, score[-1,1], confidence[0,1], emitted_at, half_life_sec, evidence[] |

### LLMSignal（认知层出口，见 contracts/llm-output.md）
| 字段 | 类型 | 约束 |
|---|---|---|
| symbol_uid, stance[-1,1], conviction[0,0.8], veto:bool, half_life_sec, reasoning, key_risks[] | conviction 硬 clamp 0.8 |

---

## B. 温层：PostgreSQL（永久保留 + 定期备份 OSS）

### trade_ledger（每笔交易，含 shadow）
```
trade_id PK, symbol_uid, strategy, tier{live|shadow},
open_ts, close_ts, side, entry_px, exit_px, qty, notional_usd,
gross_pnl, fee, funding_pnl, net_pnl,          -- 三者分离（宪法 V）
slippage_bps,
llm_stance, llm_conviction, llm_veto,          -- 归因
quant_score, config_version FK
```
**不变量**：net_pnl = gross_pnl - fee + funding_pnl；聚合可得 (币×策略×日)。

### llm_decisions（每次 LLM 决策，全文）
```
decision_id PK, ts, symbol_uid, trigger{scheduled|sentinel|event},
graph_run_id,                                  -- 关联 LangGraph checkpoint
model_versions JSONB,
full_prompt TEXT, full_output TEXT,            -- ★ 完整留存（宪法 V）
bull_argument TEXT, bear_argument TEXT,
trader_verdict JSONB,                          -- stance/conviction/veto
token_cost, latency_ms
```
**不变量**：full_prompt/full_output 非空；trigger=sentinel 且无变化时可只写轻量行。

### config_changes（配置留痕）
```
config_version PK (自增), ts, actor, file, diff TEXT, git_sha
```
**规则**：每笔交易的 config_version 指向此表；风控参数变更也必须在此留痕（且只能来自文件，非 UI）。

### positions_snapshot（对账留痕）
```
ts, symbol_uid, local_qty, exchange_qty, consistent:bool
```
**规则**：每 30s 一行；consistent=false → 触发停机事件。

### system_events（运行事件日志）
```
event_id PK, ts, severity{info|warn|fatal}, source, kind, payload JSONB
```
**规则**：闸门拒单、熔断、地板触及、Watchdog 动作、WS 重连全部落此表。

---

## C. 热层：Redis（TTL 过期，不持久化真相）

| Key/Stream | 类型 | TTL | 用途 |
|---|---|---|---|
| `signals:{uid}` | Stream | 短 | 信号总线 |
| `heartbeat:{proc}` | String | 60s | 进程心跳（Watchdog 监控） |
| `position:{uid}` | Hash | — | 持仓热态（真相仍以交易所为准） |
| `control:cmd` | Stream | — | Web→strategy 控制指令（pause/flat/resume） |
| `llm:latest:{uid}` | Hash | half_life | 最近 LLM 信号缓存 |
| `ratelimit:weight` | String | 60s | X-MBX-USED-WEIGHT 监控 |

**规则**：真相数据（仓位/成交）永远以交易所 ACCOUNT_UPDATE + Postgres 为准，Redis 仅热态。

---

## D. 冷层：OSS Parquet（按天分区，永久，不可复得资产）

| 数据集 | 分区 | 字段要点 |
|---|---|---|
| `orderbook_delta/{uid}/{date}` | 日 | ts, side, price, qty, first_update_id, final_update_id, pu |
| `agg_trades/{uid}/{date}` | 日 | ts, price, qty, is_buyer_maker |
| `force_orders/{uid}/{date}` | 日 | ts, side, price, qty（爆仓流） |
| `funding_mark/{uid}/{date}` | 日 | ts, mark_price, funding_rate |

**规则**：recorder 从 M1 起全量落盘；回放引擎的唯一可信输入（宪法 VI / R11）。

---

## E. 配置实体（YAML + Git，config_changes 留痕）

| 文件 | 关键结构 | 启动校验 |
|---|---|---|
| `universe.yaml` | 每 symbol：tier/strategies/capital_weight/max_notional_usd；constraints | U1-U5（见 spec） |
| `strategies/*.yaml` | name/version/symbols/entry/exit/sizing | 引用信号存在；sizing 不超风险预算 |
| `cognitive.yaml` | sentinel/deliberation/events/budget | 预算 ≤ 硬上限；max_per_day 存在 |
| `binance.yaml` | endpoints/testnet 开关（不含明文 Key） | Key 从环境变量/密钥管理读 |

---

## 状态机（关键）

### 订单状态
```
NEW → SUBMITTED → (PARTIALLY_FILLED) → FILLED
                → REJECTED（闸门/交易所）
                → CANCELED
FILLED → 立即挂 STOP_MARKET（reduce_only）
       → STOP 挂失败 → 强制市价平仓（不允许裸持仓）
```

### 系统运行态（Watchdog 视角）
```
RUNNING → PAUSED（暂停开新仓，保留持仓）
        → HALTED（全平+停机，需人工重启）
触发 HALTED：equity<地板 / 单小时亏损>3% / 对账不一致 / 心跳丢失>60s
```
