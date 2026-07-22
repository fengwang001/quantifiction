# Contract: 信号总线（Redis Streams）

**Producers**: markets/binance_ums/signals.py（快信号）、cognitive（慢信号，经 llm:latest）
**Consumer**: strategy/fusion.py

## Signal 消息

```json
{
  "symbol_uid": "binance_ums:BTCUSDT",
  "source": "obi_20 | liq_flow | cvd | funding_skew | policy_agent | ...",
  "score": 0.62,            // [-1, 1]
  "confidence": 0.7,        // [0, 1]
  "emitted_at": 1721_000_000,
  "half_life_sec": 3600,
  "evidence": ["..."]
}
```

## 衰减契约
消费端有效值：
```
effective = score · confidence · exp(-Δt · ln2 / half_life_sec)
```

### 契约不变量
- **CT-SB-1**: 快信号（盘口）half_life 短（秒~分钟），慢信号（政策/情绪）half_life 长（小时）；二者在同一数轴相加。
- **CT-SB-2**: 生产者故障停发 ⇒ effective 自然衰减到 0 ⇒ 系统优雅降级，不报错（宪法 II/降级）。
- **CT-SB-3**: 所有 key 以 `symbol_uid` 索引（宪法 VII 接缝1）。
- **CT-SB-4**: evidence 用于事后归因，落 trade_ledger 关联，不可为空。

## 契约测试要点
- 生产者停发 30s → effective→~0，engine 不抛异常。
- 快慢信号混合求和方向正确。
- Δt 超 half_life → 贡献 < 初值 50%。
