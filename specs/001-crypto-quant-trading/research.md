# Phase 0 Research: 关键技术决策

**Feature**: 001-crypto-quant-trading | **Date**: 2026-07-21

> 每项以 Decision / Rationale / Alternatives 三段记录。按「证伪成本」排序——越靠前越应尽早验证（宪法 VI）。

---

## R1. 币安账户与网络出口可用性 ⚠️ 最高优先，阻塞性

- **Decision**: 进入任何编码前，先在阿里云香港轻量实例上用真实/Testnet API Key 完成一次 REST 下单 + WS 订阅冒烟。
- **Rationale**: 这是 spec Assumptions 第一条，也是唯一能让整个方案归零的前提（宪法 VI「证伪优先」）。国内节点直连币安受限；香港节点需实测长连接稳定性。
- **Alternatives**: AWS Tokyo（更稳但增加账号面）——保留为香港不可用时的回退；国内+代理——因无人值守下 WS 断线风险否决。
- **Status**: ✅ RESOLVED（2026-07-21）——操作者确认币安账户可用、香港节点连通性 OK。仍建议编码前跑一次 Testnet 冒烟脚本坐实长连接稳定性，但不再阻塞进入真金阶段。

## R2. Connector 分层：官方库 + 自研业务层

- **Decision**: 传输层用 `binance-futures-connector`（签名/限速/时间戳同步）；自研订单状态机、本地订单簿维护、对账（~1000 行）。
- **Rationale**: 宪法 IV「不假设 connector 可靠」+ 可审计性。官方库处理传输边界情况，业务层承载风控语义且需完全可读。
- **Alternatives**: Hummingbot connector——实战里程更高但继承链深、不可审计、与其策略框架耦合，在无人值守+全职开发前提下否决；从零写签名/WS——重复造轮子，否决。

## R3. 本地订单簿维护（合约特有 pu 校验）

- **Decision**: depth@100ms 增量 + REST snapshot(limit=1000)，严格执行 5 步同步；**每事件校验 `pu == 上一事件 u`，不等即触发重建**。
- **Rationale**: 合约独有 `pu` 字段，遗漏导致订单簿静默错位、信号失真（spec Edge Case / FR-001）。
- **Alternatives**: 只用 REST 轮询——延迟高且丢失盘口动态；信任 WS 不校验——静默错位风险，否决。

## R4. 信号总线：Redis Streams + 半衰期衰减

- **Decision**: Redis Streams 承载 Signal（含 score/confidence/half_life/evidence）；消费端按 `score·confidence·exp(-Δt·ln2/half_life)` 衰减。
- **Rationale**: 让 LLM 慢信号与盘口快信号在同一数轴相加；LLM 挂掉时信号自然衰减到 0，系统优雅降级为纯量化（宪法 II）。
- **Alternatives**: Kafka——对单机单用户过重；直接函数调用——耦合各层生命周期，违反解耦与降级要求。

## R5. 认知层编排：LangGraph + PostgresSaver

- **Decision**: 沿用 TradingAgents 的 LangGraph 图，改造数据源为加密；启用 `PostgresSaver` checkpointer，与温层同库。
- **Rationale**: 图的有状态辩论、条件短路（哨兵无变化→END 省钱）、可回放正是所需；checkpoint 关联 llm_decisions 形成完整审计链（宪法 V）。
- **Alternatives**: 自研状态机——重复 LangGraph 能力；无 checkpointer——丧失回放/审计/中断恢复，违反宪法 V。

## R6. LLM 权限的工程固化

- **Decision**: 融合为纯函数 `final_score(quant, llm)`：veto→0；反向→quant×0.3；同向→quant×(1+0.5·stance·conviction)。conviction 上限 clamp 0.8。
- **Rationale**: 宪法 II 不对称边界必须是代码而非约定；纯函数便于契约测试穷举越界输入。
- **Alternatives**: 让 LLM 直接输出目标仓位——根本违反宪法 II，否决；对称加权——放大 LLM 假阳性风险，与「不能亏本金」冲突。

## R7. 成本控制：模型分层 + 事件触发

- **Decision**: 通过 grsai OpenAI 兼容端点分层用模型（哨兵/数据解读用便宜档、研究员/裁决用较强档，模型名在 cognitive.yaml 配置）；哨兵无变化则短路。硬预算 $1.20/天，超支降级纯量化。成本按 total_tokens × 单价（cognitive.yaml `usd_per_1k_total`）计入 BudgetGuard。
- **Rationale**: 短路 + 分层把月度成本压到目标区间（FR-012/SC-006）。
- **Alternatives**: 固定高频辩论——横盘时浪费，否决。

## R7b. LLM 接入：grsai OpenAI 兼容端点（替代 Anthropic SDK）

- **Decision**: 认知层不直连 Anthropic SDK，改走 grsai `/v1/chat/completions`（OpenAI 兼容）。全球节点 https://grsaiapi.com、国内节点 https://grsai.dakka.com.cn，Bearer 鉴权，决策层用非流式。客户端 `cognitive/llm_client.py`，HTTP 传输注入（可测），模型名由 cognitive.yaml 配置（provider 支持多模型）。
- **Rationale**: 统一网关、模型可切换、香港/国内节点均可达（呼应 R8 部署）；依赖从 anthropic 换为 httpx。
- **Alternatives**: 直连各家 SDK——多套鉴权与依赖，否决。
- **约束保持**: 无论用哪个模型/网关，输出仍过 validator→breaker→fusion，权限边界不变（宪法 II）。

