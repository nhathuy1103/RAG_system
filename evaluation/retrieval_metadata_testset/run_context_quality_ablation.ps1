[CmdletBinding()]
param(
    [ValidateSet("openai", "hashing")]
    [string]$EmbeddingProvider = "openai",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$SourceDir = (Join-Path $HOME "Downloads"),

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000,

    [ValidateRange(1, 100)]
    [int]$ContextMaxWords = 45,

    [int]$ContextMaxOutputTokens = 400,

    [switch]$AllowContextFallback
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "real_benchmark_v3"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunName = "real-benchmark-v3-context-quality-v4-{0}" -f $EmbeddingProvider
    $RunDir = Join-Path $PSScriptRoot (Join-Path "runs" $RunName)
}

$Builder = Join-Path $PSScriptRoot "build_real_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Auditor = Join-Path $PSScriptRoot "audit_context_quality.py"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$GoldMetadata = Join-Path $BenchmarkDir "gold_metadata.json"
$EmbeddingCache = Join-Path $BenchmarkDir ".cache\embedding_cache.json"
$ContextCache = Join-Path $BenchmarkDir ".cache\context_enrichment_cache.json"
$Corpus = Join-Path $RunDir "corpus.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$QualityAudit = Join-Path $RunDir "context_quality_audit.csv"
$AllMetricsDir = Join-Path $RunDir "metrics_all_queries"
$FilterMetricsDir = Join-Path $RunDir "metrics_filter_capable"
$Modes = @(
    "ctx_a_chunk_only",
    "ctx_b_deterministic_header",
    "ctx_c_raw_context_dense_only",
    "ctx_c_raw_context_sparse_only",
    "ctx_c_raw_context",
    "ctx_d_effective_context",
    "ctx_e_shuffled_context"
) -join ","
$Comparisons = @(
    "ctx_a_chunk_only:ctx_b_deterministic_header:header_minus_chunk",
    "ctx_b_deterministic_header:ctx_c_raw_context_dense_only:raw_dense_minus_header",
    "ctx_b_deterministic_header:ctx_c_raw_context_sparse_only:raw_sparse_minus_header",
    "ctx_b_deterministic_header:ctx_c_raw_context:raw_context_minus_header",
    "ctx_c_raw_context:ctx_d_effective_context:effective_minus_raw",
    "ctx_e_shuffled_context:ctx_c_raw_context:correct_minus_shuffled"
) -join ","

function Invoke-CheckedPython {
    param([object[]]$Arguments)

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

if ($Repeats -le 0) {
    throw "Repeats must be greater than zero."
}
if ($BootstrapSamples -le 0) {
    throw "BootstrapSamples must be greater than zero."
}
if ($ContextMaxOutputTokens -le 0) {
    throw "ContextMaxOutputTokens must be greater than zero."
}

$env:CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS = [string]$ContextMaxWords
$env:CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS = [string]$ContextMaxOutputTokens

New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

Write-Host "[1/5] Verifying the approved benchmark..."
Invoke-CheckedPython @(
    $Builder,
    "--source-dir", $SourceDir,
    "--output-dir", $BenchmarkDir
)

Write-Host "[2/5] Generating context v4 and running A/B/C/D plus shuffled control..."
Invoke-CheckedPython @(
    $Runner,
    "--source-dir", $SourceDir,
    "--testset", $Testset,
    "--gold-metadata", $GoldMetadata,
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--context-cache", $ContextCache,
    "--current-context-source", "openai",
    "--modes", $Modes,
    "--ablation-source", "gold",
    "--repeats", $Repeats
)

$Manifest = Get-Content (Join-Path $RunDir "run_manifest.json") -Raw | ConvertFrom-Json
if ($Manifest.current_context_source -ne "openai") {
    throw "Run manifest does not use OpenAI context."
}
if ($Manifest.context_enrichment_prompt_version -ne "chunk-context-v4") {
    throw "Expected chunk-context-v4 but manifest contains $($Manifest.context_enrichment_prompt_version)."
}
$FallbackCount = [int]$Manifest.context_enrichment_fallback_count
if ($FallbackCount -gt 0 -and -not $AllowContextFallback) {
    throw (
        "Context v4 produced $FallbackCount fallback chunk(s). " +
        "Inspect the warning, then rerun; valid cache entries will be reused."
    )
}

Write-Host "[3/5] Auditing raw and effective context quality..."
Invoke-CheckedPython @(
    $Auditor,
    "--corpus", $Corpus,
    "--output", $QualityAudit,
    "--max-words", $ContextMaxWords
)

$CommonScoreArgs = @(
    $Scorer,
    "--testset", $ResolvedTestset,
    "--results", $Results,
    "--comparisons", $Comparisons,
    "--bootstrap-samples", $BootstrapSamples
)

Write-Host "[4/5] Scoring all paired queries..."
Invoke-CheckedPython ($CommonScoreArgs + @(
    "--output-dir", $AllMetricsDir,
    "--query-subset", "all"
))

Write-Host "[5/5] Scoring structured-filter-capable queries..."
Invoke-CheckedPython ($CommonScoreArgs + @(
    "--output-dir", $FilterMetricsDir,
    "--query-subset", "filter_capable"
))

Write-Host ""
Write-Host "Completed context quality ablation."
Write-Host "Run manifest:  " (Join-Path $RunDir "run_manifest.json")
Write-Host "Quality audit: " $QualityAudit
Write-Host "Quality JSON:  " ([System.IO.Path]::ChangeExtension($QualityAudit, ".summary.json"))
Write-Host "All metrics:   " (Join-Path $AllMetricsDir "retrieval_metric_comparison.csv")
Write-Host "Filter metrics:" (Join-Path $FilterMetricsDir "retrieval_metric_comparison.csv")
