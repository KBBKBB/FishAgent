@echo off
REM Start FishAgent over HTTPS on the LAN.
REM
REM Plain http on a LAN IP is not a secure context: the browser refuses to
REM expose geolocation and the service worker never registers, so the page
REM silently loses both the locate button and PWA install. TLS on this port is
REM what makes those work from a phone, not a nicety.
REM
REM Usage:  serve-https.bat [port]      (default 8018)
REM
REM The certificate is a local mkcert leaf with SANs for localhost, 127.0.0.1
REM and this machine's LAN IP. If the host's IP changes the certificate stops
REM matching, so keep the address fixed or re-issue it.

setlocal
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8018"

set "CERT_DIR=D:\FishAgent\certs"
set "CERT=%CERT_DIR%\fishagent-lan.pem"
set "KEY=%CERT_DIR%\fishagent-lan-key.pem"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON%" (
  echo [error] Python not found at "%PYTHON%"
  exit /b 1
)
if not exist "%CERT%" (
  echo [error] certificate not found: "%CERT%"
  echo         Re-issue it with mkcert; see docs\cr03-lan-https-runbook.md
  exit /b 1
)
if not exist "%KEY%" (
  echo [error] certificate key not found: "%KEY%"
  exit /b 1
)

cd /d "%~dp0backend" || exit /b 1

echo Starting FishAgent on https://0.0.0.0:%PORT%/  (Ctrl+C to stop)
"%PYTHON%" -m uvicorn fishagent.main:app ^
  --host 0.0.0.0 ^
  --port %PORT% ^
  --ssl-certfile "%CERT%" ^
  --ssl-keyfile "%KEY%"

endlocal
