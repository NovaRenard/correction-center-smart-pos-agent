param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$')]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $ProjectRoot 'dist'
$ReleaseRoot = Join-Path $ProjectRoot 'release'
$GuiName = 'KoshakanSmartPosAgent'
$CliName = 'KoshakanSmartPosAgentCli'
$GuiDirectory = Join-Path $DistRoot $GuiName
$CliDirectory = Join-Path $DistRoot $CliName

foreach ($Directory in @($GuiDirectory, $CliDirectory)) {
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        throw "Build directory not found: $Directory"
    }
}

& (Join-Path $PSScriptRoot 'test-release-safety.ps1') -Paths @($GuiDirectory, $CliDirectory)

if (Test-Path -LiteralPath $ReleaseRoot) {
    Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
$StageRoot = Join-Path $ReleaseRoot 'stage'
New-Item -ItemType Directory -Path $StageRoot | Out-Null

function New-PortableZip([string]$Name, [string]$ReadmeName) {
    $Source = Join-Path $DistRoot $Name
    $StageDirectory = Join-Path $StageRoot $Name
    Copy-Item -LiteralPath $Source -Destination $StageDirectory -Recurse
    Copy-Item -LiteralPath (Join-Path $ProjectRoot (Join-Path 'packaging' $ReadmeName)) -Destination (Join-Path $StageDirectory 'README.txt')
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'LICENSE') -Destination (Join-Path $StageDirectory 'LICENSE.txt')
    & (Join-Path $PSScriptRoot 'test-release-safety.ps1') -Paths @($StageDirectory)
    $Archive = Join-Path $ReleaseRoot "$Name-$Version-win64.zip"
    Compress-Archive -LiteralPath $StageDirectory -DestinationPath $Archive -CompressionLevel Optimal
    return $Archive
}

$GuiZip = New-PortableZip $GuiName 'README-gui.txt'
$CliZip = New-PortableZip $CliName 'README-cli.txt'
$Checksums = @($GuiZip, $CliZip) | ForEach-Object {
    $Hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
    "$($Hash.Hash.ToLowerInvariant()) *$([System.IO.Path]::GetFileName($_))"
}
$Checksums | Set-Content -LiteralPath (Join-Path $ReleaseRoot 'SHA256SUMS.txt') -Encoding utf8NoBOM
Remove-Item -LiteralPath $StageRoot -Recurse -Force
Write-Host "Release files: $ReleaseRoot"
