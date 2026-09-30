# QingLan icon - geometry owner and PNG exporter (PowerShell 5.1 + GDI+, no external deps).
#
# The mark is authored once in a 64-unit design space; everything else (favicon PNGs, contact
# sheets) is derived from it, and svg/*.svg carries the identical numbers.
#
#   .\render.ps1              # export png/ + check/
#   $env:QL_TONE=0.22; .\render.ps1   # try another container lightness
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = 'Stop'

$ROOT = $PSScriptRoot
$CHK = Join-Path $ROOT 'check'
$PNG = Join-Path $ROOT 'png'
foreach ($d in @($CHK, $PNG)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null } }

# ---------------------------------------------------------------- color utils
$WH = '#FFFFFF'
$BRAND = '#0F6CBD'                     # site default brand_color (admin can change it)
function Col([string]$hex, [double]$alpha = 1.0) {
  $c = [System.Drawing.ColorTranslator]::FromHtml($hex)
  return [System.Drawing.Color]::FromArgb([int][math]::Round($alpha * 255), $c.R, $c.G, $c.B)
}
function Mix([string]$hex, [string]$to, [double]$t) {
  $a = [System.Drawing.ColorTranslator]::FromHtml($hex); $b = [System.Drawing.ColorTranslator]::FromHtml($to)
  (([System.Drawing.Color]::FromArgb(255,
    [int][math]::Round($a.R + ($b.R - $a.R) * $t),
    [int][math]::Round($a.G + ($b.G - $a.G) * $t),
    [int][math]::Round($a.B + ($b.B - $a.B) * $t))).Name) -replace '^ff', '#'
}
function Ramp([string]$mid) {
  # single continuous vertical ramp, glossy top baked in (no overlay seam)
  return @{
    hexes = @((Mix $mid '#FFFFFF' 0.34), (Mix $mid '#FFFFFF' 0.15), $mid, (Mix $mid '#000000' 0.15))
    pos   = @(0.0, 0.16, 0.52, 1.0)
  }
}