## R8. 部署拓扑：香港执行 + 国内研究

- **Decision**: 执行/认知/watchdog/redis 在阿里云香港轻量；归档/回测/Grafana 在国内。执行节点不开公网端口，运维经 Tailscale。
- **Rationale**: 宪法 Additional Constraints；香港稳定连币安，国内做重研究省成本。
- **Alternatives**: 全在国内+代理——WS 断线风险；全在 AWS Tokyo——成本略高，保留为回退。

## R9. 通知：飞书出站 + 加急双通道，无入站控制

- **Decision**: 飞书群机器人 Webhook 出站告警/日报；致命告警并发飞书加急消息（buzz/urgent_phone）；控制（暂停/全平）一律走 Web 控制台。
- **Rationale**: 飞书交互回调需公网，与「执行节点不暴露公网」冲突（宪法 IV / R8）；加急消息零成本第二通道，取代短信。
- **Alternatives**: Telegram——国内不便，已弃；阿里云短信——加急消息已覆盖，去掉省成本。

## R10. Web 安全：API 无交易 Key + 参数禁改

- **Decision**: `webui/api` 进程不持币安 Key，仅向 Redis 写控制指令；`guards.py` 拦截对风控参数（地板/单笔风险/杠杆/并发上限/闸门阈值）的任何写入，返回 403。访问经 Tailscale。
- **Rationale**: 宪法 III/IV；UI 被攻破最坏只能停机而非转移资金；禁改是「防操作者本人冲动」的行为设计。
- **Alternatives**: UI 直连交易——单点致命；公网+密码——攻击面过大，否决。

## R11. 回测数据：自录 tick 为唯一可信源

- **Decision**: `recorder` 从 M1 起全量落盘订单簿增量/逐笔/爆仓流为 Parquet→OSS；回放引擎基于此。K 线可用 Freqtrade 下载补充。
- **Rationale**: 币安不提供历史 L2 深度，第三方 $200-500/月（占本金过高）；无自录数据则含盘口的回测全部不可信（宪法 VI，M1 不可跳过）。
- **Alternatives**: 买 Tardis.dev——成本不成比例；仅用 K 线回测——盘口策略无法验证，否决。

## R12. $100 阶段的标的选择

- **Decision**: $100 阶段 live 层只能用 MIN_NOTIONAL=20 的标的（ETH/SOL），单个小仓位；BTCUSDT（MIN_NOTIONAL=100）启动校验即拒绝。定性为链路冒烟，不追求策略表现。
- **Rationale**: $100 ≈ BTC 最小下单额，无缓冲（spec Edge Case / SC-002）。
- **Alternatives**: $100 直接跑 BTC——无法分仓、无缓冲，否决；跳过 $100 直上 $1000——违反宪法 VI 阶段闸门。

---

## R13. 交易所切换：欧易主用，币安保留（2026-07-21）

- **Decision**: 主用交易所切为欧易 OKX SWAP（用户决定）；币安实现与测试完整保留供扩展。经模拟盘真实验证：三要素签名、1x 锁定、下单/条件单止损/平仓闭环、账户模式预检（acctLv≥2）。
- **Rationale**: 接缝架构（Market 枚举 + ExecutionGateway 协议）使切换零侵入共享层；切换过程暴露并修复了两处硬编码交易所的宪法 VII 违规（engine market 参数化、G5 按基础币归簇）。
- **网络**: 本地开发经代理，REST 用 `www.okx.cab` 备用域名；WS 8443 代理不通 → 本地阶段用 REST 轮询（RestPoller），香港服务器阶段切 WS。

## R14. 本地早期阶段温层：JSON 文件（暂替 Postgres）

- **Decision**: 本地验证阶段温层用追加式 JSON 文件（`shadow_persist.json` 原子写、`agent_decisions.jsonl`、`strategy_registry.jsonl`、每日归档 `data/snapshots/{date}/`），**上服务器阶段迁 Postgres**（schema 已建于 db/migrations）。
- **Rationale**: 宪法 V 的实质（全量留存、可回放、版本关联）已达成；本地单机免去 PG 运维负担。留痕字段与 data-model B 节对齐，迁移为直接导入。
- **Alternatives**: 本地即起 docker PG——可行但对纯验证阶段过重，否决。

## 未决澄清项汇总（供 /speckit-clarify 或线下确认）

| ID | 事项 | 阻塞级别 |
|---|---|---|
| R1 | 币安账户主体/KYC + 香港节点连通性 | ✅ 已确认（2026-07-21），解除 |
| — | Glassnode 免费档字段是否满足 onchain 节点需求 | 🟡 影响认知层数据源 |
| — | 飞书自建应用加急消息权限申请周期 | 🟢 不阻塞开发 |

**全部阻塞性 NEEDS CLARIFICATION 已解析。R1 确认后，无剩余全局阻塞项——可进入 /speckit-tasks 与真金阶段。剩余两项为非阻塞、可并行办理。**
