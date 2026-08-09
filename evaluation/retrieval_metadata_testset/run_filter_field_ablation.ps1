[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "openai",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$SourceDir = (Join-Path $HOME "Downloads"),

    [string]$CorpusFixture = "",

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000,

    [switch]$SkipBenchmarkVerification
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "real_benchmark_v3"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunName = "real-benchmark-v3-filter-field-ablation-{0}" -f $EmbeddingProvider
    $RunDir = Join-Path $PSScriptRoot (Join-Path "runs" $RunName)
}

$Builder = Join-Path $PSScriptRoot "build_real_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$GoldMetadata = Join-Path $BenchmarkDir "gold_metadata.json"
$EmbeddingCache = Join-Path $BenchmarkDir ".cache\embedding_cache.json"
$ContextCache = Join-Path $BenchmarkDir ".cache\context_enrichment_cache.json"
$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$AllMetricsDir = Join-Path $RunDir "metrics_filter_capable"
$FieldMetricsRoot = Join-Path $RunDir "metrics_by_field"
$DecisionSummary = Join-Path $RunDir "filter_field_decision_summary.csv"
if ([string]::IsNullOrWhiteSpace($CorpusFixture)) {
    $CandidateFixture = Join-Path $PSScriptRoot "runs\real-benchmark-v3-context-quality-v4-openai\corpus.jsonl"
    if (Test-Path -LiteralPath $CandidateFixture -PathType Leaf) {
        $CorpusFixture = $CandidateFixture
    }
}

$Fields = @(
    @{ Name = "document_type"; DropMode = "filter_drop_document_type" },
    @{ Name = "project_name"; DropMode = "filter_drop_project_name" },
    @{ Name = "year"; DropMode = "filter_drop_year" },
    @{ Name = "lifecycle_status"; DropMode = "filter_drop_lifecycle_status" },
    @{ Name = "source"; DropMode = "filter_drop_source" }
)
$Modes = @(
    "filter_full",
    "filter_drop_document_type",
    "filter_drop_project_name",
    "filter_drop_year",
    "filter_drop_lifecycle_status",
    "filter_drop_source",
    "filter_drop_all_domain"
)
$Comparisons = @(
    "filter_full:filter_drop_document_type:without_document_type_minus_full",
    "filter_full:filter_drop_project_name:without_project_name_minus_full",
    "filter_full:filter_drop_year:without_year_minus_full",
    "filter_full:filter_drop_lifecycle_status:without_lifecycle_status_minus_full",
    "filter_full:filter_drop_source:without_source_minus_full",
    "filter_full:filter_drop_all_domain:without_all_domain_filters_minus_full"
)

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

if ($SkipBenchmarkVerification) {
    Write-Host "[1/4] Reusing the previously verified frozen benchmark..."
} else {
    Write-Host "[1/4] Verifying the approved frozen benchmark..."
    Invoke-CheckedPython @(
        $Builder,
        "--source-dir", $SourceDir,
        "--output-dir", $BenchmarkDir
    )
}

Write-Host "[2/4] Running full-filter and leave-one-field-out modes..."
$RunnerArgs = @(
    $Runner,
    "--testset", $Testset,
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--context-cache", $ContextCache,
    "--current-context-source", "base",
    "--modes", ($Modes -join ","),
    "--ablation-source", "gold",
    "--repeats", $Repeats
)
if ([string]::IsNullOrWhiteSpace($CorpusFixture)) {
    $RunnerArgs += @(
        "--source-dir", $SourceDir,
        "--gold-metadata", $GoldMetadata
    )
} else {
    Write-Host "Using frozen corpus fixture: $CorpusFixture"
    $RunnerArgs += @(
        "--corpus-fixture", $CorpusFixture,
        "--corpus-fixture-kind", "real_document_snapshot"
    )
}
Invoke-CheckedPython $RunnerArgs

$CommonScoreArgs = @(
    $Scorer,
    "--testset", $ResolvedTestset,
    "--results", $Results,
    "--bootstrap-samples", $BootstrapSamples,
    "--query-subset", "filter_capable"
)

Write-Host "[3/4] Scoring all 110 filter-capable queries..."
Invoke-CheckedPython ($CommonScoreArgs + @(
    "--output-dir", $AllMetricsDir,
    "--comparisons", ($Comparisons -join ",")
))

Write-Host "[4/4] Scoring each field only on queries that require it..."
$SummaryRows = @()
foreach ($Field in $Fields) {
    $FieldName = [string]$Field.Name
    $DropMode = [string]$Field.DropMode
    $FieldDir = Join-Path $FieldMetricsRoot $FieldName
    $ComparisonName = "without_{0}_minus_full" -f $FieldName
    Invoke-CheckedPython ($CommonScoreArgs + @(
        "--output-dir", $FieldDir,
        "--metadata-field", $FieldName,
        "--comparisons", ("filter_full:{0}:{1}" -f $DropMode, $ComparisonName)
    ))

    $Scope = Get-Content (Join-Path $FieldDir "evaluation_scope.json") -Raw | ConvertFrom-Json
    $Rows = Import-Csv (Join-Path $FieldDir "retrieval_metric_comparison.csv")
    foreach ($Metric in @("recall_at_5", "mrr_at_10", "null_rejection_at_10", "empty_result_rate")) {
        $Row = $Rows | Where-Object { $_.metric -eq $Metric } | Select-Object -First 1
        if ($null -eq $Row) {
            continue
        }
        $SummaryRows += [pscustomobject]@{
            field = $FieldName
            selected_queries = [int]$Scope.selected_query_count
            selected_answerable = [int]$Scope.selected_answerable_count
            metric = $Metric
            full_filter = $Row.left_mean
            without_field = $Row.right_mean
            delta = $Row.absolute_delta
            ci95_low = $Row.ci95_low
            ci95_high = $Row.ci95_high
            wins = $Row.win
            ties = $Row.tie
            losses = $Row.loss
            p_value = $Row.p_value_permutation
            scenario_clusters = $Row.cluster_count
            cluster_ci95_low = $Row.cluster_ci95_low
            cluster_ci95_high = $Row.cluster_ci95_high
            cluster_p_value = $Row.cluster_p_value_permutation
        }
    }
}

$SummaryRows | Export-Csv -LiteralPath $DecisionSummary -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "Completed pre-retrieval metadata field ablation."
Write-Host "Run manifest:    " (Join-Path $RunDir "run_manifest.json")
Write-Host "All comparisons: " (Join-Path $AllMetricsDir "retrieval_metric_comparison.csv")
Write-Host "Field metrics:   " $FieldMetricsRoot
Write-Host "Decision summary:" $DecisionSummary
