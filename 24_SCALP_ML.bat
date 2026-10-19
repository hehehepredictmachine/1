@echo off
rem PepeMarketWizard - Scalp ML: P(dodatni wynik netto cyklu) + net_R, XGBoost LONG/SHORT (PMW-UPD-03).
rem Nie wysyla zlecen, nie zmienia Execution Lock. Nowy model nigdy nie jest wybierany automatycznie (OBSERVE / SHADOW_GATE recznie).
setlocal
chcp 65001 >nul
title PepeMarketWizard - Scalp ML
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Scalp ML (%ASSET%) ===
echo  1. Diagnostyka (doctor)
echo  2. Status (probki, runy, wybrane modele)
echo  3. Przygotuj dane (replay kandydatow z ostatniego eksportu REAL_USER_DATA)
echo  4. Trenuj i ocen (walk-forward + jednorazowy holdout, bez aktywacji)
echo  5. Raport ostatniego runu
echo  6. Rollback wyboru BUY
echo  7. Rollback wyboru SELL
echo  8. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo ml-scalp doctor --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo ml-scalp status --asset %ASSET%
if "%C%"=="3" "%PY%" -m masterquo ml-scalp prepare --asset %ASSET%
if "%C%"=="4" "%PY%" -m masterquo ml-scalp train --asset %ASSET% --activate none
if "%C%"=="5" "%PY%" -m masterquo ml-scalp report --asset %ASSET% --latest
if "%C%"=="6" "%PY%" -m masterquo ml-scalp rollback --asset %ASSET% --side BUY
if "%C%"=="7" "%PY%" -m masterquo ml-scalp rollback --asset %ASSET% --side SELL
popd
if "%C%"=="8" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu
