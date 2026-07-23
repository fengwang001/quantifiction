# Quantifiction 统一启动脚本 — Windows (PowerShell 5+/7+)
# 管理三个常驻进程：影子引擎 / Agent认知层 / Web看板
#
# 用法:
#   .\scripts\quant.ps1 start            启动全部（读 .env，默认 REST 轮询）
#   .\scripts\quant.ps1 start -Ws        WS 实时模式（经 Clash/透明代理）
#   .\scripts\quant.ps1 stop             停止全部
#   .\scripts\quant.ps1 restart -Ws      重启（无损，恢复持久化状态）
#   .\scripts\quant.ps1 status           查看各进程状态
#   .\scripts\quant.ps1 logs engine      跟随日志（engine|agent|web）
#   .\scripts\quant.ps1 start engine     只启动某一个
#
# WS 实时模式需透传 TLS 的代理（如 Clash 混合端口）。默认 http://127.0.0.1:7890，
# 用环境变量 QUANT_WS_PROXY 覆盖；服务器直连用 -WsDirect。
[CmdletBinding()]
param(
  [Parameter(Position=0)][string]$Command = "status",
  [Parameter(Position=1)][string]$Target = "",
  [switch]$Ws,
  [switch]$WsDirect
)
$ErrorActionPreference = "Stop"
$Root   = Split-Path -Parent $PSScriptRoot
$PidDir = Join-Path $Root "data\pids"
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $PidDir,$LogDir | Out-Null

# 加载 .env（KEY=VALUE，忽略注释/空行）——使脚本自包含（agent 需 GRSAI/OKX 密钥）
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
      $k,$v = $line.Split("=",2)
      Set-Item -Path "env:$($k.Trim())" -Value $v.Trim()
    }
  }
}

# 探测 Python
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = (Get-Command python).Source }

$Services = @{
  engine = @("-m","quant.research.shadow_engine")
  agent  = @("-m","quant.cognitive.agent_runner")
  web    = @("-m","uvicorn","quant.webui.live_dashboard:app","--host","127.0.0.1","--port","8000","--log-level","warning")
  carry  = @("-m","quant.research.carry_engine")   # 资金费carry(迭代65 pivot：结构性edge)
}
# 每服务的额外环境变量（多标的并行引擎用；迭代47）
$ServiceEnv = @{}

# 多标的：除主 ETH 引擎外，为每个额外标的注册独立引擎（独立持久化/展示文件，同策略并行）
# 数据增速×(1+标的数)，零策略逻辑改动。ETH 用默认文件名保持现有数据不动。
$Instruments = @("BTC-USDT-SWAP","SOL-USDT-SWAP")
foreach ($inst in $Instruments) {
  $sym = ($inst -split "-")[0].ToLower()       # btc / sol
  $svc = "engine-$sym"
  $Services[$svc] = @("-m","quant.research.shadow_engine")
  $ServiceEnv[$svc] = @{
    SHADOW_INST    = $inst
    SHADOW_PERSIST = "data\shadow_persist_$sym.json"
    SHADOW_OUT     = "data\shadow_state_$sym.json"
  }
}
$All = @("engine") + ($Instruments | ForEach-Object { "engine-" + ($_ -split "-")[0].ToLower() }) + @("carry","agent","web")

function Apply-WsEnv([bool]$Direct) {
  $env:OKX_BASE_URL = "https://www.okx.com"
  $env:PYTHONIOENCODING = "utf-8"
  if ($Direct) { $env:OKX_WS_DIRECT = "1"; Write-Host "  [WS] 直连模式 (OKX_WS_DIRECT=1)" }
  else {
    $proxy = if ($env:QUANT_WS_PROXY) { $env:QUANT_WS_PROXY } else { "http://127.0.0.1:7890" }
    $env:HTTP_PROXY = $proxy; $env:HTTPS_PROXY = $proxy; $env:WS_PROXY = $proxy
    Write-Host "  [WS] 经代理 $proxy"
  }
}

