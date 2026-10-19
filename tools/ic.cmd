@echo off
rem cienki launcher: python -m masterquo indicator-context <polecenie> (status nie przyjmuje --asset)
setlocal
chcp 65001 >nul
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - INSTALUJ_TRENING.bat & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "CMD=%~1"
pushd "%ROOT%\backend"
if /i "%CMD%"=="status" ("%PY%" -m masterquo indicator-context status) else ("%PY%" -m masterquo indicator-context %*)
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
