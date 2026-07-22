# Contract: ExecutionGateway + MarketDataFeed（接缝2）

**Consumers**: strategy/engine.py, ops/watchdog.py
**Implementors**: `markets/okx_swap/`（**当前主用**，含账户模式预检 + 条件单止损）、`markets/binance_ums/`（保留扩展）、A股未来实现 `markets/ashare/`

## ExecutionGateway (Protocol)

```python
class ExecutionGateway(Protocol):
    async def submit(self, order: OrderRequest) -> OrderAck: ...
    async def cancel(self, client_order_id: str) -> None: ...
    async def positions(self) -> list[Position]: ...
    async def reconcile(self) -> ReconcileResult: ...       # 与远端对账
    async def place_protective_stop(self, pos: Position, stop_px: Decimal) -> OrderAck: ...
    @property
    def caps(self) -> MarketCaps: ...
```

### 契约不变量
- **CT-EG-1**: `submit` 必须幂等——同一 `client_order_id` 重复提交不产生第二个仓位（幂等键去重）。
- **CT-EG-2**: 每个成交后 consumer 必须调用 `place_protective_stop`；返回失败则 consumer 必须立即市价平仓（宪法 III，不允许裸持仓）。
- **CT-EG-3**: `reconcile` 以交易所 `ACCOUNT_UPDATE` 为唯一真相；`ReconcileResult.consistent=false` 时 consumer 停机（宪法 IV）。
- **CT-EG-4**: `caps` 只读且稳定；consumer 通过 caps 查询能力，禁止基于 `market` 硬编码分支（宪法 VII）。
- **CT-EG-5**: gateway 内部复用币安官方库做签名/限速；业务层不自行实现签名。
- **CT-EG-6**（宪法 III/IV 最终防线 F7）: gateway 启动时必须在交易所侧将标的杠杆设为 **1x**、marginType=CROSSED、持仓模式为单向，并读回校验一致；任一不一致必须**拒绝启动**（不得带着 >1x 杠杆运行）。运行期不得调高杠杆。

## MarketDataFeed (Protocol)

```python
class MarketDataFeed(Protocol):
    async def subscribe(self, symbols: list[Symbol]) -> None: ...
    def orderbook(self, uid: str) -> OrderBook: ...          # 本地维护
    def last_update_age_ms(self, uid: str) -> int: ...       # 供 StaleDataGate
    async def stream_events(self) -> AsyncIterator[MarketEvent]: ...
```

### 契约不变量
- **CT-MD-1**: 订单簿维护必须执行 5 步同步 + `pu==prev.u` 校验；校验失败必须重建快照（R3）。
- **CT-MD-2**: `last_update_age_ms > 5000` 时，StaleDataGate 拒单（宪法 III / FR-012 边界）。
- **CT-MD-3**: feed 崩溃不得静默——须置心跳失联，由 Watchdog 接管。

## 契约测试要点（tests/contract/）
- 幂等：并发提交同 client_order_id → 单仓位。
- 止损兜底：mock `place_protective_stop` 失败 → 断言触发市价平仓。
- 对账：注入交易所侧多出一仓 → `consistent=false`。
- caps 驱动：ashare mock caps.has_liquidation_feed=False → 爆仓流信号自动跳过，无异常。
- 杠杆锁定（CT-EG-6）：mock 交易所返回杠杆=3 → 断言 gateway 拒绝启动；正常路径断言启动时发出 leverage=1 设置调用并校验回读。
