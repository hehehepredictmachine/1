@echo off
rem PepeMarketWizard - Neural Scalp System (PMW-UPD-04): TCN M1/M5 + kontekst M15/H1, P(TP1/SL/TIMEOUT) i net_R kandydata scalp.
rem Nie wysyla zlecen, nie zmienia Execution Lock. Nowy model nigdy nie jest wybierany automatycznie (OBSERVE / SHADOW_GATE recznie).
setlocal
chcp 65001 >nul
title PepeMarketWizard - Neural Scalp System
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Neural Scalp System (%ASSET%) ===
echo  1. Sprawdz gotowosc (doctor)
echo  2. Przygotuj dane (kandydaci + sekwencje z ostatniego eksportu REAL_USER_DATA)
echo  3. Trenuj kandydata (walk-forward + jednorazowy holdout, bez aktywacji)
echo  4. Status
echo  5. Otworz raport ostatniego runu
echo  6. Przywroc poprzedni wybor (rollback)
echo  7. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo neural-scalp doctor --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo neural-scalp prepare --asset %ASSET% --months 12
if "%C%"=="3" "%PY%" -m masterquo neural-scalp train --asset %ASSET% --manifest latest --activate none
if "%C%"=="4" "%PY%" -m masterquo neural-scalp status --asset %ASSET%
if "%C%"=="5" "%PY%" -m masterquo neural-scalp report --asset %ASSET% --latest
if "%C%"=="6" "%PY%" -m masterquo neural-scalp rollback --asset %ASSET%
popd
if "%C%"=="7" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu
