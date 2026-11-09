# Raport końcowy – PepeMarketWizard 1.38.0 (pakiet 20 strategii XAUUSD: 10 HEDGING + 10 SCALPING)

**Paczki 1.38.0:**

| Plik | SHA-256 |
|---|---|
| `PepeMarketWizard_DESKTOP_1_38_0.zip` (2635 plików, aplikacja Windows) | `61a93ade75563da4a730b1c2a4ff35e4a7d06e481b2d701780a5713c6903ecb5` |
| `PepeMarketWizard_1_38_0.zip` (1566 plików, folder programu) | `3e0dd8ccc164236cad5fe62fd055bccab7983c711b0855e52ae05e67e61620f8` |

`tools/verify_release.py --all`: OK dla obu (ścieżki, manifest, sekrety, .sha256). Paczki bez wag modeli, środowisk `.venv_*`, danych
rachunku, historii i raportów walidacji. Start z rozpakowanej paczki (backend demo): wersja 1.38.0, katalog 20 wariantów
(PMW-SH-PACK-2.0.0), migracja 0027 zastosowana. Wejściowa paczka 1.37.0 nie została nadpisana.

## Co działa end-to-end

Feed MT5 (zamknięte świece M1/M3/M5/M15/H1) → cykl SH po każdej zamkniętej M1 (niezależnie od otwarcia panelu) → 20 detektorów
(BUY + lustrzany SELL, wspólna generacja cech) → solver dwóch TP i RR netto / RR koszyka → odbiorniki modeli (role istniejące) →
arbitraż (jedno wejście na ekspozycję) → silnik ryzyka z profilem wariantu → DecisionCoordinator → IntentLedger/RiskBook → executor SH w
bieżącym trybie (SIGNALS: zero zleceń, PAPER: jawne fille) → plan z planowanymi TP1/TP2 bez BE → zarządzanie koszykiem HG polityką
wariantu (hedge z intencją HEDGE i rezerwacją, limit po partialu, timeout = wyjście koszyka) → plan PMW-PLAN-2 → panel „Pakiet 20
strategii”, warstwa wykresu „Pakiet 20” (strzałki, Entry/SL/TP1/TP2), PEPE$SIGNAL z tożsamością wariantu i TF, statystyki per wariant →
replay/walidacja na eksporcie (CLI, zadanie runnera `sh_pack`, `39_PAKIET_20_WALIDACJA.bat`).

## 20 strategii

| ID | Implementacja | Testy | Walidacja skuteczności |
|---|---|---|---|
| PMW_HG01–HG10 | IMPLEMENTED (detektor + plan + polityka hedge) | TESTED (mechanika; polityki: HG03 pełny scenariusz, wszystkie – teksty i ograniczenie straty, replay) | NOT_VALIDATED |
| PMW_SC01–SC10 | IMPLEMENTED (detektor + plan) | TESTED (mechanika) | NOT_VALIDATED |

Szczegóły per ID: `docs/strategies20/TEST_REPORT.md`; reguły: `STRATEGY_SPECIFICATIONS.md`; integracja: `INTEGRATION_MAP.md`;
RR i jednostki: `RISK_AND_UNITS.md`; instrukcja: `RUNBOOK_PL.md`; źródła: `RESEARCH_AND_SOURCES.md`; rollback: `ROLLBACK.md` (0c).

## Testy i build

| Zestaw | Wynik |
|---|---|
| `test_sh_pack` (24) + `test_ui_sh_pack` (1) | OK |
| Pełna regresja `tools/run_tests.py` | 1314 testów, 22 pominięte; 6 błędów z jednej przyczyny (stary kontrakt `arbitrate` w testach) – naprawione, 37/37 powtórzone OK; po ostatnich zmianach 155 testów z dotkniętych zestawów OK |
| `npm run typecheck`, `npm run build`, `go test` aplikacji desktop, kontrola requirements Windows | OK |
| Zadanie runnera `sh_pack` (demo), replay CLI (40 000 M1 syntetycznych, 52 s) | UKOŃCZONE; werdykty NOT_VALIDATED (dane syntetyczne) |
| Wydajność cyklu pakietu | offline p50 26 ms / p95 33 ms; w działającym bocie demo p50 337 ms / p95 738 ms (raz na M1, 4 vCPU) |

## Ograniczenia

* Brak historii MT5 użytkownika → żaden wariant nie ma walidacji OOS (NOT_VALIDATED). Pakiet nie jest „gotowy do zyskownego handlu”;
  AUTO_LIVE dla wariantu wymaga raportu VALIDATED na `REAL_USER_DATA`.
* Warianty HG potrzebują ~42 dni historii H1 do rozgrzewki (EMA200 × 5) – przy krótszej historii pozostają WARMING_UP.
* Brak Windows i terminala MT5 w środowisku budowania (AUTO_DEMO/AUTO_LIVE nietestowane na prawdziwym terminalu); pliki EXE niepodpisane.
* Prowizja nieznana → plan hipotetyczny ze scenariuszem kosztowym (nie NET_VALIDATED / READY_TO_EXECUTE); swap niemodelowany.
* REDUCE na rachunku NETTING dla pakietu niewłączony (HG na NETTING = blokada z powodem); wariant GARCH dla HG09 – nie zaimplementowany jako
  podmiana. DSR/PBO – wymagają realnych serii; raport replayu pokazuje wszystkie próby.

Nie otwierano transakcji i nie zmieniano trybu rachunku.
