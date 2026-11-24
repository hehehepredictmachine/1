# K7 – Wersja i przebudowa aplikacji

## Wersja

| Sytuacja (z K0) | Wersja |
|---|---|
| Wariant A, wydanie 1.42.0 już zbudowane | **1.42.1** |
| Wariant A, pełny pakiet 1.42.0 w trakcie (ten pakiet zastąpił E3) | bez nowej wersji – wydanie robi etap Z1 pełnego pakietu; tu **nie budujesz** |
| Wariant B, opcja (2) | **1.41.1** |

Wersję ustaw w: `APP_VERSION`, `tools/build_release.py` (`VERSION`), `tools/build_desktop.py` (jeśli ma), `desktop/winres/winres.json`, `frontend/package.json` (jeśli wersjonowany).

## CHANGELOG
Sekcja nowej wersji – „CHARTS 1:1 z wizualizacją”:
- wykres, okna RSI / MACD, Kronos i panel opcji w wyglądzie wizualizacji;
- strategie bota jako wskaźniki w koszykach (FX_SMC, FX_SCALP, FX_HEDGE, S01–S12, SH) z markerami, poziomami i kartą PLAN BOTA; TP3 tylko tam, gdzie strategia go definiuje;
- strefy bota tylko z wybranego TF;
- Session Volume Profile każdej sesji (zgodność z silnikiem 27/27);
- test 1:1 (8 scenariuszy) i test zgodności SVP w zestawie testów;
- bez zmian: wykonanie MT5, strategie, modele. Ekran CHARTS tylko odczytuje dane.

## Przebudowa (narzędziami projektu)
1. `cd frontend && npm ci && npm run build`
2. `tools/run_tests.py` (z testem SVP i testami adapterów); test 1:1 – wynik z K6
3. `python tools/build_release.py` → `release/PepeMarketWizard_<wersja>.zip` (+ `.sha256`, MANIFEST)
4. `python tools/build_desktop.py` → `release/PepeMarketWizard_DESKTOP_<wersja>.zip` z nowym `PepeMarketWizardDesktop.exe` (wersja w zasobach exe)
5. `python tools/verify_release.py` dla obu paczek
6. Brak Go ≥ 1.23 albo sieci → zatrzymaj się i napisz, czego brakuje. Nie podmieniaj exe ręcznie.

`update_charts/` i `archive/` **nie** wchodzą do paczek wydania. Hak `__PMW_TEST__` nie występuje w `frontend/dist`.

## Kryteria K7
- [ ] Obie paczki zbudowane i zweryfikowane; wersja widoczna w aplikacji i w zasobach exe.
- [ ] Wszystkie testy przechodzą.
- [ ] Raport końcowy `update_charts/raport/K7.md` z listą zmienionych plików.
