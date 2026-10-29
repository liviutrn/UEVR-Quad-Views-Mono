param([string]$CapturePath = "", [switch]$NoOpen)
$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP "UEVR_DuoViewCaptures"
if (-not $CapturePath) {
    if (-not (Test-Path $root)) { throw "No DuoView captures at $root. Press CAPTURE NOW in UEVR first." }
    $CapturePath = Get-ChildItem $root -Directory | Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $CapturePath -or -not (Test-Path (Join-Path $CapturePath "manifest.json"))) {
    throw "Capture manifest missing. Supply a capture directory as an argument."
}
$manifest = Get-Content (Join-Path $CapturePath "manifest.json") -Raw | ConvertFrom-Json
function Html([string]$s) { return [System.Net.WebUtility]::HtmlEncode($s) }
$labels = @(
    @("ngx_left_fovea_color", "LEFT FOVEA - DLSS color"),
    @("ngx_left_fovea_depth", "LEFT FOVEA - DLSS depth"),
    @("ngx_left_fovea_motion", "LEFT FOVEA - DLSS motion vectors"),
    @("ngx_right_periphery_color", "RIGHT PERIPHERY - DLSS color"),
    @("ngx_right_periphery_depth", "RIGHT PERIPHERY - DLSS depth"),
    @("ngx_right_periphery_motion", "RIGHT PERIPHERY - DLSS motion vectors"),
    @("left_fovea", "UE source - fovea"),
    @("right_periphery", "UE source - periphery"),
    @("xr_submitted_doublewide", "Submitted XR double-wide - both eyes"),
    @("CI50_left_eye_final", "SYNTHESIZED LEFT eye - final XR image"),
    @("CI50_right_eye_final", "SYNTHESIZED RIGHT eye - final XR image")
)
$files = @(Get-ChildItem $CapturePath -Filter "*.bmp" -File)
$xr = $files | Where-Object { $_.BaseName -match '^image_[0-9]+_xr_submitted_doublewide
$cards = New-Object System.Collections.Generic.List[string]
foreach ($pair in $labels) {
    $name = $pair[0]; $label = $pair[1]
    $img = $files | Where-Object { $_.BaseName -eq $name -or $_.BaseName -match ("^image_[0-9]+_" + [regex]::Escape($name) + "(_|$)") } | Select-Object -First 1
    $src = if ($img) { [uri]::EscapeDataString($img.Name) } else { "" }
    $imageTag = if ($img) { "<img loading='lazy' src='$src' alt='$(Html $label)'>" } else { "<div class='missing'>Not captured (see manifest)</div>" }
    [void]$cards.Add("<figure><figcaption>$(Html $label)</figcaption>$imageTag</figure>")
}
$warnings = @($manifest.excluded | ForEach-Object { "<li>$(Html ([string]$_))</li>" }) -join ""
$detail = Html ([string]$manifest.frame_info)
$inventory = Html ([string]$manifest.candidate_inventory)
$joinedCards = $cards -join " "
$html = @"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DuoView CI50 - NGX capture viewer</title>
<style>body{font:14px system-ui,sans-serif;background:#11161d;color:#e9edf5;margin:28px;max-width:1500px}
h1{font-size:26px}p{color:#b9c2d0}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:15px}
figure{margin:0;background:#202833;border:1px solid #344052;border-radius:10px;overflow:hidden}
figcaption{padding:12px;font-weight:650}img{display:block;width:100%;height:auto;max-height:440px;object-fit:contain;background:#080a0d}
.missing{padding:42px 10px;color:#ffd29b}pre{white-space:pre-wrap;word-wrap:break-word;max-height:420px;overflow:auto;background:#1c2530;padding:14px}
li{margin:4px 0}details{margin:15px 0}</style></head><body>
<h1>DuoView - DLSS input capture</h1><p>Two real source passes: LEFT fovea / RIGHT periphery. These captures do not prove stereo correctness. Depth is contrast-adjusted; motion colors are diagnostic.</p>
<section>$joinedCards</section>
<h2>Capture warnings</h2><ul>$warnings</ul>
<details><summary>Frame metadata</summary><pre>$detail</pre></details>
<details><summary>Candidate inventory and resource provenance</summary><pre>$inventory</pre></details>
</body></html>
"@
$target = Join-Path $CapturePath "CI50_DLSS_CAPTURE_VIEWER.html"
[System.IO.File]::WriteAllText($target, $html, [System.Text.Encoding]::UTF8)
Write-Host "DuoView capture viewer created: $target"
if (-not $NoOpen) { Start-Process $target }
 } | Select-Object -First 1
if ($xr) {
    try {
        Add-Type -AssemblyName System.Drawing
        $sourceImage = [System.Drawing.Image]::FromFile($xr.FullName)
        try {
            if ($sourceImage.Width -ge 2 -and ($sourceImage.Width % 2) -eq 0) {
                $eyeWidth = [int]($sourceImage.Width / 2)
                for ($eye = 0; $eye -lt 2; $eye++) {
                    $targetName = if ($eye -eq 0) { "CI50_left_eye_final.bmp" } else { "CI50_right_eye_final.bmp" }
                    $crop = [System.Drawing.Bitmap]::new($eyeWidth, $sourceImage.Height)
                    try {
                        $g = [System.Drawing.Graphics]::FromImage($crop)
                        try {
                            $from = [System.Drawing.Rectangle]::new(($eye * $eyeWidth),0,$eyeWidth,$sourceImage.Height)
                            $to = [System.Drawing.Rectangle]::new(0,0,$eyeWidth,$sourceImage.Height)
                            $g.DrawImage($sourceImage, $to, $from, [System.Drawing.GraphicsUnit]::Pixel)
                        } finally { $g.Dispose() }
                        $crop.Save((Join-Path $CapturePath $targetName),[System.Drawing.Imaging.ImageFormat]::Bmp)
                    } finally { $crop.Dispose() }
                }
            }
        } finally { $sourceImage.Dispose() }
    } catch {
        Write-Warning ("Eye cropping unavailable: " + $_.Exception.Message)
    }
}
$files = @(Get-ChildItem $CapturePath -Filter "*.bmp" -File)
$cards = New-Object System.Collections.Generic.List[string]
foreach ($pair in $labels) {
    $name = $pair[0]; $label = $pair[1]
    $img = $files | Where-Object { $_.BaseName -match ("^image_[0-9]+_" + [regex]::Escape($name) + "(_|$)") } | Select-Object -First 1
    $src = if ($img) { [uri]::EscapeDataString($img.Name) } else { "" }
    $imageTag = if ($img) { "<img loading='lazy' src='$src' alt='$(Html $label)'>" } else { "<div class='missing'>Not captured (see manifest)</div>" }
    [void]$cards.Add("<figure><figcaption>$(Html $label)</figcaption>$imageTag</figure>")
}
$warnings = @($manifest.excluded | ForEach-Object { "<li>$(Html ([string]$_))</li>" }) -join ""
$detail = Html ([string]$manifest.frame_info)
$inventory = Html ([string]$manifest.candidate_inventory)
$joinedCards = $cards -join " "
$html = @"
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>DuoView CI50 - NGX capture viewer</title>
<style>body{font:14px system-ui,sans-serif;background:#11161d;color:#e9edf5;margin:28px;max-width:1500px}
h1{font-size:26px}p{color:#b9c2d0}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:15px}
figure{margin:0;background:#202833;border:1px solid #344052;border-radius:10px;overflow:hidden}
figcaption{padding:12px;font-weight:650}img{display:block;width:100%;height:auto;max-height:440px;object-fit:contain;background:#080a0d}
.missing{padding:42px 10px;color:#ffd29b}pre{white-space:pre-wrap;word-wrap:break-word;max-height:420px;overflow:auto;background:#1c2530;padding:14px}
li{margin:4px 0}details{margin:15px 0}</style></head><body>
<h1>DuoView - DLSS input capture</h1><p>Two real source passes: LEFT fovea / RIGHT periphery. These captures do not prove stereo correctness. Depth is contrast-adjusted; motion colors are diagnostic.</p>
<section>$joinedCards</section>
<h2>Capture warnings</h2><ul>$warnings</ul>
<details><summary>Frame metadata</summary><pre>$detail</pre></details>
<details><summary>Candidate inventory and resource provenance</summary><pre>$inventory</pre></details>
</body></html>
"@
$target = Join-Path $CapturePath "CI50_DLSS_CAPTURE_VIEWER.html"
[System.IO.File]::WriteAllText($target, $html, [System.Text.Encoding]::UTF8)
Write-Host "DuoView capture viewer created: $target"
Start-Process $target
