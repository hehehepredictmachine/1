@echo off
rem PepeMarketWizard - PMW Quant Core (1.35): stan, inwentaryzacja modeli, trening meta-modelu z ledgera, pomiary.
rem Trening NIE aktywuje modelu. ASSIST wymaga zwalidowanego modelu i jawnego potwierdzenia (panel albo opcja 8).
rem Zadne zlecenie nie jest wysylane. Wymaga zainstalowanego srodowiska (01_INSTALUJ.bat).
setlocal
chcp 65001 >nul
title PepeMarketWizard - Quant Core
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
echo  1 - Stan Quant Core (tryb, ledger, artefakty; stan na zywo, gdy bot dziala)
echo  2 - Inwentaryzacja modeli (docs\quant\INVENTORY.md)
echo  3 - Inwentaryzacja ze stanem dzialajacego bota
echo  4 - Trening meta-modelu XAUUSD z ledgera (bez aktywacji)
echo  5 - Lista wersji meta-modelu XAUUSD
echo  6 - Pomiary wydajnosci (p50/p95/p99)
echo  7 - Tryb SHADOW (domyslny)
echo  8 - Tryb ASSIST (wymaga zwalidowanego modelu i potwierdzenia)
echo  9 - Tryb OFF
echo  0 - Koniec
set "CH="
set /p "CH=Wybor: "
pushd "%ROOT%backend"
if "%CH%"=="1" "%PY%" -m masterquo quant status
if "%CH%"=="2" "%PY%" -m masterquo quant inventory
if "%CH%"=="3" "%PY%" -m masterquo quant inventory --live
if "%CH%"=="4" "%PY%" -m masterquo quant train --instrument XAUUSD
if "%CH%"=="5" "%PY%" -m masterquo quant list --instrument XAUUSD
if "%CH%"=="6" "%PY%" -m masterquo quant bench
if "%CH%"=="7" "%PY%" -m masterquo quant mode SHADOW
if "%CH%"=="8" call :assist
if "%CH%"=="9" "%PY%" -m masterquo quant mode OFF
popd
if "%CH%"=="0" exit /b 0
goto menu
:assist
set "OK="
set /p "OK=ASSIST moze tylko wstrzymac kandydata (bez zlecen, bez zmiany limitow). Wpisz TAK aby potwierdzic: "
if /i "%OK%"=="TAK" "%PY%" -m masterquo quant mode ASSIST --confirm
exit /b 0
