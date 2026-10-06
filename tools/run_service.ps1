<#
  Запуск сервиса сбора разметки на Windows (PowerShell 5.1 и PowerShell 7+).

  Использование:
    powershell -ExecutionPolicy Bypass -File tools\run_service.ps1
    powershell -ExecutionPolicy Bypass -File tools\run_service.ps1 -Port 9000 -LocalOnly
    powershell -ExecutionPolicy Bypass -File tools\run_service.ps1 -AdminToken "мой-admin-токен" `
        -Experts "gidr01:Иван Петров:lead,gidr02:Мария Сидорова:expert"

  Скрипт сам:
    • создаёт токены, если вы их не задали;
    • ставит переменные окружения (в PowerShell это $env:ИМЯ = "значение", а не export);
    • печатает адреса и персональные ссылки для гидравликов;
    • запускает сервис. Остановка — Ctrl+C.

  Проверить в другом окне PowerShell:
    python tools\check_service.py
#>
[CmdletBinding()]
param(
  [int]$Port = 8080,
  [string]$AdminToken = "",
  [string]$Experts = "",
  [string]$DataDir = "service_data",
  [double]$AutoExportHours = 6,
  [switch]$LocalOnly,
  [switch]$SkipDependencyCheck
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # корень проекта = tools\..
Set-Location $root
$OutEnc = [Console]::OutputEncoding
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function New-RandomToken([string]$Prefix) {
  $bytes = New-Object 'byte[]' 8
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return $Prefix + (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Write-Section([string]$Text) { Write-Host $Text -ForegroundColor Cyan }

# ── токены: если не заданы — генерируем
if (-not $AdminToken) { $AdminToken = New-RandomToken "admin-" }
if (-not $Experts) { $Experts = (New-RandomToken "gidr01-") + ":Иван Петров:lead" }
if (-not $Experts.Contains(":")) { throw "Experts задаётся как токен:Имя:роль (через запятую)" }

# ── python
$python = $null
foreach ($cand in @("python", "py", "python3")) {
  if (Get-Command $cand -ErrorAction SilentlyContinue) { $python = $cand; break }
}
if (-not $python) {
  Write-Host "Python не найден в PATH. Установите Python 3.11+ с python.org (галочка 'Add to PATH')." -ForegroundColor Red
  exit 1
}

if (-not $SkipDependencyCheck) {
  & $python -c "import fastapi, uvicorn, wntr" 2>$null
  if ($LASTEXITCODE -ne 0) {
    if ($LASTEXITCODE -eq 9009 -or $LASTEXITCODE -gt 100) {
      Write-Host "Команда python не запускается. Если открылся Microsoft Store — это заглушка Windows:" -ForegroundColor Yellow
      Write-Host "  установите Python 3.11+ с https://www.python.org/downloads/ (галочка 'Add python.exe to PATH')"
      Write-Host "  или используйте 'py' вместо 'python'."
    }
    Write-Host "Не хватает зависимостей. Выполните один раз:" -ForegroundColor Yellow
    Write-Host "  $python -m pip install -r requirements.txt"
    exit 1
  }
}

# ── переменные окружения (аналог export в bash)
if ([System.IO.Path]::IsPathRooted($DataDir)) { $dataPath = $DataDir }
else { $dataPath = (Resolve-Path -LiteralPath $root).Path + "\" + $DataDir }
$env:SERVICE_DATA        = $dataPath
$env:ADMIN_TOKEN         = $AdminToken
$env:EXPERT_TOKENS       = $Experts
$env:AUTO_EXPORT_HOURS   = "$AutoExportHours"
$env:SERVICE_PUBLIC_URL  = ""                      # локально ссылки относительные
$host_ = if ($LocalOnly) { "127.0.0.1" } else { "0.0.0.0" }

New-Item -ItemType Directory -Force -Path $env:SERVICE_DATA | Out-Null

Write-Section "Сервис запускается (Windows / PowerShell)"
Write-Host "  интерфейс:      http://localhost:$Port/"
Write-Host "  админка:        http://localhost:$Port/admin?token=$AdminToken"
Write-Host "  проверка:       http://localhost:$Port/health"
Write-Host ""
Write-Host "Токен администратора (только для вас, никому не передавайте):" -ForegroundColor Yellow
Write-Host "  $AdminToken"
Write-Host ""
foreach ($chunk in ($Experts -split ",")) {
  $parts = $chunk.Trim() -split ":"
  if ($parts.Count -lt 2) { continue }
  $token = $parts[0].Trim()
  $name  = $parts[1].Trim()
  $role  = if ($parts.Count -gt 2) { $parts[2].Trim() } else { "expert" }
  Write-Host "Гидравлик: $name ($role)" -ForegroundColor Green
  Write-Host "  персональная ссылка: http://localhost:$Port/?token=$token"
}
Write-Host ""
Write-Host "Проверка в другом окне:  $python (Join-Path 'tools' 'check_service.py') --token <токен гидравлика> --admin $AdminToken"
Write-Host "Остановить сервис: Ctrl+C"
Write-Host ""

& $python -m uvicorn service.app:app --host $host_ --port $Port
try { [Console]::OutputEncoding = $OutEnc } catch { }
