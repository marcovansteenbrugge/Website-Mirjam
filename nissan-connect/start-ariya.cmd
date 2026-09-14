@echo off
setlocal
title Ariya - accu en voorverwarmen

rem ---------------------------------------------------------------------
rem  Start de Ariya-app en opent de pagina in je browser.
rem
rem  Dubbelklik dit bestand, of gebruik de snelkoppeling op je bureaublad.
rem  Dit venster sluiten stopt de server.
rem
rem  De server luistert ook op je thuisnetwerk, zodat je telefoon erbij kan.
rem  Dat werkt pas nadat je telefoon-toegang.ps1 eenmalig hebt gedraaid; tot
rem  die tijd houdt de Windows-firewall alles van buiten gewoon tegen.
rem ---------------------------------------------------------------------

cd /d "%~dp0server"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   De omgeving ontbreekt. Draai eerst eenmalig start-windows.ps1
  echo   vanuit de map nissan-connect.
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  echo.
  echo   Het instellingenbestand .env ontbreekt. Draai eerst eenmalig
  echo   start-windows.ps1 vanuit de map nissan-connect.
  echo.
  pause
  exit /b 1
)

rem Draait er al een server? Dan alleen de pagina openen.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
  echo   De server draait al. De pagina wordt geopend.
  start "" "http://localhost:8000"
  timeout /t 2 >nul
  exit /b 0
)

rem Wacht op de achtergrond tot de server luistert en open dan pas de pagina.
rem Te vroeg openen levert een foutpagina op die eruitziet alsof er iets stuk is.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
  "for ($i=0; $i -lt 120; $i++) { try { Invoke-WebRequest -Uri 'http://localhost:8000/' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:8000'; break } catch { Start-Sleep -Milliseconds 500 } }"

echo.
echo   Ariya start op http://localhost:8000
echo   De pagina opent vanzelf zodra de server klaar is.
echo.

rem Het adres van deze pc tonen, voor op de telefoon.
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$c = Get-NetIPConfiguration ^| Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } ^| Select-Object -First 1; if ($c) { $c.IPv4Address.IPAddress }"`) do set LANIP=%%i
if defined LANIP (
  echo   Op je telefoon, op dezelfde wifi:  http://%LANIP%:8000
  echo.
)

echo   Dit venster sluiten stopt de server.
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
