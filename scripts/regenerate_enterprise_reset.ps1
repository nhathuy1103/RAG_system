$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$migrationDirectory = Join-Path $workspaceRoot "supabase\migrations"
$resetPath = Join-Path $migrationDirectory "RESET_AND_REBUILD.sql"
$marker = "-- Extensions required by the schema."

$reset = [System.IO.File]::ReadAllText($resetPath)
$markerIndex = $reset.IndexOf($marker, [System.StringComparison]::Ordinal)
if ($markerIndex -lt 0) {
    throw "Canonical migration marker was not found in RESET_AND_REBUILD.sql"
}

$prefix = $reset.Substring(0, $markerIndex)
$migrationPaths = Get-ChildItem -LiteralPath $migrationDirectory -File |
    Where-Object { $_.Name -match '^[0-9]{2}_.+\.sql$' } |
    Sort-Object Name
if ($migrationPaths.Count -eq 0) {
    throw "No canonical migrations were found"
}

$latestNumber = [int]$migrationPaths[-1].Name.Substring(0, 2)
$prefix = [regex]::Replace(
    $prefix,
    'Canonical migrations 01 through [0-9]{2}',
    "Canonical migrations 01 through $($latestNumber.ToString('00'))"
)
$canonical = ($migrationPaths | ForEach-Object {
    [System.IO.File]::ReadAllText($_.FullName).TrimEnd("`r", "`n")
}) -join "`r`n`r`n"

$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $resetPath,
    $prefix + $canonical + "`r`n",
    $utf8WithoutBom
)

Write-Output "Regenerated RESET_AND_REBUILD.sql from migrations 01-$($latestNumber.ToString('00'))."
