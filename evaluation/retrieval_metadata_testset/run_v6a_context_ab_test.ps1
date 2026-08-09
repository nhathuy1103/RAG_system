[CmdletBinding()]
param(
    [ValidateSet("openai", "hashing")]
    [string]$EmbeddingProvider = "openai",

    [string]$EmbeddingModel = "text-embedding-3-small",

    [string]$SourceDir = (Join-Path $HOME "Downloads"),

    [string]$RunDir = "",

    [int]$Repeats = 3,

    [int]$BootstrapSamples = 5000,

    [int]$ContextMaxOutputTokens = 400,

    [ValidateRange(1, 100)]
    [int]$ContextMaxWords = 45,

    [switch]$AllowContextFallback
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = "python"
}

$BenchmarkDir = Join-Path $PSScriptRoot "real_benchmark_v3"
if ([string]::IsNullOrWhiteSpace($RunDir)) {
    $RunName = "real-benchmark-v3-v6a-context-v4-ab-{0}" -f $EmbeddingProvider
    $RunDir = Join-Path $PSScriptRoot (Join-Path "runs" $RunName)
}

$Builder = Join-Path $PSScriptRoot "build_real_metadata_benchmark.py"
$Runner = Join-Path $PSScriptRoot "run_abcd_experiment.py"
$Scorer = Join-Path $PSScriptRoot "score_experiment_comparison.py"
$Testset = Join-Path $BenchmarkDir "testset.jsonl"
$GoldMetadata = Join-Path $BenchmarkDir "gold_metadata.json"
$EmbeddingCache = Join-Path $BenchmarkDir ".cache\embedding_cache.json"
$ContextCache = Join-Path $BenchmarkDir ".cache\context_enrichment_cache.json"

$BeforeDir = Join-Path $RunDir "before_base_context"
$AfterDir = Join-Path $RunDir "after_openai_context_v3"
$BeforeResults = Join-Path $BeforeDir "retrieval_results.jsonl"
$AfterResults = Join-Path $AfterDir "retrieval_results.jsonl"
$BeforeCorpus = Join-Path $BeforeDir "corpus.jsonl"
$AfterCorpus = Join-Path $AfterDir "corpus.jsonl"
$BeforeResolvedTestset = Join-Path $BeforeDir "testset.resolved.jsonl"
$AfterResolvedTestset = Join-Path $AfterDir "testset.resolved.jsonl"
$MergedResults = Join-Path $RunDir "retrieval_results.context_ab.jsonl"
$ContextComparison = Join-Path $RunDir "context_summary_comparison.csv"
$AllMetricsDir = Join-Path $RunDir "metrics_all_queries"
$FilterMetricsDir = Join-Path $RunDir "metrics_filter_capable"
$Comparison = "v6a_base_context:v6a_openai_context_v3:openai_context_v3_minus_base"

function Invoke-CheckedPython {
    param([object[]]$Arguments)

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Remove-FallbackContextCacheEntries {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }
    $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($null -eq $payload.entries) {
        return
    }

    $kept = [ordered]@{}
    $removed = 0
    foreach ($property in $payload.entries.PSObject.Properties) {
        if ([string]$property.Value.status -eq "fallback") {
            $removed += 1
            continue
        }
        $kept[$property.Name] = $property.Value
    }
    if ($removed -eq 0) {
        return
    }

    $replacement = [ordered]@{
        schema_version = $payload.schema_version
        model = $payload.model
        entries = $kept
    }
    $tempPath = "$Path.tmp"
    $json = $replacement | ConvertTo-Json -Depth 20 -Compress
    [System.IO.File]::WriteAllText($tempPath, $json, $Utf8NoBom)
    Move-Item -LiteralPath $tempPath -Destination $Path -Force
    Write-Host "Removed $removed cached fallback context entries; they will be retried."
}

