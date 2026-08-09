[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "hashing",

    [ValidateSet("base", "openai")]
    [string]$CurrentContextSource = "base",

    [string]$SourceDir = (Join-Path $HOME "Downloads"),

    [string]$RunDir = "",

    [int]$Repeats = 1,

    [int]$BootstrapSamples = 1000,

    [switch]$SkipAblation
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "real_benchmark_v3"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunDir = Join-Path $PSScriptRoot "runs\real-benchmark-v3-latest"
}

$Builder = Join-Path $PSScriptRoot "build_real_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$GoldMetadata = Join-Path $BenchmarkDir "gold_metadata.json"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$MetricsDir = Join-Path $RunDir "metrics"
$ContextCache = Join-Path $BenchmarkDir ".cache\context_enrichment_cache.json"

Write-Host "[1/3] Building and auditing the 300-query real-document benchmark..."
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
    "--current-context-source", $CurrentContextSource,
    "--context-cache", $ContextCache,
    "--repeats", $Repeats
)
if (-not $SkipAblation) {
    $RunnerArgs += "--include-ablation"
}

Write-Host "[2/3] Running isolated retrieval indexes and metadata variants..."
& $Python @RunnerArgs
if ($LASTEXITCODE -ne 0) {
    throw "run_abcd_experiment.py failed with exit code $LASTEXITCODE"
}

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
        "v5_context_terms:v6_domain_metadata:v6_minus_v5",
        "v6a_filter_only:v6b_filter_plus_search_text:search_text_minus_filter_only",
        "v6a_filter_only:v6c_filter_plus_embedding_text:embedding_text_minus_filter_only",
        "v6b_filter_plus_search_text:v6c_filter_plus_embedding_text:embedding_text_minus_search_text"
    )
}

Write-Host "[3/3] Scoring slices, fields, multi-hop, null, ACL, latency, and paired deltas..."
& $Python $Scorer `
    --testset $ResolvedTestset `
    --results $Results `
    --output-dir $MetricsDir `
    --comparisons ($Comparisons -join ",") `
    --bootstrap-samples $BootstrapSamples
if ($LASTEXITCODE -ne 0) {
    throw "score_experiment_comparison.py failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Completed. Review:"
Write-Host (Join-Path $MetricsDir "retrieval_metric_summary.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_slice.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_metadata_field.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_scenario.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_by_evidence_fact.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_macro_summary.csv")
Write-Host (Join-Path $MetricsDir "retrieval_metric_comparison.csv")
Write-Host (Join-Path $RunDir "ground_truth_audit.csv")
Write-Host (Join-Path $BenchmarkDir "numeric_fact_integrity_audit.csv")
Write-Host (Join-Path $BenchmarkDir "queries_for_review.csv")
