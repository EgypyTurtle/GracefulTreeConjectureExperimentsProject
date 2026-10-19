[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Server,
    [string]$User = "dell"
)
$ErrorActionPreference = "Stop"
if ($Server -notmatch '^[A-Za-z0-9.-]+$' -or $User -notmatch '^[A-Za-z0-9_-]+$') {
    throw "Unsupported SSH host or user format."
}
$Target = "${User}@${Server}"
$Root = "/home/dell/math-search/Erdos-Gyarfas/erdos-gyarfas-v2"
$Launcher = Join-Path (Split-Path $PSScriptRoot -Parent) "run_cpu0.sh"
Get-Command ssh,scp -ErrorAction Stop | Out-Null
Write-Host "Uploading only the launcher. Engine source, binary and k=14 records are not changed."
& scp $Launcher "${Target}:${Root}/run_cpu0.sh"
if ($LASTEXITCODE -ne 0) { throw "Upload failed." }
$Hash = (Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash.ToLowerInvariant()
& ssh $Target "set -e; cd $Root; printf '%s  %s\n' '$Hash' run_cpu0.sh | sha256sum -c -; bash run_cpu0.sh 15"
if ($LASTEXITCODE -ne 0) { throw "Remote launcher failed; inspect the server before retrying." }
Write-Host "Progress: ssh -t $Target 'tmux attach -t eg-k15-cpu0'"