function Get-Pid([string]$Name) {
  $pf = Join-Path $PidDir "$Name.pid"
  if (-not (Test-Path $pf)) { return $null }
  $procId = Get-Content $pf
  if (Get-Process -Id $procId -ErrorAction SilentlyContinue) { return $procId } else { return $null }
}

function Start-One([string]$Name) {
  if (-not $Services.ContainsKey($Name)) { Write-Host "未知服务: $Name"; return }
  if (Get-Pid $Name) { Write-Host "  $Name 已在运行 (pid $(Get-Pid $Name))"; return }
  $env:PYTHONIOENCODING = "utf-8"
  # 应用该服务的专属环境变量（多标的引擎），记录原值以便复原
  $saved = @{}
  if ($ServiceEnv.ContainsKey($Name)) {
    foreach ($k in $ServiceEnv[$Name].Keys) {
      $saved[$k] = [Environment]::GetEnvironmentVariable($k)
      Set-Item -Path "env:$k" -Value $ServiceEnv[$Name][$k]
    }
  }
  $p = Start-Process -FilePath $Py -ArgumentList $Services[$Name] -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $LogDir "$Name.log") `
        -RedirectStandardError  (Join-Path $LogDir "$Name.err") `
        -PassThru -WindowStyle Hidden
  $p.Id | Out-File -Encoding ascii (Join-Path $PidDir "$Name.pid")
  # 复原环境，避免污染后续服务
  foreach ($k in $saved.Keys) {
    if ($null -eq $saved[$k]) { Remove-Item "env:$k" -ErrorAction SilentlyContinue }
    else { Set-Item -Path "env:$k" -Value $saved[$k] }
  }
  Start-Sleep -Seconds 1
  if (Get-Pid $Name) { Write-Host "  $Name 启动 ✓ (pid $($p.Id))" } else { Write-Host "  $Name 启动失败，看 $LogDir\$Name.err" }
}

function Stop-One([string]$Name) {
  $procId = Get-Pid $Name
  if ($procId) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue; Write-Host "  $Name 已停" }
  else { Write-Host "  $Name 未运行" }
  Remove-Item (Join-Path $PidDir "$Name.pid") -ErrorAction SilentlyContinue
}

function Show-Status {
  "{0,-8} {1,-10} {2}" -f "服务","状态","PID"
  foreach ($s in $All) {
    $procId = Get-Pid $s
    if ($procId) { "{0,-8} {1,-10} {2}" -f $s,"运行中",$procId } else { "{0,-8} {1,-10} {2}" -f $s,"停止","-" }
  }
  Write-Host "看板: http://127.0.0.1:8000"
}

$Targets = if ($Target -and $All -contains $Target) { @($Target) } else { $All }
$useWs = $Ws -or $WsDirect

switch ($Command) {
  "start" {
    if ($useWs) { Write-Host "行情: WS 实时模式"; Apply-WsEnv($WsDirect) } else { Write-Host "行情: REST 轮询（默认，读 .env）" }
    $Targets | ForEach-Object { Start-One $_ }
  }
  "stop"  { $Targets | ForEach-Object { Stop-One $_ } }
  "restart" {
    $Targets | ForEach-Object { Stop-One $_ }; Start-Sleep -Seconds 1
    if ($useWs) { Apply-WsEnv($WsDirect) }
    $Targets | ForEach-Object { Start-One $_ }
  }
  "status" { Show-Status }
  "logs" {
    $t = if ($Target) { $Target } else { "engine" }
    $lf = Join-Path $LogDir "$t.log"
    if (Test-Path $lf) { Get-Content $lf -Wait -Tail 20 } else { Write-Host "无日志: $t（engine|agent|web）" }
  }
  default { Write-Host "用法: quant.ps1 {start|stop|restart|status|logs} [-Ws|-WsDirect] [engine|agent|web]" }
}
