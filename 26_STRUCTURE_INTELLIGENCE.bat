@echo off
rem PepeMarketWizard - Structure Intelligence (PMW-UPD-07). Dane, kalibracja na dev, trening rodzin, raport.
rem Nie wysyla zlecen, nie zmienia Execution Lock, nie wybiera modelu automatycznie (SHADOW tylko recznie).
setlocal
chcp 65001 >nul
title PepeMarketWizard - Structure Intelligence
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" (echo [BLAD] Brak .venv - uruchom INSTALUJ_TRENING.bat & pause & exit /b 2)
set "PYTHONIOENCODING=utf-8"
set "ASSET=%~1"
if "%ASSET%"=="" set "ASSET=XAUUSD"
:menu
echo.
echo === Structure Intelligence (%ASSET%) ===
echo  1. Audyt (eksport, datasety, profil wskaznikow, rejestr)
echo  2. Dataset STRUCTURE_MOVE_M1_V1 z najnowszego eksportu REAL_USER_DATA
echo  3. Dataset SCALP_STRUCTURE_CONTEXT_V1 (tylko rzeczywiste setupy strategii)
echo  4. Kalibracja wskaznikow (tylko czesc dev)
echo  5. Trening ruchu - standard (LOGREG, XGB, ResNeXt, SEW, SEW-EB)
echo  6. Trening ruchu - quick (niepelny smoke)
echo  7. Raport ostatniego runu
echo  8. Replay SHADOW (ogon dev, holdout nieotwierany)
echo 10. Neutralizacja ROC20 - diagnostyka (PMW-UPD-08)
echo 11. Eksperyment MQ_NEUTRAL_REACTION_V1 (LOGREG/XGB)
echo 12. Operatory SEW ADD/AND/IAND (standard)
echo 13. Replay archiwum tickow (Newtonian Bid/Ask)
echo 14. Eksperyment MQ_QUOTE_CONTEXT_REACTION_V1 (wymaga tickow)
echo 15. Kalibracja rezim/SMMA/Z/struktura (tylko dev) (PMW-UPD-09)
echo 16. SpikingBrain BAR_EVENT_V1 HYBRID (standard)
echo 17. SpikingBrain QUOTE_EVENT_V1 HYBRID (wymaga archiwum tickow)
echo 18. MiniRocket V2 + ridge (standard)
echo 19. MiniRocket parytet (fixture sktime 1.2.0)
echo 20. Benchmark CPU (SpikingBrain + MiniRocket)
echo 21. MiniRocket: eksport fixture dla self-testu MQL5
echo  9. Zmien aktywo (XAUUSD / BTC)
echo  0. Wyjscie
set "C="
set /p "C=Wybor: "
pushd "%ROOT%\backend"
if "%C%"=="1" "%PY%" -m masterquo structure-intelligence audit --asset %ASSET%
if "%C%"=="2" "%PY%" -m masterquo structure-intelligence dataset --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1
if "%C%"=="3" "%PY%" -m masterquo structure-intelligence dataset --asset %ASSET% --latest --task SCALP_STRUCTURE_CONTEXT_V1
if "%C%"=="4" "%PY%" -m masterquo structure-intelligence calibrate-indicators --asset %ASSET% --latest
if "%C%"=="5" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --profile standard
if "%C%"=="6" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --profile quick
if "%C%"=="7" "%PY%" -m masterquo structure-intelligence report --asset %ASSET% --latest
if "%C%"=="8" "%PY%" -m masterquo structure-intelligence replay --asset %ASSET% --latest --mode shadow
if "%C%"=="10" "%PY%" -m masterquo structure-intelligence neutralize --asset %ASSET% --latest --signal ROC20
if "%C%"=="11" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_NEUTRAL_REACTION_V1 --families LOGREG,XGB --profile standard
if "%C%"=="12" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SEW_RESNET1D_V2,MQ_SEW_RESNEXT_EB_V1 --sew-operators ADD,AND,IAND --profile standard
if "%C%"=="13" "%PY%" -m masterquo structure-intelligence tick-replay --asset %ASSET% --latest
if "%C%"=="14" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_QUOTE_CONTEXT_REACTION_V1 --families LOGREG,XGB --profile standard
if "%C%"=="15" "%PY%" -m masterquo structure-intelligence calibrate-indicators --asset %ASSET% --latest --profiles MQ_REGIME_MULTI_V2,STRUCTURE_CAUSAL_V2,MQ_SMMA_HL3_V2,MQ_ZSCORE_V2
if "%C%"=="16" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FINANCE_V1 --encoder BAR_EVENT_V1 --attention HYBRID --profile standard
if "%C%"=="17" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FINANCE_V1 --encoder QUOTE_EVENT_V1 --attention HYBRID --profile standard
if "%C%"=="18" "%PY%" -m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_MINIROCKET_RIDGE_V2 --transform MQ_MINIROCKET_UNIVARIATE_V2 --profile standard
if "%C%"=="19" "%PY%" -m masterquo structure-intelligence minirocket parity --reference-version sktime==1.2.0
if "%C%"=="20" "%PY%" -m masterquo structure-intelligence benchmark --families MQ_SPIKE_BRAIN_FINANCE_V1,MQ_MINIROCKET_RIDGE_V2 --profile cpu
if "%C%"=="21" "%PY%" -m masterquo structure-intelligence minirocket export-fixture --output "%ROOT%\exports\minirocket_fixture"
popd
if "%C%"=="9" (if /i "%ASSET%"=="XAUUSD" (set "ASSET=BTC") else (set "ASSET=XAUUSD"))
if "%C%"=="0" exit /b 0
goto menu
