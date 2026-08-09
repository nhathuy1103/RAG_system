[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "openai",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000
)

$ErrorActionPreference = "Stop"

Write-Warning (
    "This legacy study uses gold/oracle metadata to estimate field utility. " +
    "Do not use it for production field approval; run run_production_metadata_field_study.ps1."
)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$DiagnosticDir = Join-Path $PSScriptRoot "extended_metadata_field_diagnostic"
$Builder = Join-Path $PSScriptRoot "build_extended_metadata_field_diagnostic.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$FrozenTestset = Join-Path $PSScriptRoot "real_benchmark_v3\testset.jsonl"
$CorpusFixture = Join-Path $PSScriptRoot "runs\real-benchmark-v3-context-quality-v4-openai\corpus.jsonl"
$Testset = Join-Path $DiagnosticDir "diagnostic_testset.jsonl"
$EmbeddingCache = Join-Path $PSScriptRoot "real_benchmark_v3\.cache\embedding_cache.json"

if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunDir = Join-Path $PSScriptRoot ("runs\extended-metadata-field-study-{0}" -f $EmbeddingProvider)
}

$ResolvedTestset = Join-Path $RunDir "testset.resolved.jsonl"
$Results = Join-Path $RunDir "retrieval_results.jsonl"
$FieldMetricsRoot = Join-Path $RunDir "metrics_by_field"
$DecisionSummary = Join-Path $RunDir "extended_field_decision_summary.csv"

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
if (-not (Test-Path -LiteralPath $CorpusFixture -PathType Leaf)) {
    throw "Missing real-document corpus fixture: $CorpusFixture"
}

Write-Host "[1/4] Building the traceable diagnostic testset..."
Invoke-CheckedPython @(
    $Builder,
    "--testset", $FrozenTestset,
    "--corpus", $CorpusFixture,
    "--output-dir", $DiagnosticDir
)

$Manifest = Get-Content (Join-Path $DiagnosticDir "diagnostic_manifest.json") -Raw | ConvertFrom-Json
$Fields = @($Manifest.field_query_counts.PSObject.Properties.Name | Sort-Object)
$Modes = @("filter_full") + @($Fields | ForEach-Object { "filter_drop_{0}" -f $_ })

Write-Host "[2/4] Running standalone field filters and no-field controls..."
Invoke-CheckedPython @(
    $Runner,
    "--testset", $Testset,
    "--corpus-fixture", $CorpusFixture,
    "--corpus-fixture-kind", "real_document_snapshot",
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--current-context-source", "base",
    "--modes", ($Modes -join ","),
    "--ablation-source", "gold",
    "--repeats", $Repeats
)

Write-Host "[3/4] Scoring each field with scenario-clustered statistics..."
$SummaryRows = @()
$CandidateSummary = Import-Csv (Join-Path $DiagnosticDir "candidate_reduction_summary.csv")
foreach ($FieldName in $Fields) {
    $DropMode = "filter_drop_{0}" -f $FieldName
    $ComparisonName = "without_{0}_minus_full" -f $FieldName
    $FieldDir = Join-Path $FieldMetricsRoot $FieldName
    Invoke-CheckedPython @(
        $Scorer,
        "--testset", $ResolvedTestset,
        "--results", $Results,
        "--output-dir", $FieldDir,
        "--query-subset", "filter_capable",
        "--metadata-field", $FieldName,
        "--bootstrap-samples", $BootstrapSamples,
        "--comparisons", ("filter_full:{0}:{1}" -f $DropMode, $ComparisonName)
    )

    $Scope = Get-Content (Join-Path $FieldDir "evaluation_scope.json") -Raw | ConvertFrom-Json
    $Rows = Import-Csv (Join-Path $FieldDir "retrieval_metric_comparison.csv")
    $ModeSummary = Import-Csv (Join-Path $FieldDir "retrieval_metric_summary.csv")
    $FullMode = $ModeSummary | Where-Object { $_.mode -eq "filter_full" } | Select-Object -First 1
    $DropModeRow = $ModeSummary | Where-Object { $_.mode -eq $DropMode } | Select-Object -First 1
    $Candidate = $CandidateSummary | Where-Object { $_.field -eq $FieldName } | Select-Object -First 1

    foreach ($Metric in @("recall_at_5", "mrr_at_10", "ndcg_at_10", "null_rejection_at_10", "forbidden_top1_rate")) {
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
            query_ci95_low = $Row.ci95_low
            query_ci95_high = $Row.ci95_high
            query_p_value = $Row.p_value_permutation
            scenario_clusters = $Row.cluster_count
            cluster_ci95_low = $Row.cluster_ci95_low
            cluster_ci95_high = $Row.cluster_ci95_high
            cluster_p_value = $Row.cluster_p_value_permutation
            full_latency_p50_ms = $FullMode.latency_p50_ms
            without_field_latency_p50_ms = $DropModeRow.latency_p50_ms
            mean_prefilter_candidates = $Candidate.mean_candidates
            mean_candidate_reduction_pct = $Candidate.mean_candidate_reduction_pct
            evidence_bases = $Candidate.evidence_bases
        }
    }
}

Write-Host "[4/4] Exporting the decision table..."
$SummaryRows | Export-Csv -LiteralPath $DecisionSummary -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "Completed extended metadata field study."
Write-Host "Diagnostic manifest:" (Join-Path $DiagnosticDir "diagnostic_manifest.json")
Write-Host "Review sheet:       " (Join-Path $DiagnosticDir "queries_for_review.csv")
Write-Host "Run manifest:       " (Join-Path $RunDir "run_manifest.json")
Write-Host "Decision summary:   " $DecisionSummary
