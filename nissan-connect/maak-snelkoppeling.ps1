# Zet een snelkoppeling "Ariya" op je bureaublad.
#
# Eenmalig draaien:
#     powershell -ExecutionPolicy Bypass -File .\maak-snelkoppeling.ps1
#
# Daarna dubbelklik je op je bureaublad op "Ariya" en start alles vanzelf.

$ErrorActionPreference = "Stop"

$doel = Join-Path $PSScriptRoot "start-ariya.cmd"
if (-not (Test-Path $doel)) {
    Write-Host "start-ariya.cmd niet gevonden naast dit script." -ForegroundColor Red
    Read-Host "`nDruk op Enter om te sluiten"
    exit 1
}

$bureaublad = [Environment]::GetFolderPath("Desktop")
$koppeling  = Join-Path $bureaublad "Ariya.lnk"

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($koppeling)
$s.TargetPath       = $doel
$s.WorkingDirectory = $PSScriptRoot
$s.Description      = "Accu uitlezen en voorverwarmen van de Nissan Ariya"
$s.WindowStyle      = 7          # geminimaliseerd starten; de browser komt naar voren
$s.Save()

Write-Host ""
Write-Host "Klaar. Op je bureaublad staat nu een snelkoppeling 'Ariya'." -ForegroundColor Green
Write-Host ""
Write-Host "Dubbelklikken start de server en opent de pagina."
Write-Host "Het venster dat daarbij opent, stopt de server als je het sluit."
Write-Host ""
Read-Host "Druk op Enter om te sluiten"
