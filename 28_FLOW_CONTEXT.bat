@echo off
rem PepeMarketWizard - Flow context (PMW-UPD-11): Markov 3-stanowy i koszyki, Heikin Flow, kanaly S/R, StopDistance.
rem Kalibracja i Markov tylko na czesci dev; holdout wylacznie evaluate-holdout; SHADOW recznie; brak zlecen i zmian Execution Lock.
setlocal EnableDelayedExpansion
chcp 65001 >nul
title PepeMarketWizard - Flow context
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Flow context (%ASSET%) ===
echo  1. Audyt (eksport, profil, rejestr)
echo  2. Kalibracja profili Heikin / S-R / StopDistance (tylko dev)
echo  3. Dopasuj Markov3 + koszyki roznic (tylko dev)
echo  4. Dataset FLOW_CONTEXT_MOVE_M1_V1
echo  5. Trening LOGREG/XGB - standard
echo  6. Trening - quick (niepelny smoke)
echo  7. Raport ostatniego runu (ablacje, NO_VALIDATED_EDGE gdy brak przewagi)
echo  8. Replay SHADOW (ogon dev)
echo  9. Benchmark CPU
echo 10. Parytet native (eksport kolektora + golden)
echo 11. Instalacja + kompilacja wskaznikow MQL5 (MetaEditor)
echo 12. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo flow-context audit --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo flow-context calibrate --asset %ASSET% --latest --modules heikin,sr-channels,stopdistance
if "%C%"=="3" "%PY%" -m masterquo flow-context train-markov --asset %ASSET% --latest --models MQ_MARKOV3_FLOW_V1,MQ_MARKOV_DIFF_FLOW_V1
if "%C%"=="4" "%PY%" -m masterquo flow-context dataset --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1
if "%C%"=="5" "%PY%" -m masterquo flow-context train --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1 --families LOGREG,XGB --profile standard
if "%C%"=="6" "%PY%" -m masterquo flow-context train --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1 --families LOGREG,XGB --profile quick
if "%C%"=="7" "%PY%" -m masterquo flow-context report --asset %ASSET% --latest
if "%C%"=="8" "%PY%" -m masterquo flow-context replay --asset %ASSET% --latest --mode shadow
if "%C%"=="9" "%PY%" -m masterquo flow-context benchmark --profile cpu
if "%C%"=="10" "%PY%" -m masterquo flow-context native-parity
popd
if "%C%"=="11" call :native
if "%C%"=="12" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu

:native
set "DATA="
set /p "DATA=Folder danych terminala (Plik > Otworz folder danych): "
if not exist "%DATA%\MQL5" (echo [BLAD] Brak "%DATA%\MQL5" & exit /b 2)
set "ME=%ProgramFiles%\MetaTrader 5\metaeditor64.exe"
if not exist "%ME%" set /p "ME=Pelna sciezka metaeditor64.exe: "
if not exist "%ME%" (echo [BLAD] NOT_COMPILED_NO_METAEDITOR & exit /b 3)
xcopy /y /i "%ROOT%\mql5\FlowContext\Include\PMW\*.mqh" "%DATA%\MQL5\Include\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\FlowContext\Indicators\*.mq5" "%DATA%\MQL5\Indicators\PMW\" >nul
xcopy /y /i "%ROOT%\mql5\FlowContext\Scripts\*.mq5" "%DATA%\MQL5\Scripts\PMW\" >nul
if not exist "%DATA%\MQL5\Files\PMW" mkdir "%DATA%\MQL5\Files\PMW"
set ERR=0
for %%F in ("%DATA%\MQL5\Indicators\PMW\MQ_*.mq5" "%DATA%\MQL5\Scripts\PMW\MQ_Flow*.mq5") do (
  if exist "%%~dpnF.ex5" del "%%~dpnF.ex5"
  "%ME%" /compile:"%%~F" /inc:"%DATA%\MQL5" /log:"%%~dpnF.log"
  if not exist "%%~dpnF.ex5" (echo [BLAD] brak EX5 dla %%~nxF & set /a ERR+=1) else (echo [OK] %%~nxF)
)
"%PY%" -I "%ROOT%\tools\mr2_native_status.py" "%DATA%" !ERR! "flow" --flow
echo W terminalu: Skrypty ^> PMW ^> MQ_FlowSelfTest, potem MQ_FlowCollector (InpBars=0). Ustaw MQ_MT5_FILES_DIR=%DATA%\MQL5\Files
exit /b 0
