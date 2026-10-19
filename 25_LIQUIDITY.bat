@echo off
rem PepeMarketWizard - boksy sesji + heatmapa likwidacji (PMW-UPD-06). OBSERVE: nie wysyla zlecen, nie zmienia Execution Lock.
setlocal
chcp 65001 >nul
title PepeMarketWizard - sesje i heatmapa
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Sesje i heatmapa (%ASSET%) ===
echo  1. Status zrodla heatmapy (klucz, uprawnienia, ostatni snapshot)
echo  2. Odpytaj zrodlo teraz (CoinGlass - wymaga klucza i planu z dostepem do model1)
echo  3. Importuj pliki z data\liquidity\inbox
echo  4. Boksy sesji z ostatniego eksportu historii
echo  5. Ocena B0-B3 (replay, koszty, holdout)
echo  6. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo liquidity status --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo liquidity poll --asset %ASSET%
if "%C%"=="3" "%PY%" -m masterquo liquidity import --asset %ASSET%
if "%C%"=="4" "%PY%" -m masterquo liquidity sessions --asset %ASSET%
if "%C%"=="5" "%PY%" -m masterquo liquidity evaluate --asset %ASSET%
popd
if "%C%"=="6" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu
