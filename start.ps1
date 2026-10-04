
# ClippyRipoff - Local Development Launcher
# Run from the project root with: .\start.ps1

$ErrorActionPreference = 'Stop'

$ProjectRoot = $PSScriptRoot
$BackendRoot = $ProjectRoot
$FrontendPath = Join-Path $ProjectRoot 'frontend'
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$BackendUrl = 'http://127.0.0.1:8000'
$FrontendUrl = 'http://127.0.0.1:5173'
$BackendHealthUrl = "$BackendUrl/api/health"
$FrontendProbeUrl = $FrontendUrl
$BackendPort = 8000
$FrontendPort = 5173
$StartupTimeoutSeconds = 60

function Write-Banner {
    param([string]$Title)

    Write-Host ''
    Write-Host '======================================' -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host '======================================' -ForegroundColor Cyan
    Write-Host ''
}

function Test-HttpEndpoint {
    param(
        [string]$Url,
        [string]$ExpectedBodySubstring = ''
    )

    try {
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) {
            return $false
        }
        if ($ExpectedBodySubstring -and ($Response.Content -notlike "*$ExpectedBodySubstring*")) {
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

function Wait-ForHttp {
    param(
        [string]$Name,
        [string]$Url,
        [string]$ExpectedBodySubstring = '',
        [int]$TimeoutSeconds = 60
    )

    for ($Second = 0; $Second -lt $TimeoutSeconds; $Second++) {
        if (Test-HttpEndpoint -Url $Url -ExpectedBodySubstring $ExpectedBodySubstring) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    Write-Host "[!] $Name did not become ready within $TimeoutSeconds seconds: $Url" -ForegroundColor Red
    return $false
}

function ConvertTo-EncodedCommand {
    param([string]$Command)

    $Bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
    return [Convert]::ToBase64String($Bytes)
}

function Start-VisiblePowerShellWindow {
    param(
        [string]$WorkingDirectory,
        [string]$Command,
        [string]$WindowTitle
    )

    $EncodedCommand = ConvertTo-EncodedCommand -Command $Command
    Start-Process powershell.exe -WorkingDirectory $WorkingDirectory -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy', 'Bypass',
        '-EncodedCommand', $EncodedCommand
    ) | Out-Null
}

if (!(Test-Path $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}

if (!(Test-Path $VenvPython)) {
    throw "Virtual environment not found at .venv. Create it first, then run: python -m pip install -r requirements.txt"
}

if (!(Test-Path (Join-Path $FrontendPath 'package.json'))) {
    throw "Frontend package.json not found at: $FrontendPath"
}

if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js was not found. Install Node.js and restart PowerShell.'
}

if (!(Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm was not found. Check your Node.js installation and PATH.'
}

Write-Banner 'CLIPPYRIPPOFF LAUNCHER'
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray
Write-Host "Backend:      $BackendUrl" -ForegroundColor Gray
Write-Host "Frontend:     $FrontendUrl" -ForegroundColor Gray
Write-Host ''
Write-Host "Checking backend virtual environment..." -ForegroundColor Yellow

& $VenvPython -c "import fastapi, uvicorn, argon2; print('FastAPI', fastapi.__version__); print('Uvicorn', uvicorn.__version__); print('Argon2 available')"
if ($LASTEXITCODE -ne 0) {
    throw 'The project virtual environment is missing a backend dependency. Run .\.venv\Scripts\python.exe -m pip install -r requirements.txt in the repo root.'
}

Write-Host "Backend dependencies are available." -ForegroundColor Green
Write-Host "Checking frontend dependencies..." -ForegroundColor Yellow

if (!(Test-Path (Join-Path $FrontendPath 'node_modules'))) {
    Write-Host 'Frontend node_modules is missing.' -ForegroundColor Red
    throw "Run 'cd frontend; npm install' once, then start the app again."
}

Write-Host 'Frontend dependencies are available.' -ForegroundColor Green

$BackendAlreadyReady = Test-HttpEndpoint -Url $BackendHealthUrl -ExpectedBodySubstring 'ok'
$FrontendAlreadyReady = Test-HttpEndpoint -Url $FrontendProbeUrl

if ($BackendAlreadyReady -and $FrontendAlreadyReady) {
    Write-Host ''
    Write-Host 'Backend and frontend are already running.' -ForegroundColor Green
    Write-Host "Opening $FrontendUrl in Firefox..." -ForegroundColor Cyan
    $Firefox = Get-Command firefox.exe -ErrorAction SilentlyContinue
    if ($Firefox) {
        Start-Process -FilePath $Firefox.Source -ArgumentList $FrontendUrl | Out-Null
    } else {
        Start-Process $FrontendUrl | Out-Null
    }
    return
}

if (!(Test-HttpEndpoint -Url $BackendHealthUrl -ExpectedBodySubstring 'ok')) {
    Write-Host ''
    Write-Host '[1/4] Starting FastAPI backend...' -ForegroundColor Yellow
    $BackendCommand = @"
Set-Location -LiteralPath '$BackendRoot'
Write-Host ''
Write-Host '======================================' -ForegroundColor Cyan
Write-Host '       CLIPPYRIPPOFF BACKEND' -ForegroundColor Cyan
Write-Host '======================================' -ForegroundColor Cyan
Write-Host ''
& '$VenvPython' -m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort --reload
Write-Host ''
Write-Host 'Backend stopped. Press Enter to close this window.'
Read-Host
"@
    Start-VisiblePowerShellWindow -WorkingDirectory $BackendRoot -Command $BackendCommand -WindowTitle 'ClippyRipoff Backend'
} else {
    Write-Host 'Backend is already responding on /api/health; skipping duplicate start.' -ForegroundColor Green
}

if (!(Test-HttpEndpoint -Url $FrontendProbeUrl)) {
    Write-Host '[2/4] Starting React frontend...' -ForegroundColor Yellow
    $FrontendCommand = @"
Set-Location -LiteralPath '$FrontendPath'
Write-Host ''
Write-Host '======================================' -ForegroundColor Cyan
Write-Host '       CLIPPYRIPPOFF FRONTEND' -ForegroundColor Cyan
Write-Host '======================================' -ForegroundColor Cyan
Write-Host ''
& npm run dev
Write-Host ''
Write-Host 'Frontend stopped. Press Enter to close this window.'
Read-Host
"@
    Start-VisiblePowerShellWindow -WorkingDirectory $FrontendPath -Command $FrontendCommand -WindowTitle 'ClippyRipoff Frontend'
} else {
    Write-Host 'Frontend is already responding on 127.0.0.1:5173; skipping duplicate start.' -ForegroundColor Green
}

Write-Host ''
Write-Host '[3/4] Waiting for backend readiness...' -ForegroundColor Yellow
$BackendReady = Wait-ForHttp -Name 'Backend' -Url $BackendHealthUrl -ExpectedBodySubstring 'ok' -TimeoutSeconds $StartupTimeoutSeconds

Write-Host '[4/4] Waiting for frontend readiness...' -ForegroundColor Yellow
$FrontendReady = Wait-ForHttp -Name 'Frontend' -Url $FrontendProbeUrl -TimeoutSeconds $StartupTimeoutSeconds

Write-Host ''
Write-Host '======================================' -ForegroundColor Cyan
Write-Host '       STARTUP RESULTS' -ForegroundColor Cyan
Write-Host '======================================' -ForegroundColor Cyan

if ($BackendReady) {
    Write-Host "[OK] Backend is ready: $BackendHealthUrl" -ForegroundColor Green
} else {
    Write-Host "[!] Backend is not ready. Check the backend PowerShell window." -ForegroundColor Red
}

if ($FrontendReady) {
    Write-Host "[OK] Frontend is ready: $FrontendUrl" -ForegroundColor Green
} else {
    Write-Host "[!] Frontend is not ready. Check the frontend PowerShell window." -ForegroundColor Red
}

if ($BackendReady -and $FrontendReady) {
    Write-Host ''
    Write-Host "Opening Firefox at $FrontendUrl ..." -ForegroundColor Cyan
    $Firefox = Get-Command firefox.exe -ErrorAction SilentlyContinue
    if ($Firefox) {
        Start-Process -FilePath $Firefox.Source -ArgumentList $FrontendUrl | Out-Null
    } else {
        Start-Process $FrontendUrl | Out-Null
    }
} else {
    Write-Host ''
    Write-Host 'Browser was not opened because one or more services are not ready.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Server logs are visible in their separate PowerShell windows.' -ForegroundColor Gray
Write-Host 'Close those windows or press Ctrl+C in them to stop the servers.' -ForegroundColor Gray
Write-Host ''