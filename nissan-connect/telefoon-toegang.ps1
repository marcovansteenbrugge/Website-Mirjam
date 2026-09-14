# Maakt de Ariya-app bereikbaar vanaf je telefoon, op je eigen wifi.
#
#     powershell -ExecutionPolicy Bypass -File .\telefoon-toegang.ps1
#
# Weer dichtzetten:
#     powershell -ExecutionPolicy Bypass -File .\telefoon-toegang.ps1 -Verwijderen
#
# Dit vraagt om beheerdersrechten, want er komt een firewallregel bij. Die regel
# geldt alleen voor je thuisnetwerk, niet voor openbare wifi.

param([switch]$Verwijderen)

$ErrorActionPreference = "Stop"
$regelNaam = "Ariya-app (poort 8000, thuisnetwerk)"

# --- Beheerdersrechten: zichzelf opnieuw starten indien nodig ---------------
$ikBenBeheerder = ([Security.Principal.WindowsPrincipal]`
    [Security.Principal.WindowsIdentity]::GetCurrent()`
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $ikBenBeheerder) {
    Write-Host "Beheerdersrechten nodig voor de firewallregel; Windows vraagt het zo." -ForegroundColor Yellow
    $args = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($Verwijderen) { $args += " -Verwijderen" }
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

# --- Weer dichtzetten -------------------------------------------------------
if ($Verwijderen) {
    $bestaand = Get-NetFirewallRule -DisplayName $regelNaam -ErrorAction SilentlyContinue
    if ($bestaand) {
        $bestaand | Remove-NetFirewallRule
        Write-Host "`nDe firewallregel is verwijderd. Je telefoon kan er niet meer bij." -ForegroundColor Green
    } else {
        Write-Host "`nEr stond geen regel open; er viel niets te verwijderen." -ForegroundColor Yellow
    }
    Read-Host "`nDruk op Enter om te sluiten"
    exit
}

# --- Netwerkprofiel controleren --------------------------------------------
# Een regel voor het prive-profiel doet niets als Windows dit netwerk als
# openbaar ziet. Dat is precies het geval waarin mensen denken dat het stuk is.
$profielen = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne "Disconnected" }
$openbaar  = $profielen | Where-Object { $_.NetworkCategory -eq "Public" }

if ($openbaar -and -not ($profielen | Where-Object { $_.NetworkCategory -eq "Private" })) {
    Write-Host ""
    Write-Host "Let op: Windows ziet dit netwerk als OPENBAAR." -ForegroundColor Yellow
    Write-Host "Een regel voor het thuisnetwerk werkt dan niet. Het betreft:"
    Write-Host ""
    foreach ($p in $openbaar) {
        Write-Host ("  - {0}  (via {1})" -f $p.Name, $p.InterfaceAlias)
    }
    Write-Host ""
    Write-Host "Omzetten kan hier meteen, of via Instellingen > Netwerk en internet"
    Write-Host "> Ethernet (of Wi-Fi) > Netwerkprofieltype: Prive."
    Write-Host ""
    $antwoord = Read-Host "Nu omzetten naar Prive? (j/n)"
    if ($antwoord -match '^[jJyY]') {
        try {
            $openbaar | Set-NetConnectionProfile -NetworkCategory Private
            Write-Host "`nOmgezet naar Prive. Het script gaat verder." -ForegroundColor Green
            Start-Sleep -Seconds 2
        } catch {
            Write-Host "`nOmzetten mislukt: $($_.Exception.Message)" -ForegroundColor Red
            Read-Host "`nDruk op Enter om te sluiten"
            exit 1
        }
    } else {
        Write-Host "`nNiets gewijzigd. Draai dit script opnieuw zodra het netwerk op Prive staat."
        Read-Host "`nDruk op Enter om te sluiten"
        exit 1
    }
}

# --- Firewallregel ----------------------------------------------------------
if (Get-NetFirewallRule -DisplayName $regelNaam -ErrorAction SilentlyContinue) {
    Write-Host "De firewallregel bestond al." -ForegroundColor Green
} else {
    New-NetFirewallRule -DisplayName $regelNaam `
        -Direction Inbound -Protocol TCP -LocalPort 8000 `
        -Profile Private -Action Allow | Out-Null
    Write-Host "Firewallregel aangemaakt (alleen thuisnetwerk)." -ForegroundColor Green
}

# --- Adres van deze pc opzoeken --------------------------------------------
$config = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
    Select-Object -First 1
$ip = $config.IPv4Address.IPAddress

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
if ($ip) {
    Write-Host "  Op je telefoon, op dezelfde wifi, ga je naar:"
    Write-Host ""
    Write-Host "      http://$ip`:8000" -ForegroundColor Green
} else {
    Write-Host "  Geen netwerkadres gevonden. Zit deze pc wel op wifi of" -ForegroundColor Yellow
    Write-Host "  aan de kabel?"
}
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Je hebt daar eenmalig hetzelfde app-token nodig."
Write-Host ""
Write-Host "  Tip: in je telefoonbrowser kun je de pagina aan je"
Write-Host "  beginscherm toevoegen. Hij opent dan schermvullend,"
Write-Host "  zonder adresbalk, als een gewone app."
Write-Host ""
Write-Host "  Let op: dit werkt alleen thuis en alleen als deze"
Write-Host "  laptop aanstaat en wakker is."
Write-Host ""
Read-Host "Druk op Enter om te sluiten"
