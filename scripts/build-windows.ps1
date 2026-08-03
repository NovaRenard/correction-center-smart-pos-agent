param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$env:QT_QPA_PLATFORM = 'offscreen'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot '.venv'
$Python = Join-Path $VenvPath 'Scripts\python.exe'

if (-not (Test-Path $Python)) {
    python -m venv $VenvPath
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e "$ProjectRoot[dev]"

if (-not $SkipTests) {
    & $Python -m ruff check src tests
    & $Python -m ruff format --check src tests
    & $Python -m mypy src
    & $Python -m pytest
}

$BuildRoot = Join-Path $ProjectRoot 'build'
$DistRoot = Join-Path $ProjectRoot 'dist'
foreach ($Directory in @($BuildRoot, $DistRoot)) {
    if (Test-Path -LiteralPath $Directory) {
        Remove-Item -LiteralPath $Directory -Recurse -Force
    }
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot 'packaging\KoshakanSmartPosAgent.spec')
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot 'packaging\KoshakanSmartPosAgentCli.spec')
} finally {
    Pop-Location
}

$GuiExe = Join-Path $DistRoot 'KoshakanSmartPosAgent\KoshakanSmartPosAgent.exe'
$CliExe = Join-Path $DistRoot 'KoshakanSmartPosAgentCli\KoshakanSmartPosAgentCli.exe'
& $GuiExe --smoke-test
& $CliExe --help
& $CliExe --version
Write-Host "GUI build: $(Split-Path -Parent $GuiExe)"
Write-Host "CLI build: $(Split-Path -Parent $CliExe)"
