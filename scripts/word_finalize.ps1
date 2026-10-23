# Final pass in Microsoft Word: insert cover page, set page numbering, fill TOC / list of figures /
# list of tables, optionally export PDF. Called by build.py.
param(
    [Parameter(Mandatory = $true)][string]$Docx,
    [string]$Cover = "",
    [string]$CoverImage = "",
    [switch]$Pdf
)
$ErrorActionPreference = "Stop"
$Docx = (Resolve-Path $Docx).Path

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($Docx, $false, $false, $false)

    # --- cover page in its own section
    if ($Cover -or $CoverImage) {
        $before = $doc.Content.End
        $start = $doc.Range(0, 0)
        if ($Cover) {
            $start.InsertFile((Resolve-Path $Cover).Path)
        } else {
            $start.InsertParagraphBefore()
            $pic = $doc.Range(0, 0).InlineShapes.AddPicture((Resolve-Path $CoverImage).Path, $false, $true)
            $ps = $doc.Sections.Item(1).PageSetup
            $maxW = $ps.PageWidth - $ps.LeftMargin - $ps.RightMargin
            $maxH = $ps.PageHeight - $ps.TopMargin - $ps.BottomMargin - 20
            $ratio = [Math]::Min($maxW / $pic.Width, $maxH / $pic.Height)
            $pic.Width = $pic.Width * $ratio
            $pic.Height = $pic.Height * $ratio
        }
        $inserted = $doc.Content.End - $before
        $doc.Range($inserted, $inserted).InsertBreak(2)   # wdSectionBreakNextPage
    }

    # --- page numbers: cover none, front matter roman (i, ii), body arabic from 1
    $secs = $doc.Sections
    $count = $secs.Count
    for ($i = 2; $i -le $count; $i++) {
        $secs.Item($i).Footers.Item(1).LinkToPrevious = $false
    }
    $hasCover = [bool]($Cover -or $CoverImage)
    for ($i = 1; $i -le $count; $i++) {
        $footer = $secs.Item($i).Footers.Item(1)
        $footer.Range.Text = ""
        if ($hasCover -and $i -eq 1) { continue }
        $r = $footer.Range
        $doc.Fields.Add($r, 33) | Out-Null           # wdFieldPage
        $footer.Range.ParagraphFormat.Alignment = 1   # centre
        $footer.Range.Font.Name = "Times New Roman"
        $footer.Range.Font.Size = 12
        $pn = $footer.PageNumbers
        $pn.RestartNumberingAtSection = $true
        $pn.StartingNumber = 1
        if ($i -lt $count) { $pn.NumberStyle = 2 } else { $pn.NumberStyle = 0 }   # roman / arabic
    }

    # --- fill TOC, list of figures, list of tables (twice so page numbers settle)
    for ($pass = 0; $pass -lt 2; $pass++) {
        $doc.Fields.Update() | Out-Null
        foreach ($t in $doc.TablesOfContents) { $t.Update() }
    }
    $toc = $doc.TablesOfContents.Count
    $doc.Save()
    if ($Pdf) {
        $pdfPath = [IO.Path]::ChangeExtension($Docx, ".pdf")
        # 17 = wdExportFormatPDF; CreateBookmarks 1 = from headings
        $doc.ExportAsFixedFormat($pdfPath, 17, $false, 0, 0, 1, 1, 0, $true, $true, 1)
        Write-Output "PDF: $pdfPath"
    }
    $pages = $doc.ComputeStatistics(2)
    $doc.Close($false)
    Write-Output "finalised: $count section(s), $toc index field(s), $pages page(s)"
}
finally {
    $word.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
}
