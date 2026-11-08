# Raport końcowy – PepeMarketWizard 1.36.0 (Main Menu V2 + wieże PEPE$WTC i PEPE$SIGNAL)

**Paczki 1.36.0:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_36_0.zip` (2580 plików, aplikacja Windows) | `f90c866d9e28a281d9a97af763bd4f12f67afc76041e8c400ff3e854a00f3376` |
| `PepeMarketWizard_1_36_0.zip` (1511 plików, folder programu) | `4b8a87c9a274fc7290c59a79fe724a0014e4204a94f91b141c2c4ffed2aa3ade` |

`tools/verify_release.py --all` daje OK dla obu (ścieżki, manifest, sekrety, plik .sha256). Start z rozpakowanej paczki folderowej
(backend demo): wersja 1.36.0, menu z ośmioma wieżami, PEPE$WTC (wykres) i PEPE$SIGNAL ładują się bez błędów strony.
Paczka DESKTOP: `PepeMarketWizardDesktop.exe` i `PepeTrainingStudio.exe` skompilowane krzyżowo (Go, `go test` / `go vet` OK),
zasób wersji 1.36.0.0, Python 3.13.17 dla Windows; uruchomienie na Windows nie było możliwe w środowisku budowania.

**Zakres** (paczki: Menu New V2, PEPE$WTC V4 Zones, PEPE$SIGNAL V1):
* menu główne – stół neuronowy z ośmioma wieżami (PEPE$WTC, PEPE$SIGNAL, PEPE$BANK, PEPE$ROI, STRATEGIES, MARKET NEWS, TRAINING LAB, SETTINGS),
  małe logo, nawigacja na górze, bez paneli i przycisków na dole (2.5D);
* PEPE$WTC: wykres główny, Multi-Chart Workspace, indykatory bota, Kronos M1/M5, AI Live Zones, Volume Profile Auto Zones, Setup Builder bez zleceń;
* PEPE$SIGNAL: rejestr sygnałów wszystkich strategii, wykres sygnału, warunki ENTRY/TRIGGER/INVALIDATION, oceny modeli, konsensus, MTF.

Szczegóły, statusy WORKING / PARTIAL / BLOCKED i ograniczenia: `docs/wdrozenie_1_36/RAPORT_WDROZENIA_PL.md`. Instrukcje PDF: sekcja 4d.

**Testy:**

| Zestaw | Wynik |
|---|---|
| `test_ui_neural_city` (9), `test_ui_towers` (3, nowy) | PASS |
| regresja UI (cult, wizard, pmw133, terminal shell, pages, chart prefs, market zones, interface 129, kronos, lab, scalp, analytics, monitor, setup panel, signal card, control center, training center, quant) | PASS (`test_ui_terminal_shell.test_03` raz niestabilny czasowo, w powtórkach PASS) |
| `test_release_tools`, `test_desktop_app`, `test_launchers` | PASS |
| typecheck / build frontendu, `go test` / `go vet` aplikacji desktop | PASS |

Backend bez zmian funkcjonalnych (tylko numer wersji). Nie testowano na prawdziwym terminalu MT5 ani z zainstalowanym Kronosem.
Pliki EXE nie są podpisane cyfrowo.
