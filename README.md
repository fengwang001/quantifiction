# Quantifiction

加密货币量化交易研究平台（欧易 OKX 永续 · LLM 认知层 · 影子多策略进化）。
**第一约束：资本保全**——一切设计服从"先零成本证伪，再谈真金"。

> 治理文件：`.specify/memory/constitution.md`（项目宪法 v1.0.0，4 条不可协商原则）
> 完整规格：`specs/001-crypto-quant-trading/`（Spec Kit 全流程：constitution→spec→plan→tasks→analyze）
> 阶段评估：`docs/ASSESSMENT-*.md` · 每轮循环报告在 `data/loop_reports/`（本地）

---

## 一、这个系统是什么

一个**用真实行情做零真金策略进化实验**的平台：

```
欧易实盘行情(REST轮询~6s) ──┐
                            ├─→ 影子引擎：14个策略并行"纸面交易"，扣真实手续费记账
LLM认知层(gemini,30分辩论) ──┘        ↓
                              评估循环(30分钟/轮)：从历史成交总结经验 →
                              生成新策略(老策略与数据全保留) → 直到稳定盈利
```

- **影子模式**：策略只记账不下真单，但按欧易真实价格成交、扣真实费率（taker 往返 0.10%）——盈亏结论可信，风险为零
- **进化循环**：每 30 分钟评估一次全部成交，证据充分才动手（生成新策略/调参），零证据轮次零改动
- **全量留痕**：每笔成交、每次 LLM 辩论（含输入数据快照）、每个策略版本、每个行情 tick 全部实时落盘

## 二、已验证的核心结论（1300+ 笔真实数据）

| 教训 | 数据依据 | 对策（已实现并验证） |
|---|---|---|
| 分钟级高频必亏 | 1215 笔净亏=手续费，止盈 0 次触发，信号无预测力 | 全部停用（数据保留作对照基线） |
| 小时级毛利可覆盖费 | 波段盈利单毛利为手续费 3-8 倍 | 全面波段化（TP 0.8-1.5%，持仓 2-4h） |
| 固定止盈收集回吐 | 多笔 MFE +0.4~0.8% 回吐过半 | **追踪止损**（trail 出场 17/17 全胜） |
| 武装线 0.35% 偏高 | 10+ 例峰值 0.25-0.35 未武装即回落收负 | 灵敏线 0.25%/回撤 0.12% |
| 入场信号族单一 | 6 仓同向同刻被破位团灭 | 异族均值回归（负相关分散，已实证） |

**当前旗舰**：`追踪灵敏版`——7 笔 6 胜（86%）**净值 +0.22 USDT**，是上述全部证据链的结晶。
**停止条件**：新策略各 ≥30 笔、净利为正、夏普>0 → 循环终止。

## 三、Agent 认知层（LLM 辩论）

独立进程，每 30 分钟（页面可调/立即执行/价格急动≥1.5%自动触发）做一次**单调用内化多空辩论**
（gemini-3.1-pro，因供应商并发限制将多空裁决合并为一次调用），产出 `stance/conviction/veto`。

**九类判断依据**（每次辩论的完整输入随决策留档，可回放）：

