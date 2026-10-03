# Downloads the offline Vosk speech model used for wake word + commands.
param(
    [string]$OutDir = "$PSScriptRoot\..\app\models"
)

$ErrorActionPreference = "Stop"

$url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
$name = "vosk-model-small-en-us-0.15"
$target = Join-Path $OutDir $name

if (Test-Path $target) {
    Write-Host "Speech model already present at $target"
    exit 0
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir "vosk-model.zip"

Write-Host "Downloading Vosk speech model (~40 MB) from alphacephei.com ..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

Write-Host "Extracting ..."
Expand-Archive -Path $zip -DestinationPath $OutDir -Force
Remove-Item $zip -Force

if (Test-Path $target) {
    Write-Host "Speech model ready: $target"
} else {
    Write-Error "Extraction did not produce $target"
    exit 1
}
