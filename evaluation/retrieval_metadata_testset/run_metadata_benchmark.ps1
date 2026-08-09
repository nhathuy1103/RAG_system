[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "hashing",

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 1000,

    [switch]$SkipAblation
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "benchmark_v2"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunDir = Join-Path $PSScriptRoot "runs\benchmark-v2-latest"
}

$Builder = Join-Path $PSScriptRoot "build_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Corpus = Join-Path $BenchmarkDir "corpus.jsonl"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$MetricsDir = Join-Path $RunDir "metrics"

Write-Host "[1/3] Building the frozen 300-query controlled benchmark..."
& $Python $Builder
if ($LASTEXITCODE -ne 0) { throw "build_metadata_benchmark.py failed with exit code $LASTEXITCODE" }

$RunnerArgs = @(
    $Runner,
    "--corpus-fixture", $Corpus,
    "--testset", $Testset,
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--repeats", $Repeats
)
if (-not $SkipAblation) {
    $RunnerArgs += "--include-ablation"
}

Write-Host "[2/3] Running isolated indexes and retrieval modes..."
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

Write-Host "[3/3] Scoring recall, slices, multi-hop, null, ACL, latency, and paired deltas..."
& $Python $Scorer `
    "--testset" $ResolvedTestset `
    "--results" $Results `
    "--output-dir" $MetricsDir `
    "--comparisons" ($Comparisons -join ",") `
    "--bootstrap-samples" $BootstrapSamples
if ($LASTEXITCODE -ne 0) { throw "score_experiment_comparison.py failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Completed. Review:"
Write-Host (Join-Path $MetricsDir "retrieval_metric_summary.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_slice.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_metadata_field.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_comparison.csv")
Write-Host (Join-Path $RunDir "metadata_audit.csv")
