param([string]$CapturePath = "", [switch]$NoOpen)
$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP "UEVR_DuoViewCaptures"
if (-not $CapturePath) {
    if (-not (Test-Path $root)) { throw "No capture found. Use CAPTURE NOW in UEVR first." }
    $CapturePath = Get-ChildItem $root -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $CapturePath -or -not (Test-Path (Join-Path $CapturePath "manifest.json"))) { throw "Capture manifest missing: $CapturePath" }
$manifest = Get-Content (Join-Path $CapturePath "manifest.json") -Raw | ConvertFrom-Json
function Html([string]$s) { return [System.Net.WebUtility]::HtmlEncode($s) }
$files = @(Get-ChildItem $CapturePath -Filter "*.bmp" -File)
$xr = $files | Where-Object { $_.BaseName -match '^image_[0-9]+_xr_submitted_doublewide$' } | Select-Object -First 1
if ($xr) {
    try {
        Add-Type -AssemblyName System.Drawing
        $source = [System.Drawing.Image]::FromFile($xr.FullName)
        try {
            if ($source.Width -ge 2 -and ($source.Width % 2) -eq 0) {
                $eyeWidth = [int]($source.Width / 2)
                for ($eye=0; $eye -lt 2; $eye++) {
                    $outName = if ($eye -eq 0) { "CI50_left_eye_final.bmp" } else { "CI50_right_eye_final.bmp" }
                    $bmp = [System.Drawing.Bitmap]::new($eyeWidth,$source.Height)
                    try {
                        $g = [System.Drawing.Graphics]::FromImage($bmp)
                        try {
                            $from = [System.Drawing.Rectangle]::new(($eye * $eyeWidth),0,$eyeWidth,$source.Height)
                            $to = [System.Drawing.Rectangle]::new(0,0,$eyeWidth,$source.Height)
                            $g.DrawImage($source,$to,$from,[System.Drawing.GraphicsUnit]::Pixel)
                        } finally { $g.Dispose() }
                        $bmp.Save((Join-Path $CapturePath $outName),[System.Drawing.Imaging.ImageFormat]::Bmp)
                    } finally { $bmp.Dispose() }
                }
            } else { Write-Warning "Final XR capture is not an even-width double-wide image." }
        } finally { $source.Dispose() }
    } catch { Write-Warning ("Could not split final XR image: " + $_.Exception.Message) }
}
$labels = @(
    @("ngx_left_fovea_color","LEFT fovea: actual DLSS color"),
    @("ngx_left_fovea_depth","LEFT fovea: actual DLSS depth"),
    @("ngx_left_fovea_motion","LEFT fovea: actual DLSS motion vectors"),
    @("ngx_right_periphery_color","RIGHT periphery: actual DLSS color"),
    @("ngx_right_periphery_depth","RIGHT periphery: actual DLSS depth"),
    @("ngx_right_periphery_motion","RIGHT periphery: actual DLSS motion vectors"),
    @("left_fovea","UE fovea color"),
    @("right_periphery","UE periphery color"),
    @("xr_submitted_doublewide","Final XR double-wide image"),
    @("CI50_left_eye_final","Final LEFT eye"),
    @("CI50_right_eye_final","Final RIGHT eye")
)
$files = @(Get-ChildItem $CapturePath -Filter "*.bmp" -File)
$cards = New-Object System.Collections.Generic.List[string]
foreach ($pair in $labels) {
    $name = [string]$pair[0];$label=[string]$pair[1]
    $img = $files | Where-Object {
        $_.BaseName -eq $name -or $_.BaseName -match ("^image_[0-9]+_" + [regex]::Escape($name) + "(_|$)")
    } | Select-Object -First 1
    $src = if ($img) { [uri]::EscapeDataString($img.Name) } else { "" }
    $content = if ($img) { "<img loading='lazy' src='$src' alt='$(Html $label)'>" } else { "<div class='missing'>Not captured - inspect manifest exclusions</div>" }
    [void]$cards.Add("<figure><figcaption>$(Html $label)</figcaption>$content</figure>")
}
$warnings = @($manifest.excluded | ForEach-Object { "<li>$(Html ([string]$_))</li>" }) -join ""
$detail=Html ([string]$manifest.frame_info)
$inventory=Html ([string]$manifest.candidate_inventory)
$joined=$cards -join " "
$html=@"
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DuoView NGX capture</title>
<style>body{font:14px system-ui;background:#11161d;color:#e9edf5;margin:26px}h1{font-size:26px}p{color:#b9c2d0}
section{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
figure{margin:0;background:#202833;border:1px solid #344052;border-radius:10px;overflow:hidden}
figcaption{padding:11px;font-weight:600}img{width:100%;max-height:470px;object-fit:contain;background:#080a0d}
.missing{padding:34px;color:#ffd29b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1c2530;padding:14px}</style></head><body>
<h1>DuoView: original DLSS inputs and reconstructed eyes</h1>
<p>Raw files are authoritative. Images are display-only (HDR tonemapped, depth contrast adjusted, MV direction/magnitude mapped).</p>
<section>$joined</section>
<h2>Missing resources and exclusions</h2><ul>$warnings</ul>
<details><summary>Frame metadata</summary><pre>$detail</pre></details>
<details><summary>NGX resource provenance</summary><pre>$inventory</pre></details>
</body></html>
"@
$target=Join-Path $CapturePath "CI50_DLSS_CAPTURE_VIEWER.html"
[System.IO.File]::WriteAllText($target,$html,[System.Text.Encoding]::UTF8)
Write-Host "DuoView NGX capture viewer created: $target"
if (-not $NoOpen) { Start-Process $target }
