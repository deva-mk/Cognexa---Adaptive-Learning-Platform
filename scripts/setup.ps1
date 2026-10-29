<#
 One-time setup (Windows PowerShell 5.1+ or PowerShell 7 on Windows/macOS/Linux).
   .\scripts\setup.ps1 [-Demo] [-AI]
     -Demo  also create sample accounts (DEVELOPMENT ONLY); one-time passwords are saved to data/demo-accounts.txt
     -AI    also install the optional neural-embedding + Whisper packages (large downloads)
 If scripts are blocked:  Set-ExecutionPolicy -Scope Process Bypass
#>
param([switch]$Demo, [switch]$AI)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$OnWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or ($IsWindows -eq $true)
function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" } }
function Run($exe, [string[]]$a) { & $exe @a; if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $exe $($a -join ' ')" } }
$SysPy = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
Need $SysPy "Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add to PATH')."
Need node   "Install Node.js 20+ from https://nodejs.org/"
Need npm    "Install Node.js 20+ from https://nodejs.org/"

Write-Host "== Backend" -ForegroundColor Cyan
if (-not (Test-Path "backend/.venv")) { Run $SysPy @("-m", "venv", "backend/.venv") }
$Py = if ($OnWindows) { Join-Path $Root "backend/.venv/Scripts/python.exe" } else { Join-Path $Root "backend/.venv/bin/python" }
Run $Py @("-m", "pip", "install", "-q", "--upgrade", "pip")
Run $Py @("-m", "pip", "install", "-q", "-r", "backend/requirements-dev.txt")
if ($AI) { Run $Py @("-m", "pip", "install", "-q", "-r", "backend/requirements-optional.txt") }
Run $Py @("scripts/envset.py", "init")
Push-Location backend; try { Run $Py @("-m", "app.cli", "init-db") } finally { Pop-Location }

Write-Host "== Front-end" -ForegroundColor Cyan
Push-Location frontend
try { Run npm @("install", "--no-audit", "--no-fund", "--loglevel=error"); Run npm @("run", "build"); Write-Host "built frontend/dist" } finally { Pop-Location }
Write-Host "== Blockchain tooling" -ForegroundColor Cyan
Push-Location blockchain; try { Run npm @("install", "--no-audit", "--no-fund", "--loglevel=error") } finally { Pop-Location }

if ($Demo) {
  New-Item -ItemType Directory -Force data | Out-Null
  Push-Location backend
  try { & $Py -m app.cli demo-data | Tee-Object -FilePath "../data/demo-accounts.txt" } finally { Pop-Location }
  Write-Host "Sample accounts saved to data/demo-accounts.txt (git-ignored)." -ForegroundColor Green
} else {
  Write-Host "`nCreate your administrator:`n  cd backend; $Py -m app.cli create-admin --email you@example.edu --name `"Your Name`"" -ForegroundColor Yellow
}
Write-Host "`nSetup complete. Start everything with:  .\scripts\start.ps1" -ForegroundColor Green