# ---------------------------------------------------------------- drawing utils
function New-RoundedRect([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  if ($r -le 0) { $p.AddRectangle([System.Drawing.RectangleF]::new($x, $y, $w, $h)); return $p }
  $d = $r * 2
  $p.AddArc($x, $y, $d, $d, [single]180, [single]90)
  $p.AddArc($x + $w - $d, $y, $d, $d, [single]270, [single]90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, [single]0, [single]90)
  $p.AddArc($x, $y + $h - $d, $d, $d, [single]90, [single]90)
  $p.CloseFigure(); return $p
}
function New-RectF($x, $y, $w, $h) { return [System.Drawing.RectangleF]::new([single]$x, [single]$y, [single]$w, [single]$h) }
function Get-ArcPoints([double]$cx, [double]$cy, [double]$r, [double]$a0, [double]$a1, [int]$n) {
  $arr = New-Object 'System.Drawing.PointF[]' ($n + 1)
  for ($i = 0; $i -le $n; $i++) {
    $a = ($a0 + ($a1 - $a0) * $i / $n) * [Math]::PI / 180.0
    $arr[$i] = [System.Drawing.PointF]::new([single]($cx + $r * [Math]::Cos($a)), [single]($cy + $r * [Math]::Sin($a)))
  }
  return ,$arr
}
function New-VGradBrush($rect, $hexes, $alphas, $positions) {
  $last = $hexes.Count - 1
  $gb = [System.Drawing.Drawing2D.LinearGradientBrush]::new($rect, (Col $hexes[0] 1), (Col $hexes[$last] 1),
            [System.Drawing.Drawing2D.LinearGradientMode]::Vertical)
  $cb = New-Object System.Drawing.Drawing2D.ColorBlend
  $cols = New-Object 'System.Drawing.Color[]' $hexes.Count
  for ($i = 0; $i -le $last; $i++) { $cols[$i] = Col $hexes[$i] ([double]$alphas[$i]) }
  $cb.Colors = $cols; $cb.Positions = [double[]]$positions
  $gb.InterpolationColors = $cb; return $gb
}
function New-RoundPen($color, [double]$width) {
  $pen = [System.Drawing.Pen]::new($color, [single]$width)
  $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
  $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
  $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
  return $pen
}

# ---------------------------------------------------------------- THE MARK
# 蓝 = ring at reduced opacity (the source, the teacher, the platform)
# 青 = solid stroke that starts inside the ring, leaves through the gap and rises past the
#      outer edge (what comes out of blue, and surpasses it) - the bend doubles as an Accepted tick
$RCX = 31.0; $RCY = 36.0; $RR = 12.5; $RING_A0 = -10.0; $RING_A1 = 290.0; $STROKE = 6.5
$CHECK = [System.Drawing.PointF[]]@(
  [System.Drawing.PointF]::new(26.0, 33.0),
  [System.Drawing.PointF]::new(28.5, 38.5),
  [System.Drawing.PointF]::new(47.6, 19.3))

function Get-RingAlpha([double]$sizePx) {
  if ($sizePx -le 24) { return 0.72 } elseif ($sizePx -le 40) { return 0.64 } else { return 0.55 }
}
# spec carries every optical knob; small sizes get their own weights (see $OPT_SMALL below)
function New-Spec($base, $over) {
  $s = @{ mid = $MID; shell = $true; ink = $WH; ring = -1; ringW = 6.5; checkW = 6.5; hairline = $true
          rr = 12.5; cx = 31.0; cy = 36.0; pts = $CHECK }
  foreach ($h in @($base, $over)) {
    if ($h) { foreach ($k in $h.Keys) { $s[$k] = $h[$k] } }
  }
  return $s
}
function Draw-Mark($g, $s, [double]$sizePx) {
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $ring = if ($s.ring -lt 0) { Get-RingAlpha $sizePx } else { [double]$s.ring }
  if ($s.shell) {
    $shell = New-RoundedRect 2 2 60 60 15
    $r = Ramp $s.mid
    $g.FillPath((New-VGradBrush (New-RectF 2 2 60 60) $r.hexes @(1, 1, 1, 1) $r.pos), $shell)
    if ($s.hairline) {
      $g.DrawPath((New-RoundPen (Col $WH 0.30) 1.6), (New-RoundedRect 2.9 2.9 58.2 58.2 14.1))
    }
  }
  $g.DrawLines((New-RoundPen (Col $s.ink $ring) $s.ringW), (Get-ArcPoints $s.cx $s.cy $s.rr $RING_A0 $RING_A1 260))
  $g.DrawLines((New-RoundPen (Col $s.ink 1.0) $s.checkW), $s.pts)
}
function Add-MarkAt($g, [double]$x, [double]$y, [double]$sizePx, $opt) {
  $st = $g.Save()
  $g.TranslateTransform([single]$x, [single]$y) | Out-Null
  $g.ScaleTransform([single]($sizePx / 64.0), [single]($sizePx / 64.0)) | Out-Null
  Draw-Mark $g $opt $sizePx
  $g.Restore($st) | Out-Null
}
function New-Canvas([int]$w, [int]$h, [string]$bg) {
  $bmp = [System.Drawing.Bitmap]::new($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  if ($bg) { $g.Clear((Col $bg 1.0)) } else { $g.Clear([System.Drawing.Color]::Transparent) }
  return @{ bmp = $bmp; g = $g }
}
function Save-Canvas($cv, [string]$path) {
  $cv.bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Output ("  {0,-34} {1,5}x{2}" -f (Split-Path $path -Leaf), $cv.bmp.Width, $cv.bmp.Height)
}
function Plate($g, $x, $y, $w, $h, $hex) {
  $g.FillPath((New-VGradBrush (New-RectF $x $y $w $h) @($hex, $hex) @(1, 1) @(0, 1)), (New-RoundedRect $x $y $w $h 12))
}

# ---------------------------------------------------------------- config
$T = 0.18
if ($env:QL_TONE) { $T = [double]$env:QL_TONE }
$MID = Mix $BRAND '#FFFFFF' $T
Write-Output ("brand {0} + {1:P0} white -> container mid {2}" -f $BRAND, $T, $MID)

$OPT = New-Spec @{ mid = $MID } $null
$OPT_INK = New-Spec @{ mid = $MID; shell = $false; ink = $MID } $null   # monochrome, no container
# small-size optical compensation: the ring and the tick would fuse at <=24 px, so trade
# opacity contrast for weight contrast and drop the hairline.
$OPT_SMALL = New-Spec $OPT @{ ring = 0.85; ringW = 5.0; checkW = 9.0; hairline = $false }
function Get-ExportSpec([double]$sz, $spec) { if ($sz -le 24) { return (New-Spec $spec $OPT_SMALL) } return $spec }

# ---------------------------------------------------------------- PNG exports
Write-Output 'png/'
foreach ($sz in @(16, 24, 32, 48, 64, 96, 128, 180, 192, 256, 512, 1024)) {
  $cv = New-Canvas $sz $sz $null
  Add-MarkAt $cv.g 0 0 $sz (Get-ExportSpec $sz $OPT)
  Save-Canvas $cv (Join-Path $PNG ("qinglan-{0}.png" -f $sz))
  $cv.g.Dispose(); $cv.bmp.Dispose()
}
# maskable / solid-tile version: glyph on a flat brand field, 80% safe zone
foreach ($sz in @(192, 512)) {
  $cv = New-Canvas $sz $sz $null
  $st = $cv.g.Save()
  $cv.g.ScaleTransform([single]($sz / 64.0), [single]($sz / 64.0)) | Out-Null
  $cv.g.FillRectangle([System.Drawing.SolidBrush]::new((Col $MID 1.0)), [single]0, [single]0, [single]64, [single]64)
  $cv.g.Restore($st) | Out-Null
  Add-MarkAt $cv.g ($sz * 0.16) ($sz * 0.16) ($sz * 0.68) (New-Spec $OPT_INK @{ ring = 0.85; ringW = 5.0; checkW = 9.0 })
  Save-Canvas $cv (Join-Path $PNG ("qinglan-maskable-{0}.png" -f $sz))
  $cv.g.Dispose(); $cv.bmp.Dispose()
}

# ---------------------------------------------------------------- check sheets
# sheet 1: lightness ladder
$TONES = [ordered]@{}
foreach ($t in @(0.0, 0.12, 0.18, 0.26)) {
  $TONES[("tint {0:P0}" -f $t)] = New-Spec @{ mid = (Mix $BRAND '#FFFFFF' $t) } $null
}
$names = @($TONES.Keys)
$cv = New-Canvas 1320 760 '#F3F3F3'; $g = $cv.g
$fam = New-Object System.Drawing.FontFamily('Microsoft YaHei')
$lf = [System.Drawing.Font]::new($fam, 13)
$lb = [System.Drawing.SolidBrush]::new((Col '#333333' 1))
$lb2 = [System.Drawing.SolidBrush]::new((Col '#767676' 1))
for ($i = 0; $i -lt $names.Count; $i++) {
  $spec = $TONES[$names[$i]]
  $x = 40 + ($i % 2) * 640; $y = 70 + [math]::Floor($i / 2) * 330
  Plate $g $x $y 620 300 '#FFFFFF'
  Add-MarkAt $g ($x + 26) ($y + 42) 190 $spec
  $g.DrawString([string]$names[$i], $lf, $lb, [single]($x + 6), [single]($y - 26))
  $g.DrawString([string]('mid ' + $spec.mid), $lf, $lb2, [single]($x + 250), [single]($y + 210))
  $sx = $x + 250
  foreach ($sz in @(16, 24, 32, 48, 64)) { Add-MarkAt $g $sx ($y + 60 - $sz / 2) $sz (Get-ExportSpec $sz $spec); $sx += $sz + 18 }
  $sx = $x + 250
  foreach ($sz in @(16, 24, 32, 48, 64)) { Add-MarkAt $g $sx ($y + 150 - $sz / 2) $sz (Get-ExportSpec $sz $spec); $sx += $sz + 18 }
}
Save-Canvas $cv (Join-Path $CHK 'ladder.png') | Out-Null
$g.Dispose(); $cv.bmp.Dispose()

# sheet 2: real surfaces - light card, dark chrome, acrylic header, lockup
$cv = New-Canvas 1264 560 '#F3F3F3'; $g = $cv.g
Plate $g 40 40 380 190 '#FFFFFF'; Plate $g 440 40 380 190 '#1B1B1B'; Plate $g 840 40 384 190 '#293138'
$x = 62; foreach ($sz in @(16, 24, 32, 48, 64, 88)) { Add-MarkAt $g $x (135 - $sz / 2) $sz (Get-ExportSpec $sz $OPT); $x += $sz + 20 }
$x = 462; foreach ($sz in @(16, 24, 32, 48, 64, 88)) { Add-MarkAt $g $x (135 - $sz / 2) $sz (Get-ExportSpec $sz $OPT); $x += $sz + 20 }
$x = 862; foreach ($sz in @(16, 24, 32, 48, 64, 88)) { Add-MarkAt $g $x (135 - $sz / 2) $sz (Get-ExportSpec $sz $OPT); $x += $sz + 20 }
# acrylic header mock
$g.FillPath((New-VGradBrush (New-RectF 40 260 1184 150) @('#EAF4FB', '#D3E8F8') @(1, 1) @(0, 1)), (New-RoundedRect 40 260 1184 150 12))
Add-MarkAt $g 66 288 96 $OPT
Add-MarkAt $g 190 306 60 $OPT
Add-MarkAt $g 268 316 40 $OPT
Add-MarkAt $g 322 322 28 (Get-ExportSpec 28 $OPT)
Add-MarkAt $g 364 326 20 (Get-ExportSpec 20 $OPT)
$QL = -join (0x9752, 0x84DD | ForEach-Object { [char]$_ })
$g.DrawString([string]$QL, [System.Drawing.Font]::new($fam, 32, [System.Drawing.FontStyle]::Bold),
  [System.Drawing.SolidBrush]::new((Col '#1B5E8C' 1)), [single]410, [single]296)
$g.DrawString([string]'QingLan OJ', $lf, $lb2, [single]414, [single]348)
Add-MarkAt $g 900 288 96 $OPT_INK
Save-Canvas $cv (Join-Path $CHK 'surfaces.png') | Out-Null
$g.Dispose(); $cv.bmp.Dispose()

# sheet 3: small-size optical candidates, drawn at true px then blown up x6
$SMALL = [ordered]@{
  'S0 alpha only'  = New-Spec $OPT @{ ring = 0.85; ringW = 6.5; checkW = 6.5; hairline = $false }
  'S1 weight'      = New-Spec $OPT @{ ring = 0.85; ringW = 5.0; checkW = 9.0; hairline = $false }
  'S2 weight+geo'  = New-Spec $OPT @{ ring = 0.9; ringW = 4.5; checkW = 9.5; hairline = $false; rr = 11.5; cx = 30.5; cy = 35.5 }
}
$cv = New-Canvas 300 150 '#FFFFFF'; $g = $cv.g
$rowI = 0
foreach ($k in $SMALL.Keys) {
  $x = 10
  foreach ($sz in @(16, 20, 24, 32)) { Add-MarkAt $g $x (10 + $rowI * 50 + (32 - $sz) / 2) $sz $SMALL[$k]; $x += $sz + 20 }
  $rowI++
}
Save-Canvas $cv (Join-Path $CHK 'small-cands.png') | Out-Null
$g.Dispose(); $cv.bmp.Dispose()
$b = New-Object System.Drawing.Bitmap((Join-Path $CHK 'small-cands.png'))
$big = [System.Drawing.Bitmap]::new(($b.Width * 6), ($b.Height * 6))
$gg = [System.Drawing.Graphics]::FromImage($big)
$gg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$gg.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$gg.DrawImage($b, 0, 0, $big.Width, $big.Height); $gg.Dispose(); $b.Dispose()
$big.Save((Join-Path $CHK 'small-cands-x6.png'), [System.Drawing.Imaging.ImageFormat]::Png); $big.Dispose()
Write-Output '  small-cands rows: S0 alpha only / S1 weight / S2 weight+geo'

# ---------------------------------------------------------------- contrast report
function Lum([string]$hex) {
  $c = [System.Drawing.ColorTranslator]::FromHtml($hex)
  $f = { param($v) $s = $v / 255.0; if ($s -le 0.03928) { $s / 12.92 } else { [Math]::Pow((($s + 0.055) / 1.055), 2.4) } }
  return 0.2126 * (& $f $c.R) + 0.7152 * (& $f $c.G) + 0.0722 * (& $f $c.B)
}
function Ratio([string]$x, [string]$y) {
  $l1 = Lum $x; $l2 = Lum $y; if ($l1 -lt $l2) { $t = $l1; $l1 = $l2; $l2 = $t }
  return [math]::Round((($l1 + 0.05) / ($l2 + 0.05)), 2)
}
function Over($fgHex, $a, $bgHex) {
  $f = [System.Drawing.ColorTranslator]::FromHtml($fgHex); $b = [System.Drawing.ColorTranslator]::FromHtml($bgHex)
  '#' + (([System.Drawing.Color]::FromArgb(255,
    [int][math]::Round($f.R * $a + $b.R * (1 - $a)),
    [int][math]::Round($f.G * $a + $b.G * (1 - $a)),
    [int][math]::Round($f.B * $a + $b.B * (1 - $a)))).Name -replace '^ff', '')
}
Write-Output 'contrast (non-text target 3.0):'
foreach ($name in @($TONES.Keys)) {
  $m = $TONES[$name].mid
  Write-Output ("  {0,-10} mid={1}  solid white/mid={2}  ring@55/mid={3}  mid/page={4}  mid/dark={5}" -f `
      $name, $m, (Ratio '#FFFFFF' $m), (Ratio (Over '#FFFFFF' 0.55 $m) $m), (Ratio $m '#F3F3F3'), (Ratio $m '#1B1B1B'))
}
$r = Ramp $MID
Write-Output ("svg ramp for {0}: {1}" -f $MID, ($r.hexes -join ' -> '))