function Add-LabeledResults {
    param(
        [string]$SourcePath,
        [string]$Mode,
        [System.IO.StreamWriter]$Writer
    )

    $resolvedPath = (Resolve-Path -LiteralPath $SourcePath).Path
    foreach ($line in [System.IO.File]::ReadLines($resolvedPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $row = $line | ConvertFrom-Json
        $row.mode = $Mode
        $Writer.WriteLine(($row | ConvertTo-Json -Depth 30 -Compress))
    }
}

function Read-CorpusByChunkId {
    param([string]$Path)

    $rows = @{}
    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    foreach ($line in [System.IO.File]::ReadLines($resolvedPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $row = $line | ConvertFrom-Json
        $rows[[string]$row.chunk_id] = $row
    }
    return $rows
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

# The child runner loads .env without overriding process variables. Set the A/B
# output budget explicitly so an older .env value cannot truncate JSON responses.
$env:CONTEXTUAL_ENRICHMENT_MAX_OUTPUT_TOKENS = [string]$ContextMaxOutputTokens
$env:CONTEXTUAL_ENRICHMENT_MAX_CONTEXT_WORDS = [string]$ContextMaxWords

New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

Write-Host "[1/7] Verifying the approved frozen benchmark..."
Invoke-CheckedPython @(
    $Builder,
    "--source-dir", $SourceDir,
    "--output-dir", $BenchmarkDir
)

$CommonRunnerArgs = @(
    $Runner,
    "--source-dir", $SourceDir,
    "--testset", $Testset,
    "--gold-metadata", $GoldMetadata,
    "--embedding-provider", $EmbeddingProvider,
    "--embedding-model", $EmbeddingModel,
    "--embedding-cache", $EmbeddingCache,
    "--context-cache", $ContextCache,
    "--modes", "v6a_filter_only",
    "--ablation-source", "gold",
    "--repeats", $Repeats
)

Write-Host "[2/7] Running BEFORE: v6a with base context..."
Invoke-CheckedPython ($CommonRunnerArgs + @(
    "--output-dir", $BeforeDir,
    "--current-context-source", "base"
))

Remove-FallbackContextCacheEntries -Path $ContextCache

Write-Host "[3/7] Running AFTER: v6a with OpenAI context v3..."
Invoke-CheckedPython ($CommonRunnerArgs + @(
    "--output-dir", $AfterDir,
    "--current-context-source", "openai"
))

$BeforeManifest = Get-Content (Join-Path $BeforeDir "run_manifest.json") -Raw |
    ConvertFrom-Json
$AfterManifest = Get-Content (Join-Path $AfterDir "run_manifest.json") -Raw |
    ConvertFrom-Json
if ($BeforeManifest.current_context_source -ne "base") {
    throw "BEFORE manifest does not use base context."
}
if ($AfterManifest.current_context_source -ne "openai") {
    throw "AFTER manifest does not use OpenAI context."
}
if ($AfterManifest.context_enrichment_prompt_version -ne "chunk-context-v4") {
    throw "AFTER manifest does not use chunk-context-v4."
}
if ($BeforeManifest.embedding_provider -ne $AfterManifest.embedding_provider) {
    throw "Embedding providers differ between BEFORE and AFTER."
}
$FallbackCount = [int]$AfterManifest.context_enrichment_fallback_count
if ($FallbackCount -gt 0 -and -not $AllowContextFallback) {
    throw (
        "OpenAI context enrichment produced $FallbackCount fallback chunk(s). " +
        "Increase retry/backoff settings and rerun; generated cache entries will be reused."
    )
}

$BeforeTestsetHash = (Get-FileHash -LiteralPath $BeforeResolvedTestset -Algorithm SHA256).Hash
$AfterTestsetHash = (Get-FileHash -LiteralPath $AfterResolvedTestset -Algorithm SHA256).Hash
if ($BeforeTestsetHash -ne $AfterTestsetHash) {
    throw "Resolved testsets differ between BEFORE and AFTER."
}

Write-Host "[4/7] Pairing the two result sets..."
$Writer = [System.IO.StreamWriter]::new($MergedResults, $false, $Utf8NoBom)
try {
    Add-LabeledResults -SourcePath $BeforeResults -Mode "v6a_base_context" -Writer $Writer
    Add-LabeledResults -SourcePath $AfterResults -Mode "v6a_openai_context_v3" -Writer $Writer
}
finally {
    $Writer.Dispose()
}

Write-Host "[5/7] Exporting contextual_summary before/after rows..."
$BeforeByChunkId = Read-CorpusByChunkId -Path $BeforeCorpus
$ContextRows = foreach ($line in [System.IO.File]::ReadLines((Resolve-Path $AfterCorpus).Path)) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $After = $line | ConvertFrom-Json
    $Before = $BeforeByChunkId[[string]$After.chunk_id]
    if ($null -eq $Before) {
        throw "Chunk $($After.chunk_id) is missing from the BEFORE corpus."
    }
    $BeforeSummary = [string]$Before.gold_metadata.contextual_summary
    $RawAfterSummary = [string]$After.current_metadata.contextual_summary
    $AfterSummary = [string]$After.gold_metadata.contextual_summary
    [PSCustomObject]@{
        chunk_id = [string]$After.chunk_id
        document_title = [string]$After.document_title
        chunk_index = [int]$After.chunk_index
        section_title = [string]$After.gold_metadata.section_title
        before_contextual_summary = $BeforeSummary
        openai_raw_contextual_summary = $RawAfterSummary
        effective_contextual_summary = $AfterSummary
        after_contextual_summary = $AfterSummary
        summary_overridden_by_gold = ($RawAfterSummary -ne $AfterSummary)
        openai_status = [string]$After.current_metadata.context_enrichment.status
        changed = ($BeforeSummary -ne $AfterSummary)
    }
}
$ContextRows | Export-Csv -LiteralPath $ContextComparison -NoTypeInformation -Encoding UTF8

$CommonScoreArgs = @(
    $Scorer,
    "--testset", $BeforeResolvedTestset,
    "--results", $MergedResults,
    "--comparisons", $Comparison,
    "--bootstrap-samples", $BootstrapSamples
)

Write-Host "[6/7] Scoring all 300 paired queries..."
Invoke-CheckedPython ($CommonScoreArgs + @(
    "--output-dir", $AllMetricsDir,
    "--query-subset", "all"
))

Write-Host "[7/7] Scoring structured-filter-capable paired queries..."
Invoke-CheckedPython ($CommonScoreArgs + @(
    "--output-dir", $FilterMetricsDir,
    "--query-subset", "filter_capable"
))

Write-Host ""
Write-Host "Completed v6a contextual-summary A/B test."
Write-Host "BEFORE manifest: " (Join-Path $BeforeDir "run_manifest.json")
Write-Host "AFTER manifest:  " (Join-Path $AfterDir "run_manifest.json")
Write-Host "Context rows:    " $ContextComparison
Write-Host "All-query delta: " (Join-Path $AllMetricsDir "retrieval_metric_comparison.csv")
Write-Host "Filter delta:    " (Join-Path $FilterMetricsDir "retrieval_metric_comparison.csv")
