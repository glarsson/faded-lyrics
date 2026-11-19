# Still-plate lyric video: background picture + bottom ffmpeg showwaves +
# Whisper-timed pop/fade lyrics.
#
# Usage:
#   .\run_eq_with_lyrics.ps1 <picture.png> <track.mp3|wav> [lyrics.txt]
#   .\run_eq_with_lyrics.ps1 -Picture bg.png -Audio song.wav -Lyrics sheet.txt
#
# Optional:
#   -OutDir <dir>     artifact folder (default ./out/<slug>)
#   -Aspect 16:9|9:16 delivery box (default 16:9)
#   -CopyTo <dir>     also copy final_lyrics.mp4 here (e.g. D:\Downloads)
#   -Force            re-extract audio / re-ASR

[CmdletBinding(DefaultParameterSetName = "Positional")]
param(
    [Parameter(Position = 0, ParameterSetName = "Positional")]
    [string]$PicturePos,

    [Parameter(Position = 1, ParameterSetName = "Positional")]
    [string]$AudioPos,

    [Parameter(Position = 2, ParameterSetName = "Positional")]
    [string]$LyricsPos,

    [Parameter(Mandatory = $true, ParameterSetName = "Named")]
    [Alias("Bg", "Image")]
    [string]$Picture,

    [Parameter(Mandatory = $true, ParameterSetName = "Named")]
    [Alias("Track", "Song")]
    [string]$Audio,

    [Parameter(ParameterSetName = "Named")]
    [Alias("Sheet", "Txt")]
    [string]$Lyrics = "",

    [string]$OutDir = "",
    [ValidateSet("16:9", "9:16", "")]
    [string]$Aspect = "16:9",
    [string]$CopyTo = "",
    [double]$VizFrac = 0.16,
    [double]$MarginV = 0.40,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "No python found. Expected $Root\.venv\Scripts\python.exe"
}

if ($PSCmdlet.ParameterSetName -eq "Positional") {
    if (-not $PicturePos -or -not $AudioPos) {
        Write-Host @"
Usage:
  .\run_eq_with_lyrics.ps1 <picture.png> <track.mp3|wav> [lyrics.txt]
  .\run_eq_with_lyrics.ps1 -Picture bg.png -Audio song.wav [-Lyrics sheet.txt]

Options: -OutDir -Aspect 16:9|9:16 -CopyTo <dir> -VizFrac 0.16 -MarginV 0.40 -Force
"@
        exit 2
    }
    $Picture = $PicturePos
    $Audio = $AudioPos
    $Lyrics = $LyricsPos
}

function Resolve-Existing([string]$Path, [string]$Label) {
    if (-not $Path) { throw "Missing $Label path" }
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "No such ${Label}: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$PictureAbs = Resolve-Existing $Picture "picture"
$AudioAbs = Resolve-Existing $Audio "audio"
$LyricsAbs = ""
if ($Lyrics) {
    $LyricsAbs = Resolve-Existing $Lyrics "lyrics"
}

$ext = [System.IO.Path]::GetExtension($AudioAbs).ToLowerInvariant()
if ($ext -notin @(".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")) {
    throw "Audio must be mp3/wav (got $ext)"
}
$imgExt = [System.IO.Path]::GetExtension($PictureAbs).ToLowerInvariant()
if ($imgExt -notin @(".png", ".jpg", ".jpeg", ".webp", ".bmp")) {
    throw "Picture must be an image (got $imgExt)"
}

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location -LiteralPath $Root

$argsList = @(
    "-u", "-m", "faded_lyrics",
    "--audio", $AudioAbs,
    "--picture", $PictureAbs,
    "--aspect", $Aspect,
    "--width", "1920",
    "--height", "1080",
    "--fps", "30",
    "--margin-v", "$MarginV",
    "--viz-frac", "$VizFrac"
)
if ($LyricsAbs) { $argsList += @("--lyrics", $LyricsAbs) }
if ($OutDir) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $outAbs = (Resolve-Path -LiteralPath $OutDir).Path
    $argsList += @("--out-dir", $outAbs)
}
if ($Force) { $argsList += "--force" }

Write-Host "[eq+lyrics] picture  $PictureAbs"
Write-Host "[eq+lyrics] audio    $AudioAbs"
if ($LyricsAbs) { Write-Host "[eq+lyrics] lyrics   $LyricsAbs" }
Write-Host "[eq+lyrics] aspect   $Aspect  viz=$VizFrac  marginV=$MarginV"
Write-Host "[eq+lyrics] python   $Python"

& $Python @argsList
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "[eq+lyrics] FAILED (exit $code)"
    exit $code
}

$final = $null
if ($OutDir) {
    $candidate = Join-Path $OutDir "final_lyrics.mp4"
    if (Test-Path -LiteralPath $candidate) { $final = (Resolve-Path -LiteralPath $candidate).Path }
} else {
    $slugRoot = Join-Path $Root "out"
    if (Test-Path -LiteralPath $slugRoot) {
        $hit = Get-ChildItem -LiteralPath $slugRoot -Recurse -Filter "final_lyrics.mp4" |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($hit) { $final = $hit.FullName }
    }
}

if ($final) {
    Write-Host "[eq+lyrics] PASS -> $final"
    if ($CopyTo) {
        New-Item -ItemType Directory -Force -Path $CopyTo | Out-Null
        $destName = ([System.IO.Path]::GetFileNameWithoutExtension($AudioAbs)) + " - lyrics visualizer.mp4"
        $dest = Join-Path $CopyTo $destName
        Copy-Item -LiteralPath $final -Destination $dest -Force
        Write-Host "[eq+lyrics] copied -> $dest"
    }
} else {
    Write-Host "[eq+lyrics] PASS (could not resolve final_lyrics.mp4 path)"
}
exit 0
