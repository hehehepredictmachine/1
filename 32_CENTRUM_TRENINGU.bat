@echo off
rem PepeMarketWizard - Centrum treningu (1.28): eksport MT5 -> dataset -> trening -> ocena -> paczki modeli.
rem Trening NIE aktywuje modelu - aktywacja tylko recznie (panel: Modele i trening - Centrum treningu, albo opcja 6).
rem Zadne zlecenie nie jest wysylane. Wymaga zainstalowanego srodowiska (01_INSTALUJ.bat / INSTALUJ_TRENING.bat).
setlocal
chcp 65001 >nul
title PepeMarketWizard - Centrum treningu
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak srodowiska .venv - uruchom najpierw 01_INSTALUJ.bat
  pause
  exit /b 2
)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
:menu
echo.
echo  1 - Caly proces XAUUSD (eksport przyrostowy, dataset, trening, ocena)
echo  2 - Caly proces BTC
echo  3 - Tylko eksport danych XAUUSD i BTC (przyrostowo, M1/M5/M15/M30)
echo  4 - Lista wersji modeli XAUUSD
echo  5 - Lista wersji modeli BTC
echo  6 - Aktywuj wersje (test zgodnosci i predykcji)
echo  7 - Rodziny modeli 1.33 (lista XAUUSD)
echo  8 - Rodziny modeli 1.33 - trening smoke XAUUSD (wszystkie gotowe)
echo  0 - Koniec
set "CH="
set /p "CH=Wybor: "
pushd "%ROOT%backend"
if "%CH%"=="1" "%PY%" -m masterquo trainhub full --instrument XAUUSD
if "%CH%"=="2" "%PY%" -m masterquo trainhub full --instrument BTC
if "%CH%"=="7" "%PY%" -m masterquo families list --instrument XAUUSD
if "%CH%"=="8" "%PY%" -m masterquo families train-all --instrument XAUUSD --profile smoke
if "%CH%"=="3" "%PY%" -m masterquo trainhub export --instrument XAUUSD
if "%CH%"=="3" "%PY%" -m masterquo trainhub export --instrument BTC
if "%CH%"=="4" "%PY%" -m masterquo trainhub list --instrument XAUUSD
if "%CH%"=="5" "%PY%" -m masterquo trainhub list --instrument BTC
if "%CH%"=="6" call :activate
popd
if "%CH%"=="0" exit /b 0
goto menu
:activate
set "INS="
set "KEY="
set "VER="
set /p "INS=Instrument (XAUUSD/BTC): "
set /p "KEY=Model (np. TH_LOGREG_M5_H6): "
set /p "VER=Wersja: "
"%PY%" -m masterquo trainhub activate --instrument "%INS%" --model-key "%KEY%" --version "%VER%"
exit /b 0
