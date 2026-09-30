$ErrorActionPreference = 'Continue'
"LanguageMode: " + $ExecutionContext.SessionState.LanguageMode
Add-Type -AssemblyName PresentationCore
$t = [Type]::GetType('System.Windows.Media.SolidBrush, PresentationCore, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35')
if ($t) { 'WPF AQT resolve: ok' } else { 'WPF AQT resolve: null' }
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(32, 32, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(115, 255, 255, 255), 6.5)
$pen.StartCap = [System.Drawing.Drawing2D.LineCap]::RoundCap
$pen.EndCap = [System.Drawing.Drawing2D.LineCap]::RoundCap
$pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddLines([System.Drawing.PointF[]]@((New-Object System.Drawing.PointF(10, 10)), (New-Object System.Drawing.PointF(20, 22))))
$g.DrawPath($pen, $path)
$gb = New-Object System.Drawing.Drawing2D.LinearGradientBrush((New-Object System.Drawing.Rectangle(0, 0, 32, 32)), [System.Drawing.Color]::Blue, [System.Drawing.Color]::Black, [System.Drawing.Drawing2D.LinearGradientMode]::Vertical)
$cb = New-Object System.Drawing.Drawing2D.ColorBlend
$cb.Count = 3
$cb.Colors = [System.Drawing.Color[]]@([System.Drawing.Color]::White, [System.Drawing.Color]::Blue, [System.Drawing.Color]::Black)
$cb.Positions = [double[]]@(0.0, 0.55, 1.0)
$gb.InterpolationColors = $cb
$g.FillRectangle($gb, 0, 0, 8, 8)
$g.Dispose()
$bmp.Save((Join-Path $PSScriptRoot 'check\probe-gdi.png'))
$bmp.Dispose()
'GDI+: ok'
