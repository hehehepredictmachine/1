# Raport końcowy – PepeMarketWizard 1.37.0 (Kronos-base, Chronos-2, FinCast – prawdziwa inferencja)

**Paczki 1.37.0:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_37_0.zip` (2615 plików, aplikacja Windows) | `9b03eb4a3dcea7d1436b5ebdacd8fe9516b32b5b1ab33390ac44044f44b0f5ec` |
| `PepeMarketWizard_1_37_0.zip` (1546 plików, folder programu) | `3e2e8014ea9428435102e2a4c8f85e4afad808573241e964cd6f69004aee42b4` |

`tools/verify_release.py --all` daje OK dla obu (ścieżki, manifest, sekrety, plik .sha256). Paczki **nie zawierają** wag modeli, środowisk
`.venv_*`, danych rachunku ani sekretów – wagi pobiera instalator. Start z rozpakowanej paczki folderowej (backend demo): wersja 1.37.0,
Kronos-base / Chronos-2 / FinCast w stanie NOT_INSTALLED z przyczyną (bez wymyślonych prognoz).

**Zakres** (masterprompt „3 modele: Kronos-base, Chronos-2, FinCast”):
* Kronos → **Kronos-base** (największy publiczny; Kronos-large niedostępny), ten sam serwis, kontrola tożsamości checkpointu, parity PASS,
  historia „Kronos-small” zachowana, brak cichego przejścia na mniejszy model;
* **Chronos-2** (`amazon/chronos-2`) i **FinCast** (`Vincent05R/FinCast`) – osobne procesy i środowiska, oficjalne API, przypięte rewizje,
  SHA-256 każdego pliku, `weights_only=True` + `strict=True`;
* instalator `38_MODELE_CHRONOS2_FINCAST.bat` (online / offline, CPU / CUDA), przyciski w panelu;
* połączenie z ModelHub, historią i rozliczaniem (migracja 0026), koordynatorem (ACTIVE) i SH (SCALPING/HEDGING); role OBSERVE / ASSIST /
  REQUIRED tylko po pozytywnej walidacji na danych rzeczywistych i z potwierdzeniem; modele mogą wyłącznie wstrzymać setup;
* walidacja walk-forward trzech modeli vs „ostatnia cena” i momentum; brak łączenia bez osobnej walidacji;
* zwijana sekcja „Modele prognoz” na stronie „Wykresy bota” (bez zmian wyglądu i nawigacji).

Szczegóły, zasoby, czasy i ograniczenia: `docs/MODELE_KRONOS_CHRONOS2_FINCAST_1_37_PL.md`. Rollback: `ROLLBACK.md` (1.37.0 → 1.36.0).
Instrukcje PDF: sekcja 4e.

**Testy (środowisko wdrożenia: Linux, CPU, 16,9 GB RAM, bez GPU):**

| Zestaw | Wynik |
|---|---|
| Prawdziwe wagi Chronos-2 (`test_foundation_real` w `.venv_chronos2`) | PASS – tożsamość, parity 0,0, determinizm, brak look-ahead, błędy wejścia, kowariaty |
| Prawdziwe wagi FinCast (`test_foundation_real` w `.venv_fincast`) | PASS – j.w. + kwantyle; 8,0 GB RAM przy ładowaniu |
| Kronos-base runtime z oficjalnymi wagami (`test_kronos_runtime`) | PASS (102 310 592 parametrów, parity PASS, referencja autorów NOT_APPLICABLE) |
| `test_tsfm_bot` (19), `test_ui_foundation` (nowy) | PASS |
| Pełna regresja `tools/run_tests.py` | 1289 testów, 22 pominięte; 1 błąd (lista migracji bez 0026) poprawiony, test powtórzony: PASS |
| Instalatory na czystym folderze (Chronos-2, FinCast) | PASS (tryb deweloperski Linux; Chronos-2 3 min 51 s, FinCast ok. 20 min) |
| Walidacja walk-forward przez API (demo, dane syntetyczne, 60 punktów) | wykonana (351 s); werdykty niepozytywne – zgodnie z regułą dla danych syntetycznych; ASSIST odrzucony (409) |
| typecheck / build frontendu, `go test` aplikacji desktop | PASS |

**Ograniczenia:** instalacja i inferencja nie były uruchomione na Windows ani na GPU (pliki z sumami dla Windows sprawdzone narzędziem);
walidacja na rynku wymaga Twoich danych MT5; nie testowano z prawdziwym terminalem MT5. Żadna transakcja nie była otwierana, tryb rachunku
nie był zmieniany. Pliki EXE nie są podpisane cyfrowo.
