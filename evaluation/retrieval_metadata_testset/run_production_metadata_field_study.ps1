[CmdletBinding()]
param(
    [ValidateSet("hashing", "openai")]
    [string]$EmbeddingProvider = "openai",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$SourceDir = "$HOME\Downloads",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000,

    [switch]$ReuseExtractedCorpus
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Aligner = Join-Path $PSScriptRoot "align_production_metadata_corpus.py"
$Builder = Join-Path $PSScriptRoot "build_extended_metadata_field_diagnostic.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$FrozenTestset = Join-Path $PSScriptRoot "real_benchmark_v3\testset.jsonl"
$GoldMetadata = Join-Path $PSScriptRoot "real_benchmark_v3\gold_metadata.json"
$FrozenCorpus = Join-Path $PSScriptRoot "runs\real-benchmark-v3-context-quality-v4-openai\corpus.jsonl"
$ExtractRun = Join-Path $PSScriptRoot "runs\production-metadata-field-study-corpus"
$ProductionCorpus = Join-Path $ExtractRun "corpus.jsonl"
$DiagnosticDir = Join-Path $PSScriptRoot "production_metadata_field_diagnostic"
$AlignedCorpus = Join-Path $DiagnosticDir "aligned_corpus.jsonl"
$DiagnosticTestset = Join-Path $DiagnosticDir "diagnostic_testset.jsonl"
$RunDir = Join-Path $PSScriptRoot ("runs\production-metadata-field-study-{0}" -f $EmbeddingProvider)
$EmbeddingCache = Join-Path $PSScriptRoot "real_benchmark_v3\.cache\embedding_cache.json"
$DecisionSummary = Join-Path $RunDir "production_field_decision_summary.csv"

function Invoke-CheckedPython {
    param([object[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

if ($Repeats -le 0 -or $BootstrapSamples -le 0) {
    throw "Repeats and BootstrapSamples must be greater than zero."
}

if (-not $ReuseExtractedCorpus) {
    Write-Host "[1/6] Extracting metadata with the current production pipeline (no gold injection)..."
    Invoke-CheckedPython @(
        $Runner,
        "--source-dir", $SourceDir,
        "--testset", $FrozenTestset,
        "--gold-metadata", $GoldMetadata,
        "--output-dir", $ExtractRun,
        "--embedding-provider", "hashing",
        "--current-context-source", "base",
        "--modes", "no_metadata",
        "--ablation-source", "current",
        "--production-metadata-only",
        "--allow-unresolved-ground-truth",
        "--repeats", 1
    )
} elseif (-not (Test-Path -LiteralPath $ProductionCorpus -PathType Leaf)) {
    throw "Missing extracted production corpus: $ProductionCorpus"
}

Write-Host "[2/6] Aligning production metadata to the approved frozen chunk identity..."
Invoke-CheckedPython @(
    $Aligner,
    "--frozen-corpus", $FrozenCorpus,
    "--production-corpus", $ProductionCorpus,
    "--output", $AlignedCorpus
)

Write-Host "[3/6] Auditing field coverage, agreement, candidate reduction and evidence retention..."
Invoke-CheckedPython @(
    $Builder,
    "--testset", $FrozenTestset,
    "--corpus", $AlignedCorpus,
    "--output-dir", $DiagnosticDir,
    "--metadata-source", "current"
)

$Profiles = Import-Csv (Join-Path $DiagnosticDir "metadata_field_profile.csv")
$Fields = @(
    $Profiles |
        Where-Object {
            [int]$_.current_coverage -gt 0 -and [int]$_.diagnostic_query_count -gt 0
        } |
        Select-Object -ExpandProperty field |
        Sort-Object
)
if ($Fields.Count -eq 0) {
    throw "No production-populated metadata field has diagnostic queries."
}
$Modes = @("filter_full") + @($Fields | ForEach-Object { "filter_drop_{0}" -f $_ })

Write-Host "[4/6] Running production-payload A/B filters for: $($Fields -join ', ')..."
Invoke-CheckedPython @(
    $Runner,
    "--testset", $DiagnosticTestset,
    "--corpus-fixture", $AlignedCorpus,
    "--corpus-fixture-kind", "real_document_snapshot",
    "--output-dir", $RunDir,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--current-context-source", "base",
    "--modes", ($Modes -join ","),
    "--ablation-source", "current",
    "--repeats", $Repeats
)

Write-Host "[5/6] Scoring field effects with scenario-clustered statistics..."
$CandidateRows = Import-Csv (Join-Path $DiagnosticDir "candidate_reduction_summary.csv")
$SummaryRows = @()
foreach ($Field in $Fields) {
    $DropMode = "filter_drop_{0}" -f $Field
    $FieldDir = Join-Path $RunDir ("metrics_by_field\{0}" -f $Field)
    Invoke-CheckedPython @(
        $Scorer,
        "--testset", (Join-Path $RunDir "testset.resolved.jsonl"),
        "--results", (Join-Path $RunDir "retrieval_results.jsonl"),
        "--output-dir", $FieldDir,
        "--query-subset", "filter_capable",
        "--metadata-field", $Field,
        "--bootstrap-samples", $BootstrapSamples,
        "--comparisons", ("{0}:filter_full:with_{1}_minus_without" -f $DropMode, $Field)
    )

    $Profile = $Profiles | Where-Object { $_.field -eq $Field } | Select-Object -First 1
    $Candidate = $CandidateRows | Where-Object { $_.field -eq $Field } | Select-Object -First 1
    $Comparisons = Import-Csv (Join-Path $FieldDir "retrieval_metric_comparison.csv")
    $Recall = $Comparisons | Where-Object { $_.metric -eq "recall_at_5" } | Select-Object -First 1
    $Agreement = if ($Profile.current_gold_agreement_rate -eq "") {
        0.0
    } else {
        [double]$Profile.current_gold_agreement_rate
    }
    $Retention = if ($Candidate.relevant_retention_rate -eq "") {
        0.0
    } else {
        [double]$Candidate.relevant_retention_rate
    }
    $PassesSafetyGate = (
        $Agreement -ge 0.98 -and
        $Retention -eq 1.0 -and
        [double]$Recall.cluster_ci95_low -ge 0.0
    )
    $StatisticallyConfirmed = [double]$Recall.cluster_p_value_permutation -le 0.05
    $Decision = if ($PassesSafetyGate -and $StatisticallyConfirmed) {
        "selected_confirmed"
    } elseif ($PassesSafetyGate) {
        "selected_guarded_rollout"
    } else {
        "hold_or_reject"
    }
    $SummaryRows += [pscustomobject]@{
        field = $Field
        current_coverage = $Profile.current_coverage
        corpus_chunks = 277
        labeled_overlap = $Profile.current_gold_overlap
        labeled_overlap_agreement = $Agreement
        relevant_retention = $Retention
        mean_candidates = $Candidate.mean_candidates
        candidate_reduction_pct = $Candidate.mean_candidate_reduction_pct
        recall_at_5_with = $Recall.right_mean
        recall_at_5_without = $Recall.left_mean
        recall_delta = $Recall.absolute_delta
        cluster_ci95_low = $Recall.cluster_ci95_low
        cluster_ci95_high = $Recall.cluster_ci95_high
        cluster_p_value = $Recall.cluster_p_value_permutation
        passes_safety_gate = $PassesSafetyGate
        statistically_confirmed = $StatisticallyConfirmed
        decision = $Decision
    }
}

Write-Host "[6/6] Exporting the reproducible decision table..."
$SummaryRows | Export-Csv -LiteralPath $DecisionSummary -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "Completed production-first metadata field study."
Write-Host "Aligned corpus:  $AlignedCorpus"
Write-Host "Field profile:   " (Join-Path $DiagnosticDir "metadata_field_profile.csv")
Write-Host "Run manifest:    " (Join-Path $RunDir "run_manifest.json")
Write-Host "Decision summary:" $DecisionSummary
