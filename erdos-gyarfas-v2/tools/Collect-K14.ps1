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
$ProjectRoot = "/home/dell/math-search/Erdos-Gyarfas/erdos-gyarfas-v2"
$RemoteTools = "/home/dell/math-search/eg-k14-audit-tools"
$RemoteOutput = "/home/dell/math-search/eg-k14-artifacts"
$AuditScript = Join-Path $PSScriptRoot "audit_checkpoint.py"
$CollectorScript = Join-Path $PSScriptRoot "collect_artifact.py"
$LocalOutput = Join-Path (Split-Path $PSScriptRoot -Parent) "artifacts\server-k14"

Get-Command ssh,scp -ErrorAction Stop | Out-Null
foreach ($Path in @($AuditScript, $CollectorScript)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing tool: $Path" }
}

Write-Host "Preparing a separate audit-tool directory; search sources and checkpoints are not overwritten."
& ssh $Target "mkdir -p $RemoteTools"
if ($LASTEXITCODE -ne 0) { throw "Could not prepare remote audit directory." }
& scp $AuditScript $CollectorScript "${Target}:${RemoteTools}/"
if ($LASTEXITCODE -ne 0) { throw "Audit-tool upload failed." }

Write-Host "Auditing and collecting the completed k=14 run. SSH may ask for your password again."
$Response = @(& ssh $Target "python3 $RemoteTools/collect_artifact.py --project-root $ProjectRoot --checkpoint checkpoints/k14-d5-refined --output-dir $RemoteOutput --expect-k 14 --expect-states 1435716298 2>&1")
if ($LASTEXITCODE -ne 0) {
    $Response | ForEach-Object { Write-Host $_ }
    throw "Server audit/collection failed. No result is certified by this script."
}
$Response | Select-Object -SkipLast 1 | ForEach-Object { Write-Host $_ }
$Record = ($Response | Select-Object -Last 1) | ConvertFrom-Json
$ExpectedPrefix = [regex]::Escape($RemoteOutput)
if ($Record.archive -notmatch "^$ExpectedPrefix/eg_k14_[A-Za-z0-9_]+[.]tar[.]gz$" -or
    $Record.sha256_file -ne ($Record.archive + ".sha256") -or
    $Record.sha256 -notmatch '^[0-9a-f]{64}$') {
    throw "Unexpected artifact path/checksum in server response."
}
New-Item -ItemType Directory -Force -Path $LocalOutput | Out-Null
$ArchiveName = [System.IO.Path]::GetFileName([string]$Record.archive)
$LocalArchive = Join-Path $LocalOutput $ArchiveName
if (Test-Path -LiteralPath $LocalArchive) { throw "Local artifact already exists: $LocalArchive" }
& scp "${Target}:$($Record.archive)" "${Target}:$($Record.sha256_file)" $LocalOutput
if ($LASTEXITCODE -ne 0) { throw "Artifact download failed." }
$Actual = (Get-FileHash -LiteralPath $LocalArchive -Algorithm SHA256).Hash.ToLowerInvariant()
$Sidecar = ((Get-Content -LiteralPath ($LocalArchive + ".sha256") -TotalCount 1) -split '\s+', 2)[0]
if ($Actual -ne $Record.sha256 -or $Actual -ne $Sidecar) { throw "Downloaded artifact checksum mismatch." }
$Record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath ($LocalArchive + ".collection.json") -Encoding UTF8
Write-Host "PASS: checkpoint integrity and downloaded SHA-256."
Write-Host "Artifact: $LocalArchive"
Write-Host "This is an integrity check; the full DFS search has not been independently replayed."
