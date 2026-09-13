# Ariya - accu & voorverwarmen
# Startscript voor Windows PowerShell.
#
# Gebruik: rechtermuisknop op dit bestand -> "Uitvoeren met PowerShell"
# Of in PowerShell:  .\start-windows.ps1
#
# Dit script maakt alles klaar en start de server. De eerste keer duurt het
# een minuut of twee omdat er pakketten gedownload worden.

$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "server")

Write-Host ""
Write-Host "=== Ariya - accu & voorverwarmen ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Is Python aanwezig? -------------------------------------------------
$python = $null
foreach ($kandidaat in @("py", "python", "python3")) {
    try {
        $versie = & $kandidaat --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $versie -match "Python 3\.(\d+)") {
            if ([int]$Matches[1] -ge 10) { $python = $kandidaat; break }
        }
    } catch { }
}

if (-not $python) {
    Write-Host "Python 3.10 of nieuwer is niet gevonden." -ForegroundColor Red
    Write-Host ""
    Write-Host "Installeer Python via https://www.python.org/downloads/"
    Write-Host "Zet tijdens het installeren een vinkje bij 'Add python.exe to PATH'."
    Write-Host "Sluit daarna dit venster en start dit script opnieuw."
    Read-Host "`nDruk op Enter om te sluiten"
    exit 1
}
Write-Host "Python gevonden ($python)." -ForegroundColor Green

# --- 2. Virtuele omgeving ---------------------------------------------------
$pythonExe = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "Eenmalig installeren van de benodigde pakketten..."
    & $python -m venv .venv
    if (-not (Test-Path $pythonExe)) {
        Write-Host "Aanmaken van de omgeving is mislukt." -ForegroundColor Red
        Read-Host "`nDruk op Enter om te sluiten"
        exit 1
    }
    & $pythonExe -m pip install --quiet --upgrade pip
    & $pythonExe -m pip install --quiet -r requirements.txt
    Write-Host "Pakketten geinstalleerd." -ForegroundColor Green
} else {
    Write-Host "Pakketten staan al klaar." -ForegroundColor Green
}

# --- 3. Instellingenbestand -------------------------------------------------
if (-not (Test-Path ".env")) {
    Write-Host "Instellingenbestand aanmaken met een nieuw toegangstoken..."
    $token = & $pythonExe -c "import secrets; print(secrets.token_urlsafe(32))"
    $token = $token.Trim()

    (Get-Content ".env.example") -replace '^APP_TOKEN=$', "APP_TOKEN=$token" |
        Set-Content ".env" -Encoding UTF8

    Write-Host ""
    Write-Host "Je toegangstoken is:" -ForegroundColor Yellow
    Write-Host "  $token" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Dit heb je zo nodig in de webpagina. Het staat ook in server\.env,"
    Write-Host "dus je hoeft het niet te onthouden."
    Write-Host ""
} else {
    Write-Host "Instellingen staan al klaar (server\.env)." -ForegroundColor Green
    $regel = Select-String -Path ".env" -Pattern '^APP_TOKEN=(.+)$'
    if ($regel) {
        Write-Host ""
        Write-Host "Je toegangstoken is:" -ForegroundColor Yellow
        Write-Host "  $($regel.Matches[0].Groups[1].Value)" -ForegroundColor Yellow
        Write-Host ""
    }
}

# --- 4. Draaien we met een echte auto of een nagebootste? -------------------
$mockRegel = Select-String -Path ".env" -Pattern '^MOCK=(.*)$'
$isMock = $true
if ($mockRegel) {
    $waarde = $mockRegel.Matches[0].Groups[1].Value.Trim()
    if ($waarde -eq "0" -or $waarde -eq "false") { $isMock = $false }
}

if ($isMock) {
    Write-Host "Modus: NAGEBOOTSTE AUTO - er gaat niets naar je echte Ariya." -ForegroundColor Cyan
    Write-Host "Wil je de echte auto, zet dan MOCK=0 in server\.env en vul je"
    Write-Host "Nissan-gegevens in."
} else {
    Write-Host "Modus: ECHTE AUTO" -ForegroundColor Magenta
}

# --- 5. Starten -------------------------------------------------------------
Write-Host ""
Write-Host "Server start op http://localhost:8000" -ForegroundColor Green
Write-Host "Open dat adres in je browser. Stoppen doe je met Ctrl+C."
Write-Host ""

Start-Process "http://localhost:8000"
& $pythonExe -m uvicorn app.main:app --port 8000
