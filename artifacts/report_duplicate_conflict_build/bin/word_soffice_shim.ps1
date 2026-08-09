param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AllArgs
)

$outDirIndex = [Array]::IndexOf($AllArgs, '--outdir')
$convertIndex = [Array]::IndexOf($AllArgs, '--convert-to')
if ($outDirIndex -lt 0 -or $convertIndex -lt 0) {
    Write-Error 'The Word conversion shim requires --outdir and --convert-to.'
    exit 2
}

$outDir = [System.IO.Path]::GetFullPath($AllArgs[$outDirIndex + 1])
$convertTo = $AllArgs[$convertIndex + 1].ToLowerInvariant()
$inputPath = [System.IO.Path]::GetFullPath($AllArgs[$AllArgs.Length - 1])
if ($convertTo -ne 'pdf') {
    Write-Error "The Word conversion shim only supports PDF, requested: $convertTo"
    exit 3
}

[System.IO.Directory]::CreateDirectory($outDir) | Out-Null
$outputPath = [System.IO.Path]::Combine(
    $outDir,
    [System.IO.Path]::GetFileNameWithoutExtension($inputPath) + '.pdf'
)

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($inputPath, $false, $true)
    # 17 = wdExportFormatPDF; 0 = wdExportOptimizeForPrint.
    $document.ExportAsFixedFormat($outputPath, 17, $false, 0)
    Write-Output "convert $inputPath -> $outputPath"
    exit 0
}
catch {
    Write-Error $_
    exit 4
}
finally {
    if ($null -ne $document) {
        $document.Close($false)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
    if ($null -ne $word) {
        $word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
