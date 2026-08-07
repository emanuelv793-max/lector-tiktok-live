$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$workPath = Join-Path $PSScriptRoot (".build-temp\" + [guid]::NewGuid().ToString("N"))
if (-not (Test-Path -LiteralPath $python)) {
    throw "No existe .venv. Crea el entorno e instala requirements.txt primero."
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $workPath `
    --onefile `
    --windowed `
    --name "LectorTikTokLive-Moderno" `
    --icon "$PSScriptRoot\assets\app-icon.ico" `
    --add-data "$PSScriptRoot\assets;assets" `
    --collect-all TikTokLive `
    --collect-all customtkinter `
    --hidden-import win32com.client `
    --collect-all edge_tts `
    --hidden-import comtypes.client `
    "$PSScriptRoot\app.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller no pudo crear el ejecutable (código $LASTEXITCODE)."
}

Write-Host "Ejecutable creado en: $PSScriptRoot\dist\LectorTikTokLive-Moderno.exe"
