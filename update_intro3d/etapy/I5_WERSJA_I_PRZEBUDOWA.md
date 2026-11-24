# I5 – Wersja i przebudowa aplikacji

## Wersja
| Sytuacja (I0) | Wersja |
|---|---|
| A – wydanie 1.42.x już zbudowane | następna poprawka (np. **1.42.1** albo **1.42.2**, jeśli 1.42.1 zajęte przez CHARTS) |
| A′ – pełny pakiet w trakcie | bez nowej wersji – wydanie robi Z1 pełnego pakietu; tu **nie budujesz** |
| B – opcja (2) | **1.41.1** (lub następna wolna) |

Wersję ustaw w: `APP_VERSION`, `tools/build_release.py`, `tools/build_desktop.py` (jeśli ma), `desktop/winres/winres.json`, `frontend/package.json` (jeśli wersjonowany).

## CHANGELOG
„Nowa animacja startowa 3D”: trzy postacie wyłaniają się z ciemności, środkowa w czerwonej kominiarce; zatrzymują się w połowie drogi; pojawiają się planety FOREX, CRYPTO, OTC; dłoń na planetach; przejście do menu. Scena 3D w czasie rzeczywistym (three.js 0.187.0), bez plików wideo. Film `intro.mp4` przeniesiony do archiwum. Bez zmian: silnik MT5, strategie, modele.

## Przebudowa (narzędziami projektu)
1. `cd frontend && npm ci && npm run build`
2. `tools/run_tests.py`; wynik testu 1:1 z I4
3. `python tools/build_release.py`
4. `python tools/build_desktop.py` (nowy `PepeMarketWizardDesktop.exe` z wersją w zasobach)
5. `python tools/verify_release.py` dla obu paczek
6. Brak Go ≥ 1.23 lub sieci → zatrzymaj się i napisz, czego brakuje.

`update_intro3d/` i `archive/` nie wchodzą do paczek. `__PMW_TEST__` nie występuje w `frontend/dist`.
