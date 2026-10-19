@echo off
rem PepeMarketWizard - moduly IQ Gold Gann / IQ Star Lines / PAL02M / Parabolic SAR (PMW-UPD-02).
rem Kolejnosc: gotowosc zrodel -> rejestracja (dziala w bocie) -> zbior -> kalibracja SAR -> trening -> raport.
rem Nie wysyla zlecen, nie zmienia Execution Lock, nowe modele tylko SHADOW (aktywacja recznie w panelu).
setlocal
title PepeMarketWizard - moduly IQ / PAL / SAR
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
for %%C in (status record dataset calibrate-sar train) do (
  echo.
  echo === indicator-context %%C ===
  call "%~dp0tools\ic.cmd" %%C --asset %ASSET%
)
echo.
echo Raport: panel Modele i trening - karta Moduly IQ / PAL / SAR (albo data\indicator_context\%ASSET%\runs).
pause
exit /b 0
