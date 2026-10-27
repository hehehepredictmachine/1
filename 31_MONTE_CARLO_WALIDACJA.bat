@echo off
rem PepeMarketWizard - walidacja Monte Carlo P(TP przed SL) na Twoim eksporcie z MT5 (walk-forward z embargo, porownanie z modelem
rem bazowym, kalibracja). Czyta tylko pliki eksportu - nie laczy sie z MT5 i nie wysyla zlecen. Kalibracja staje sie aktywna wylacznie
rem na prawdziwych danych z przewaga nad modelem bazowym; cofniecie: python -m masterquo montecarlo rollback --instrument XAUUSD.
rem Uzycie: przeciagnij folder eksportu na ten plik albo podaj go jako parametr.
setlocal
chcp 65001 >nul
title PepeMarketWizard - walidacja Monte Carlo
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat
  pause
  exit /b 2
)
set "DS=%~1"
if "%DS%"=="" set /p "DS=Folder eksportu (panel AI Neural Lab - Trening - Eksportuj dane z MT5): "
if "%DS%"=="" (
  echo [BLAD] Nie podano folderu eksportu.
  pause
  exit /b 2
)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
pushd "%ROOT%\backend"
"%PY%" -m masterquo montecarlo validate --dataset "%DS%"
set "RC=%ERRORLEVEL%"
popd
echo Kod: %RC%  (0 wykonane - werdykt w raporcie, 1 blad, 2 eksport nie nadaje sie do walidacji)
pause
exit /b %RC%
