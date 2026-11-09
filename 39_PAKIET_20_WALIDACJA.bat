@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title PepeMarketWizard - pakiet 20 strategii SC/HG: replay i walidacja
rem 1.38: replay walk-forward 20 wariantow (PMW_SC01-SC10, PMW_HG01-HG10) na historii MT5 eksportowanej przez centrum treningu.
rem Te same detektory, solver TP1/TP2 i polityki hedge co w bocie. Werdykt VALIDATED tylko na REAL_USER_DATA ze znana prowizja,
rem >= 200 planow OOS, >= 3 odcinkach dodatnich i dodatniej dolnej granicy bootstrapu. Nic nie jest wysylane do terminala.
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat
  pause
  exit /b 2
)
set "PYTHONIOENCODING=utf-8"
pushd "%ROOT%\backend"
"%PY%" -m masterquo training run --instruments XAUUSD --profile PELNY_TRENING --tasks sh_pack
popd
pause
