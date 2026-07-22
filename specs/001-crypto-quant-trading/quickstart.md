# Quickstart: 端到端验证指南

**Feature**: 001-crypto-quant-trading | **Date**: 2026-07-21

> 验证顺序 == 宪法 VI 阶段闸门。前一节全绿方可进入下一节。本文件是**验证/运行指南**，实现细节见 tasks.md。
> 契约细节见 `contracts/`，实体见 `data-model.md`。

## 前置（阻塞）
- [ ] **R1**：香港节点用 Testnet Key 冒烟 REST 下单 + WS 订阅成功（research.md R1）
- [ ] Postgres / Redis 就绪；OSS bucket 就绪
- [ ] 飞书机器人 Webhook + 加急应用可用；Tailscale 组网

```bash
# 环境（Key 从环境变量，绝不入库/入 YAML）
export BINANCE_KEY=... BINANCE_SECRET=... BINANCE_TESTNET=1
export PG_DSN=... REDIS_URL=... FEISHU_WEBHOOK=... ANTHROPIC_API_KEY=...
```

---

## 阶段 A — Testnet 正确性（对应 US1，SC-001）

**目标**：连续 7×24h，对账偏差=0、丢单=0、混沌演练全过。

```bash
# 启动各进程（独立）
python -m markets.binance_ums.feed
python -m strategy.engine
python -m ops.watchdog          # 独立 Key
python -m research.recorder
```

验证场景（逐条，对应 §5.6 / contracts）：
1. **正常闭环**：手动注入信号 → 下单 → FILLED → 断言交易所侧 STOP_MARKET 存在（CT-EG-2）。
2. **进程崩溃**：`kill -9` strategy → Watchdog 60s 内兜底平仓 + 飞书告警（US1-AS1）。
3. **断网重连**：断网 60s → 订单簿按 pu 重建、对账一致（US1-AS2，CT-MD-1）。
4. **带仓重启**：持仓时重启 strategy → 恢复仓位+既有 STOP，不重复挂单（US1-AS3）。
5. **Redis 宕机**：停 Redis → 系统停止交易而非带错状态运行。
6. **对账失配**：网页端手动开一仓 → 30s 内 consistent=false → HALTED（CT-EG-3）。
7. **幂等**：并发同 client_order_id → 单仓位（CT-EG-1）。

**通过标准**：7 项全绿 + 连续 7 天 positions_snapshot 全 consistent=true。

---

## 阶段 A+ — $100 链路冒烟（对应 US2/US5，SC-002）

**目标**：真金验证链路，不验证策略。仅 ETH/SOL（BTC 会被 U3 拒绝）。

```bash
export BINANCE_TESTNET=0   # 真实，$100
```
1. universe.yaml 配 ETHUSDT=live, weight=1.0 → 启动校验 U1-U5 通过（US2-AS1/AS2）。
2. 真实小额成交一笔 → trade_ledger 落账，fee/funding 分列（SC-002）。
3. 触发一次致命条件 → 飞书群+加急双通道送达（US5-AS1）。
4. 经 Tailscale 打开控制台 → 点「全平」→ 指令经 Redis→strategy 执行（US5-AS2，CT-WEB-3）。
5. UI 尝试改硬地板 → 403（US5-AS3，CT-WEB-2）。

**通过标准**：5 项全绿，本金无因系统缺陷（非市场波动）的损失。

---

## 阶段 B — $1000 摩擦标定（SC-003）

**目标**：全程 equity>$850，滑点 vs 回测偏差<30%，≥50 笔可归因交易。

```bash
# 注资 $1000；live=1 策略，其余 shadow
python -m cognitive.graph          # LangGraph 认知层接入
python -m webui.api                # 控制台
```
1. shadow 与 live 并排日报（US3-AS1）；每笔可展开 LLM 全文（US3-AS2，SC-005）。
2. **LLM 降级演练**：耗尽预算 → 降级纯量化，不报错（US4-AS1，CT-LLM-4）。
3. **veto 演练**：构造 veto=true → LLMVetoGate 拒单（US4-AS2，G13）。
4. **反向削弱**：stance 与量化反向 → 结果=quant×0.3（US4-AS3，CT-LLM-2）。
5. 累计满 50 笔 → attribution 出 (币×策略×日) 报表。

**通过标准**：SC-003 三项达成；LLM 约束演练全过。

---

## 阶段 C — 追求 alpha（SC-004）

- 归因显示 LLM 净贡献为正则保留，否则依熔断/归因决定去留（US4-AS4）。
- 目标夏普>1.0、最大回撤<12%。
- shadow 币连续 30 日优于 live → 数据驱动升级（宪法 VI）。

---

## 回归验证（每次发布）
```bash
pytest tests/contract      # 5 份 contracts 的契约测试
pytest tests/unit          # 闸门边界、融合纯函数越界
pytest tests/integration   # Testnet 混沌演练
```
**门禁**：contracts 测试全绿是合并前提（宪法 III/II 的工程固化）。
