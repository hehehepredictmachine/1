@echo off
rem PepeMarketWizard - Context indicators (PMW-UPD-14): VAMD, bounded Katz FD, Pullback + SMC (BoS/CHoCH/IDM/x), Buffer Inspector.
rem Kalibracja tylko na dev (max 24 konfiguracje), trening SHADOW/OBSERVE, brak zlecen, brak zmian AutoTrading i Execution Lock.
setlocal EnableDelayedExpansion
chcp 65001 >nul
title PepeMarketWizard - Context indicators
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Context indicators (%ASSET%) ===
echo  1. Audyt danych M5 (zrodlo, luki, zegar, koszty)
echo  2. Kalibracja VAMD / FD / SMC (tylko dev, rejestr prob)
echo  3. Replay SHADOW (zdarzenia, strefy, udzial would_block)
echo  4. Dataset CONTEXT_MOVE_M5_V1
echo  5. Trening LOGREG/XGB + ablacje - standard
echo  6. Trening - quick (niepelny smoke)
echo  7. Weryfikacja raportu Buffer Inspector (MQL5\Files\PMW\PWM_BUFFER_REPORT.json)
echo  8. Parytet native (eksport PWM_ContextSelfTest + golden)
echo  9. Instalacja + kompilacja MQL5 (MetaEditor64, kopia zapasowa)
echo 10. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo context-indicators audit --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo context-indicators calibrate --asset %ASSET%
if "%C%"=="3" "%PY%" -m masterquo context-indicators replay --asset %ASSET%
if "%C%"=="4" "%PY%" -m masterquo context-indicators dataset --asset %ASSET%
if "%C%"=="5" "%PY%" -m masterquo context-indicators train --asset %ASSET% --families LOGREG,XGB --profile standard
if "%C%"=="6" "%PY%" -m masterquo context-indicators train --asset %ASSET% --families LOGREG,XGB --profile quick
if "%C%"=="7" call :report
if "%C%"=="8" "%PY%" -m masterquo context-indicators native-parity
popd
if "%C%"=="9" call :native
if "%C%"=="10" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu

:report
if "%MQ_MT5_FILES_DIR%"=="" (echo [INFO] Ustaw MQ_MT5_FILES_DIR=^<Folder danych^>\MQL5\Files & exit /b 0)
"%PY%" -m masterquo context-indicators buffers-verify --report "%MQ_MT5_FILES_DIR%\PMW\PWM_BUFFER_REPORT.json"
exit /b 0

:native
echo Foldery danych terminali (MQL5):
for /d %%T in ("%APPDATA%\MetaQuotes\Terminal\*") do if exist "%%~fT\MQL5" echo   %%~fT
set "DATA="
set /p "DATA=Folder danych terminala (Plik > Otworz folder danych): "
if not exist "%DATA%\MQL5" (echo [BLAD] Brak "%DATA%\MQL5" & exit /b 2)
set "ME="
for %%P in ("%ProgramFiles%\MetaTrader 5\metaeditor64.exe" "%ProgramFiles%\MetaTrader 5 Terminal\metaeditor64.exe") do if exist "%%~fP" set "ME=%%~fP"
if "%ME%"=="" for /d %%D in ("%ProgramFiles%\*") do if exist "%%~fD\metaeditor64.exe" set "ME=%%~fD\metaeditor64.exe"
if "%ME%"=="" set /p "ME=Pelna sciezka metaeditor64.exe: "
if not exist "%ME%" (echo [BLAD] NOT_EXECUTED_METAEDITOR_UNAVAILABLE - zrodla w mql5\ContextIndicators, skopiuj recznie i skompiluj w MetaEditorze & exit /b 3)
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "(Get-Item '%ME%').VersionInfo.FileVersion"`) do set "MEVER=%%V"
echo MetaEditor: %ME%  wersja: %MEVER%
set "BK=%DATA%\MQL5\PMW_backup_%RANDOM%%RANDOM%"
mkdir "%BK%" >nul 2>&1
for %%F in ("%DATA%\MQL5\Include\PMW\PMW_ContextCore.mqh" "%DATA%\MQL5\Indicators\PMW\PWM_*.mq5" "%DATA%\MQL5\Scripts\PMW\PWM_*.mq5") do if exist "%%~fF" copy /y "%%~fF" "%BK%\" >nul
echo Kopia zapasowa poprzednich plikow: %BK%
xcopy /y /i "%ROOT%\mql5\ContextIndicators\Include\PMW\*.mqh" "%DATA%\MQL5\Include\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\ContextIndicators\Indicators\*.mq5" "%DATA%\MQL5\Indicators\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\ContextIndicators\Scripts\*.mq5" "%DATA%\MQL5\Scripts\PMW\" >nul
if not exist "%DATA%\MQL5\Files\PMW" mkdir "%DATA%\MQL5\Files\PMW"
set ERR=0
for %%F in ("%DATA%\MQL5\Indicators\PMW\PWM_*.mq5" "%DATA%\MQL5\Scripts\PMW\PWM_*.mq5") do (
  if exist "%%~dpnF.ex5" del "%%~dpnF.ex5"
  "%ME%" /compile:"%%~F" /inc:"%DATA%\MQL5" /log:"%%~dpnF.log"
  echo   exit=!errorlevel! log=%%~dpnF.log
  if not exist "%%~dpnF.ex5" (echo [BLAD] brak EX5 dla %%~nxF & set /a ERR+=1) else (echo [OK] %%~nxF)
)
"%PY%" -I "%ROOT%\tools\mr2_native_status.py" "%DATA%" !ERR! "context %MEVER%" --context
pushd "%ROOT%\backend"
"%PY%" -m masterquo context-indicators export-fixture --files-dir "%DATA%\MQL5\Files"
popd
echo W terminalu: Skrypty ^> PMW ^> PWM_ContextSelfTest, potem opcja 8 (parytet). Inspector: Skrypty ^> PMW ^> PWM_BufferInspector.
echo Ustaw MQ_MT5_FILES_DIR=%DATA%\MQL5\Files. Instalacja nie zmienia AutoTrading i nie uruchamia handlu.
exit /b 0
