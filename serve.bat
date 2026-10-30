@echo off
REM Start FishAgent on the LAN over plain HTTP.
REM
REM Trade-off, recorded deliberately: plain http on a LAN IP is not a secure
REM context, so the browser will not expose geolocation and the service worker
REM never registers. The locate button and PWA install do not work from a phone
REM while this is the entry point. The page says so plainly rather than
REM reporting a permission problem.
REM
REM To get those back, serve TLS instead: serve-https.bat (needs the mkcert CA
REM installed on the phone). See docs/cr03-lan-https-runbook.md.
REM
REM Usage:  serve.bat [port]      (default 8018)

setlocal
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8018"

set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON%" (
  echo [error] Python not found at "%PYTHON%"
  exit /b 1
)

cd /d "%~dp0backend" || exit /b 1

echo Starting FishAgent on http://0.0.0.0:%PORT%/  (Ctrl+C to stop)
"%PYTHON%" -m uvicorn fishagent.main:app ^
  --host 0.0.0.0 ^
  --port %PORT%

endlocal
