[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "hashing",

    [string]$SourceDir = (Join-Path $env:USERPROFILE "Downloads"),

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [switch]$ContextualizeCurrent,

    [switch]$SkipAblation,

    [switch]$AllowUnresolvedGroundTruth
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunDir = Join-Path $PSScriptRoot "runs\latest"
}

$Testset = Join-Path $PSScriptRoot "testset.jsonl"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Reporter = Join-Path $PSScriptRoot "build_experiment_report.py"
$Builder = Join-Path $PSScriptRoot "build_testset.py"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$MetricsDir = Join-Path $RunDir "metrics"

Write-Host "[1/4] Rebuilding the frozen 39-query test set..."
& $Python $Builder
if ($LASTEXITCODE -ne 0) { throw "build_testset.py failed with exit code $LASTEXITCODE" }

$RunnerArgs = @(
    $Runner,
    "--source-dir", $SourceDir,
    "--testset", $Testset,
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--repeats", $Repeats
)
if (-not $SkipAblation) {
    $RunnerArgs += "--include-ablation"
}
if ($ContextualizeCurrent) {
    $RunnerArgs += @("--current-context-source", "openai")
}
if ($AllowUnresolvedGroundTruth) {
    $RunnerArgs += "--allow-unresolved-ground-truth"
}

Write-Host "[2/4] Building isolated indexes and running retrieval..."
& $Python @RunnerArgs
if ($LASTEXITCODE -ne 0) { throw "run_abcd_experiment.py failed with exit code $LASTEXITCODE" }

$Comparisons = @(
    "no_metadata:current_metadata:B_minus_A",
    "current_metadata:gold_metadata:D_minus_B",
    "shuffled_metadata:current_metadata:B_minus_C"
)
if (-not $SkipAblation) {
    $Comparisons += @(
        "v0_raw_text:v1_document_identity:v1_minus_v0",
        "v1_document_identity:v2_section_structure:v2_minus_v1",
        "v2_section_structure:v3_block_aware:v3_minus_v2",
        "v3_block_aware:v4_context_summary:v4_minus_v3",
        "v4_context_summary:v5_context_terms:v5_minus_v4",
        "v5_context_terms:v6_domain_metadata:v6_minus_v5"
    )
}

Write-Host "[3/4] Scoring quality, latency, query types, and paired deltas..."
& $Python $Scorer `
    "--testset" $ResolvedTestset `
    "--results" $Results `
    "--output-dir" $MetricsDir `
    "--comparisons" ($Comparisons -join ",")
if ($LASTEXITCODE -ne 0) { throw "score_experiment_comparison.py failed with exit code $LASTEXITCODE" }

Write-Host "[4/4] Building the final verdict report..."
& $Python $Reporter "--run-dir" $RunDir "--metrics-dir" $MetricsDir
if ($LASTEXITCODE -ne 0) { throw "build_experiment_report.py failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Completed. Open:"
Write-Host (Join-Path $RunDir "experiment_report.md")
Write-Host (Join-Path $RunDir "metadata_audit.csv")
Write-Host (Join-Path $RunDir "ground_truth_audit.csv")
