$ErrorActionPreference = 'Stop'
$TaskName = 'Koshakan Smart POS Agent'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Autostart task removed: $TaskName"
} else {
    Write-Host "Autostart task does not exist."
}
