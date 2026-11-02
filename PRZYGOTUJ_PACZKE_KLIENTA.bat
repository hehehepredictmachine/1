@echo off
setlocal
cd /d "%~dp0"
rem OWNER EDITION: przygotowanie paczki CLIENT EDITION dla klienta (KEY FOR MAGIC + sprawdzanie licencji na Twoim serwerze).
rem Uzycie: PRZYGOTUJ_PACZKE_KLIENTA.bat https://licencje.twoja-domena.pl
set "PY="
if exist "%~dp0runtime\python\python.exe" set "PY=%~dp0runtime\python\python.exe"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY (
  echo [BLAD] Brak Pythona programu - uruchom najpierw aplikacje albo 01_INSTALUJ.bat
  pause
  exit /b 1
)
set "URL=%~1"
if "%URL%"=="" set /p URL=Adres serwera licencji (https://...): 
"%PY%" "%~dp0tools\stamp_client_edition.py" --license-url "%URL%" --source "%~dp0."
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo Paczka klienta jest w folderze release\ - przekaz klientowi plik .zip oraz klucz licencji z License Managera.) else (echo Nie udalo sie przygotowac paczki - kod %RC%.)
pause
exit /b %RC%
