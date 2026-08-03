param(
    [Parameter(Mandatory = $true)]
    [string[]]$Paths
)

$ErrorActionPreference = 'Stop'
$ForbiddenNames = @('.env', 'secrets.json', 'config.json', 'agent.sqlite3')
$TextExtensions = @('.txt', '.json', '.ini', '.cfg', '.env')
$SecretPatterns = @(
    '(?i)CRM_AGENT_TOKEN\s*=\s*\S+',
    '(?i)"accessToken"\s*:\s*"[^"\r\n]+"',
    '(?i)"refreshToken"\s*:\s*"[^"\r\n]+"'
)

foreach ($InputPath in $Paths) {
    $ResolvedPath = (Resolve-Path -LiteralPath $InputPath).Path
    $Files = Get-ChildItem -LiteralPath $ResolvedPath -File -Recurse
    foreach ($File in $Files) {
        $Name = $File.Name.ToLowerInvariant()
        if ($ForbiddenNames -contains $Name -or $Name -like '*.sqlite3' -or $Name -like '*.db' -or $Name -like '*.log') {
            throw "Release safety check failed: forbidden file $($File.FullName)"
        }
        if ($TextExtensions -contains $File.Extension.ToLowerInvariant()) {
            foreach ($Pattern in $SecretPatterns) {
                if (Select-String -LiteralPath $File.FullName -Pattern $Pattern -Quiet) {
                    throw "Release safety check failed: credential pattern in $($File.FullName)"
                }
            }
        }
    }
}

Write-Host 'Release safety check passed.'
