# Contract: Web 控制台 API（宪法 III/IV）

**进程**: webui/api（FastAPI）— **★ 不持有币安交易 Key**
**通信**: 控制指令写 Redis `control:cmd` 流，由 strategy 消费执行

## 只读端点（经 Tailscale + 应用密码）
| 端点 | 返回 |
|---|---|
| GET /status | 权益、持仓、今日 PnL、系统态（RUNNING/PAUSED/HALTED） |
| GET /symbols | 币种表（tier/今日PnL/累计/笔数），live+shadow |
| GET /strategies | 各策略净值/胜率/盈亏比 |
| GET /trades?filter | 交易明细（gross/fee/funding 拆解） |
| GET /trades/{id} | 展开：当时 LLM reasoning 全文 + 信号值 + config_version |
| GET /cognitive | 辩论历史、veto+影子PnL、今日成本/预算余量 |
| GET /health | 心跳、对账偏差、WS 重连、API 权重 |
| WS /stream | 实时权益/持仓推送 |

## 控制端点（写 Redis，非直接交易）
| 端点 | 指令 | 确认 |
|---|---|---|
| POST /control/pause | 暂停开新仓（保留持仓） | 一次 |
| POST /control/resume | 恢复 | 一次 |
| POST /control/flat | 立即全平 | 二次 |
| POST /config/strategy | 改策略阈值 | 二次 + 自动回测校验 + git commit |
| POST /symbols/{uid}/tier | shadow→live 升级 | 二次 + 24h 冷却 |

## 禁改清单（guards.py，返回 403）— 宪法 III
```
❌ 硬地板/软地板   ❌ 单笔风险   ❌ 杠杆倍数
❌ max_live_symbols / max_concurrent_positions
❌ 任何风控闸门 G1-G14 阈值
❌ 认知层预算上限 / 熔断阈值
```
以上仅可改服务器配置文件 + 重启。

### 契约不变量
- **CT-WEB-1**: api 进程环境无交易 Key；即使被攻破也无法下单/转移资金（宪法 IV）。
- **CT-WEB-2**: 任何写风控参数的请求 → 403 + system_events 记录（宪法 III / R10）。
- **CT-WEB-3**: 控制指令经 Redis 中转，strategy 是唯一执行者；api 不直连交易所。
- **CT-WEB-4**: 服务不监听公网接口，仅 Tailscale 网络；应用密码为第二层。
- **CT-WEB-5**: 飞书仅出站；本 API 是唯一入站控制通道（Dashboard+刹车最小页不可砍）。

## 本地阶段看板端点（live_dashboard，2026-07-21 补录）

| 端点 | 类型 | 说明 |
|---|---|---|
| GET /api/shadow | 只读 | 影子对比快照（策略汇总/进行中/agent观点） |
| GET /api/trades?offset&limit | 只读 | 全部成交分页（下滑加载） |
| POST /api/agent/interval?sec | 控制 | 调 agent 辩论频率（写覆盖文件；C3 例外，非风控参数） |
| POST /api/agent/run-now | 控制 | 触发 agent 立即辩论（写信号文件） |

均不持有任何交易 Key（CT-WEB-1 保持）；控制端点仅写本地文件，不触交易所。

## 契约测试要点
- POST 修改地板 → 403 且落 system_events。
- api 进程 env 无交易 Key（断言缺失）。
- /control/flat → 断言 Redis 写入而非交易所调用。
- /trades/{id} → 断言可取到 llm_decisions 全文（回放，SC-005）。
