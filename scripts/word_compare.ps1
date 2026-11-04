# Tracked-changes comparison of two chapter versions with Microsoft Word (Review > Compare).
# Called by build.py redline.
param(
    [Parameter(Mandatory = $true)][string]$Original,
    [Parameter(Mandatory = $true)][string]$Revised,
    [Parameter(Mandatory = $true)][string]$Output
)
$ErrorActionPreference = "Stop"
$Original = (Resolve-Path $Original).Path
$Revised = (Resolve-Path $Revised).Path

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $a = $word.Documents.Open($Original, $false, $true)
    $b = $word.Documents.Open($Revised, $false, $true)
    # Destination 2 = new document; Granularity 1 = word level
    $cmp = $word.CompareDocuments($a, $b, 2, 1, $true, $true, $true, $true, $true, $true, $true, $true, $true, $true, "Revision", $true)
    $cmp.SaveAs2($Output, 16)
    $revs = $cmp.Revisions.Count
    $cmp.Close($false)
    $a.Close($false)
    $b.Close($false)
    Write-Output "compared: $revs revision(s)"
}
finally {
    $word.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
}
