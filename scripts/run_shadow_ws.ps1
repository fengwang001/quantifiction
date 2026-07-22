# 影子引擎 · WS 实时模式（经 Clash 混合端口透传 TLS）
# Clash for Windows 混合端口 7890 支持 CONNECT 透明隧道，可打通 wss://ws.okx.com:8443。
# 旧 HTTP 代理(42.192)不透传 TLS，故只能 REST；换 Clash 后 WS 毫秒级实时。
$env:OKX_BASE_URL = "https://www.okx.com"      # 真实域名（经 Clash 可达；.cab 是无代理时的备用）
$env:HTTP_PROXY   = "http://127.0.0.1:7890"    # Clash：REST 冷启动/回退走此隧道
$env:HTTPS_PROXY  = "http://127.0.0.1:7890"
$env:WS_PROXY     = "http://127.0.0.1:7890"    # 设置即启用 WSPoller（毫秒级实时订单簿+逐笔）
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot\..
& .venv\Scripts\python.exe -m quant.research.shadow_engine
