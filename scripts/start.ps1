<#
 Start the platform (Windows PowerShell 5.1+ / PowerShell 7).   .\scripts\start.ps1 [-NoChain] [-Port 8000]
 Runs the local Hardhat chain (auto-deploys the audit contract) and the API serving the built UI on ONE port.
 Press Ctrl+C to stop; the blockchain process is stopped automatically.
#>
param([switch]$NoChain, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$OnWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or ($IsWindows -eq $true)
$Py = if ($OnWindows) { Join-Path $Root "backend/.venv/Scripts/python.exe" } else { Join-Path $Root "backend/.venv/bin/python" }
if (-not (Test-Path $Py)) { throw "Run .\scripts\setup.ps1 first." }
if (-not (Test-Path "frontend/dist/index.html")) { Push-Location frontend; try { npm run build | Out-Null } finally { Pop-Location } }
New-Item -ItemType Directory -Force data/logs | Out-Null
$chainProc = $null
function Rpc($method, $params) {
  $body = @{ jsonrpc = "2.0"; method = $method; params = $params; id = 1 } | ConvertTo-Json -Compress
  Invoke-RestMethod -Uri http://127.0.0.1:8545 -Method Post -Body $body -ContentType "application/json" -TimeoutSec 3
}
try {
  if (-not $NoChain) {
    Write-Host "Starting local blockchain (Hardhat)..." -ForegroundColor Cyan
    $log = Join-Path $Root "data/logs/hardhat.log"
    if ($OnWindows) {
      $chainProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "cd /d `"$Root\blockchain`" && npx hardhat node > `"$log`" 2>&1" -WindowStyle Minimized -PassThru
    } else {
      $chainProc = Start-Process -FilePath "bash" -ArgumentList "-c", "`"cd '$Root/blockchain' && exec npx hardhat node > '$log' 2>&1`"" -PassThru
    }
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $up; $i++) { try { Rpc "eth_chainId" @() | Out-Null; $up = $true } catch { Start-Sleep 1 } }
    if (-not $up) { throw "The local blockchain did not start. See data/logs/hardhat.log" }
    $addr = (& $Py scripts/envset.py get CONTRACT_ADDRESS | Out-String).Trim()
    $hasCode = $false
    if ($addr) { try { $hasCode = (Rpc "eth_getCode" @($addr, "latest")).result -ne "0x" } catch { $hasCode = $false } }
    if (-not $hasCode) {
      Push-Location backend
      try { $line = & $Py -m app.cli deploy-contract | Where-Object { $_ -like "CONTRACT_ADDRESS=*" } } finally { Pop-Location }
      if ($line) { $new = ($line | Select-Object -First 1).Substring("CONTRACT_ADDRESS=".Length); & $Py scripts/envset.py set CONTRACT_ADDRESS $new; Write-Host "Audit contract deployed at $new" -ForegroundColor Green }
      else { Write-Warning "Contract deployment failed; records will stay pending (see data/logs/hardhat.log)." }
    }
  } else { $env:BLOCKCHAIN_ENABLED = "false" }   # this run only; .env is untouched
  Write-Host "Starting the platform on http://localhost:$Port  (Ctrl+C to stop)" -ForegroundColor Green
  if ($OnWindows) { Start-Job { param($p) Start-Sleep 4; Start-Process "http://localhost:$p" } -ArgumentList $Port | Out-Null }
  Push-Location backend
  try { & $Py -m uvicorn app.main:app --host 127.0.0.1 --port $Port } finally { Pop-Location }
} finally {
  if ($chainProc) {
    Write-Host "Stopping blockchain..."
    if ($OnWindows) { taskkill /PID $chainProc.Id /T /F 2>$null | Out-Null }
    else { & pkill -P $chainProc.Id 2>$null; Stop-Process -Id $chainProc.Id -Force -ErrorAction SilentlyContinue }
  }
}
