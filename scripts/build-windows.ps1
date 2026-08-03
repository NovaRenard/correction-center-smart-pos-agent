param(
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
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

& $Python -m PyInstaller --noconfirm --clean --onedir --name KoshakanSmartPosAgent --paths (Join-Path $ProjectRoot 'src') (Join-Path $ProjectRoot 'src\smart_pos_agent\entrypoint.py')
Write-Host "Build completed: $(Join-Path $ProjectRoot 'dist\KoshakanSmartPosAgent')"
