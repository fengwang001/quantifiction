#!/usr/bin/env bash
# T068：借用 vendor/freqtrade 下载币安永续历史 K 线（辅助回测数据）。
# 盘口/深度类回测仍须用自录 tick（research R11）；此脚本只补 K 线。
set -euo pipefail

PAIRS="${1:-ETH/USDT:USDT BTC/USDT:USDT}"
TIMEFRAMES="${2:-5m 1h}"
DAYS="${3:-180}"
OUT="${4:-data/klines}"

mkdir -p "$OUT"

# 使用 vendor 内的 freqtrade（不引入为项目依赖，仅作数据工具）
uv run --project vendor/freqtrade freqtrade download-data \
  --exchange binance \
  --trading-mode futures \
  --pairs $PAIRS \
  --timeframes $TIMEFRAMES \
  --days "$DAYS" \
  --datadir "$OUT"

echo "K 线已下载至 $OUT"