1. 价格现状（现价/24h/成交额） 2. 多周期K线（5m/1H/4H/**1D×30天**）
3. 资金费率近8期走向 4. 持仓量及2h变化 5. 多空账户比 6. 盘口OBI/点差
7. **新闻+恐惧贪婪指数**（Cointelegraph/Decrypt/alternative.me）
8. **资金面**（DefiLlama：ETH TVL、稳定币市值及1d/7d变化）
9. **宏观/美联储**（DXY、美债10Y、FOMC倒计时、宏观新闻）

并附**自身近 6 次判断记录+事后对错校验**——已观察到教科书级自我修正
（"必须修正此前连续看空的偏差…忽视了日线级别强劲多头趋势"）。

**宪法 II 约束（不可协商）**：LLM 只能 veto（硬否决）或 ±50% 软加成，**永远不能发起交易、不能反转方向**；
输出过 V1-V5 校验，超预算（$1.20/日硬闸）自动降级纯量化。

## 四、Web 看板（http://127.0.0.1:8000）

- **Agent 观点面板**：最新辩论结论/理由/风险 + 辩论频率按钮（5-60分/自定义）+ ⚡立即执行
- **进行中交易**：数量/投入/现在价值/浮动%（实时）
- **策略汇总**：扣费净利排序、胜率、夏普、**全历史净值迷你图**、启停开关
- **策略详情**（点名称或曲线）：定义参数（中文）、来源(🤖Agent/👤人工)、版本演化链、
  净值时间线大图（每点=一笔，悬停详情）、全部成交明细（买卖价/时间/MFE最大浮盈/MAE最大浮亏）
- **⚙ 策略管理**（唯一修改入口）：改参数→服务端格式校验（范围/逻辑关系）→3秒热生效→自动新版本号
- **成交明细**：全量分页、下滑加载更多
- 价格带新鲜度标识（>12s 变红）

## 五、数据留痕（全部实时，本地 `data/`，gitignore 不入库）

| 数据 | 文件 | 时机 |
|---|---|---|
| Agent 全部辩论（含9类数据快照+输出全文） | `agent_decisions.jsonl` | 每次辩论即追加 |
| 全部成交（买卖价/时间/费/净利/MFE/MAE/版本号） | `shadow_persist.json` | 成交即写（原子），重启无损 |
| 策略版本定义（内容哈希，不可变） | `strategy_registry.jsonl` | 变更即追加 |
| **行情 tick 原始流**（盘口5档+特征） | `ticks/日期.jsonl` | 每次轮询(~6s) |
| 评估循环报告 | `loop_reports/*.json` | 每轮 |
| 每日归档 | `snapshots/日期/` | 每日 |

## 六、运行

```bash
uv sync --extra dev                # Python 3.12 依赖
cp .env.example .env               # 填 OKX(三要素,模拟盘) + GRSAI key
uv run pytest -q                   # 132 passed（含契约测试=宪法的工程固化）

# 三个常驻进程
uv run python -m quant.research.shadow_engine     # 影子引擎
uv run python -m quant.cognitive.agent_runner     # Agent 认知层
uv run uvicorn quant.webui.live_dashboard:app --host 127.0.0.1 --port 8000
```

**行情双模式**（`markets/okx_swap/ws_feed.py`）：
- **WS 实时**（`WSPoller`）：设 `WS_PROXY` 即启用，后台线程维护实时订单簿(400档)+逐笔，毫秒级更新，
  断线/冷启动自动 REST 回退。经透传 TLS 的代理（Clash 混合端口 7890）连 `wss://ws.okx.com:8443`——
  一键启动 `scripts/run_shadow_ws.ps1`。
- **REST 轮询**（`RestPoller`）：无 WS_PROXY 时回退，~6s/次，走任意 HTTP 代理。

> 关键坑：普通 HTTP 代理对 CONNECT 回 200 但不透传 TLS 字节流，WS 握手被 RST；
> 需 SOCKS5 或 Clash 这类透明隧道代理。上服务器直连则无需代理，设 `OKX_WS_DIRECT=1` 即可。

## 七、代码结构（src-layout 单包 `quant`）

```
src/quant/
├── core/        Symbol/types/总线/事件（市场无关，A股接缝①）
├── risk/        风控闸门 G1-G14 + 链执行器（接缝③，宪法III最终裁决者）
├── markets/
│   ├── okx_swap/     当前主用：签名客户端/网关(1x锁定+条件止损)/订单簿/信号/RestPoller
│   ├── binance_ums/  完整保留供扩展（pu校验订单簿/网关/对账）
│   └── base.py       ExecutionGateway/MarketDataFeed 协议（接缝②）
├── strategy/    engine(闸门→下单→止损→恢复)/fusion(宪法II融合)/sizing/shadow
├── cognitive/   agent_runner/LLM客户端(grsai)/校验器/熔断器/预算/9类数据源
├── research/    shadow_engine(影子进化)/strategy_registry(版本留痕)/replay/attribution
├── ops/         watchdog(独立进程独立Key)/飞书告警(双通道)
└── webui/       live_dashboard(本地看板)/api(无交易Key+禁改清单)
experiments/     绕过闸门的演示代码（标注禁止实盘）
```

**测试**：132 passed（5 份契约测试把宪法 II/III 固化为合并门禁）。

## 八、路线图

- [x] Spec Kit 全流程规格 + 宪法治理 + 74任务(69完成,余5项需真金环境)
- [x] 欧易接入真实验证（签名/1x锁定/下单/止损/平仓闭环，模拟盘）
- [x] 影子多策略进化循环（37轮评估，首个正净值策略诞生）
- [ ] 灵敏版跑满30笔验证停止条件 → Agent生成策略(DSL+provenance已就位)
- [ ] 香港服务器部署（WS实时/Postgres温层/Watchdog常驻）→ $100 真金冒烟 → $1000 阶段B

## 参考的开源项目（vendor/，本地克隆，不入库不依赖）

- **TradingAgents**：认知层多空辩论范式来源（未集成——其多调用模式在当前LLM通道跑不动，evaluated in docs）
- **Freqtrade**：历史K线下载工具；**Hummingbot**：connector 参考（宪法IV可审计性原因未采用）
