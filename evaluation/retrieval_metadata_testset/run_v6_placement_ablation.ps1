[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "hashing",

    [ValidateSet("base", "openai")]
    [string]$CurrentContextSource = "base",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$SourceDir = (Join-Path $HOME "Downloads"),

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "real_benchmark_v3"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunName = "real-benchmark-v3-v6-placement-{0}" -f $EmbeddingProvider
    $RunDir = Join-Path $PSScriptRoot (Join-Path "runs" $RunName)
}

$Builder = Join-Path $PSScriptRoot "build_real_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$GoldMetadata = Join-Path $BenchmarkDir "gold_metadata.json"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$AllMetricsDir = Join-Path $RunDir "metrics_all_queries"
$FilterMetricsDir = Join-Path $RunDir "metrics_filter_capable"
$EmbeddingCache = Join-Path $BenchmarkDir ".cache\embedding_cache.json"
$ContextCache = Join-Path $BenchmarkDir ".cache\context_enrichment_cache.json"

$Modes = @(
    "v6a_filter_only",
    "v6b_filter_plus_search_text",
    "v6c_filter_plus_embedding_text"
)
$Comparisons = @(
    "v6a_filter_only:v6b_filter_plus_search_text:search_text_minus_filter_only",
    "v6a_filter_only:v6c_filter_plus_embedding_text:embedding_text_minus_filter_only",
    "v6b_filter_plus_search_text:v6c_filter_plus_embedding_text:embedding_text_minus_search_text"
)

Write-Host "[1/4] Verifying the frozen real-document benchmark..."
& $Python $Builder --source-dir $SourceDir --output-dir $BenchmarkDir
if ($LASTEXITCODE -ne 0) {
    throw "build_real_metadata_benchmark.py failed with exit code $LASTEXITCODE"
}

$RunnerArgs = @(
    $Runner,
    "--source-dir", $SourceDir,
    "--testset", $Testset,
    "--gold-metadata", $GoldMetadata,
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--current-context-source", $CurrentContextSource,
    "--context-cache", $ContextCache,
    "--modes", ($Modes -join ","),
    "--ablation-source", "gold",
    "--repeats", $Repeats
)

Write-Host "[2/4] Running v6 metadata-placement variants..."
& $Python @RunnerArgs
if ($LASTEXITCODE -ne 0) {
    throw "run_abcd_experiment.py failed with exit code $LASTEXITCODE"
}

$CommonScoreArgs = @(
    $Scorer,
    "--testset", $ResolvedTestset,
    "--results", $Results,
    "--comparisons", ($Comparisons -join ","),
    "--bootstrap-samples", $BootstrapSamples
)

Write-Host "[3/4] Scoring all 300 queries for regression visibility..."
& $Python @CommonScoreArgs --output-dir $AllMetricsDir --query-subset all
if ($LASTEXITCODE -ne 0) {
    throw "All-query scoring failed with exit code $LASTEXITCODE"
}

Write-Host "[4/4] Scoring only structured-filter-capable queries..."
& $Python @CommonScoreArgs --output-dir $FilterMetricsDir --query-subset filter_capable
if ($LASTEXITCODE -ne 0) {
    throw "Filter-capable scoring failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Completed v6 placement ablation. Review:"
Write-Host (Join-Path $FilterMetricsDir "evaluation_scope.json")
Write-Host (Join-Path $FilterMetricsDir "retrieval_metric_summary.csv")
Write-Host (Join-Path $FilterMetricsDir "retrieval_metric_comparison.csv")
Write-Host (Join-Path $FilterMetricsDir "retrieval_metric_by_slice.csv")
Write-Host (Join-Path $RunDir "metadata_audit.csv")
Write-Host (Join-Path $RunDir "run_manifest.json")
