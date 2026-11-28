@echo off
setlocal EnableExtensions
rem PepeMarketWizard 1.33 - Pepe Data ^& Training Studio (osobna aplikacja: wlasny proces, port z ustawien - domyslnie 8780, folder data_studio).
rem Eksport -> walidacja -> dataset -> trening -> test loadera -> przekazanie do bota (kandydat SHADOW). Studio NIE wysyla zlecen.
rem Zalecane: PepeTrainingStudio.exe (okno). Ten skrypt uruchamia ten sam serwer i otwiera przegladarke.
cd /d "%~dp0"
chcp 65001 >nul
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
call "%ROOT%\tools\pmwpy.cmd"
if not exist "%PY%" (echo [BLAD] Brak Pythona bota (.venv albo runtime aplikacji) - uruchom INSTALUJ_TRENING.bat albo raz aplikacje Apollo23 - PepeMarketWizard.exe & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "MQ_STUDIO_DATA_DIR=%~dp0data_studio"
rem 1.46: bez MQ_BOT_DATA_DIR - Studio znajduje folder danych bota ta sama regula co bot: folder data programu, a obok
rem PepeMarketWizardDesktop.exe folder LOCALAPPDATA\PepeMarketWizard\data. Pole bot_data_dir w ustawieniach Studio ma pierwszenstwo.
set "MASTERQUO_DATA_DIR=%~dp0data_studio"
pushd "%~dp0backend"
rem 1.46: przegladarka na porcie z ustawien Studio - plik data_studio\settings.json - a 8780 tylko gdy odczyt sie nie uda
set "PORT="
for /f "usebackq delims=" %%P in (`call "%PY%" -m masterquo.studio.settings 2^>nul`) do set "PORT=%%P"
if not defined PORT set "PORT=8780"
start "" "http://127.0.0.1:%PORT%/"
"%PY%" -m masterquo studio
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
