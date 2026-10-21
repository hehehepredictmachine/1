# PMW-SH-1 · Raport końcowy (wersja 1.17.0)

## Najważniejsze

* **Gotowość techniczna**: SCALPING i HEDGING są zintegrowane z botem (analiza, setup, ryzyko, koordynacja, wykonanie
  SIGNALS/PAPER/AUTO_DEMO, rekonsyliacja, restart, panel, trening, eksport). Testy odbioru 1–16 są zielone na symulacji, a
  pełna regresja (755 testów) jest zielona po dwóch poprawkach oczekiwań.
* **Jakość strategii: NIEZNANA.** Walidacji na historii klienta nie wykonano (bloker B-DATA). Parametry są robocze. **Nie
  wolno używać SH na rachunku rzeczywistym**: AUTO_LIVE jest zablokowane w kodzie, a AUTO_DEMO wymaga przetrenowanego
  i zwalidowanego modelu zdarzenia oraz znanej prowizji.

## Co zmieniono (etapy)

| Etap | Raport | Commit |
|---|---|---|
| 1–2 audyt i naprawy krytyczne (F-03…F-15) | `01_AUDYT_ARCHITEKTURY.md` | 361d725 |
| jednostki, cykl życia, automat koszyka | (w `05`) | d0dab3f |
| 3 rejestr modeli i wspólna analiza | `03_MODELE_I_ROLE.md` | c05aeff |
| 4 ryzyko, stan, konflikty | `04_KONFLIKTY_I_RYZYKO.md` | 0d3b140 |
| 5–6 SCALPING / HEDGING na żywo | `05_SPECYFIKACJA_STRATEGII.md` | a1b7d75 |
| 7–8 replay, trening SH, panel treningu, panel strategii | `07_TRENING_EKSPORT_URUCHOMIENIE.md` | 610d5d2 |
| 9 walidacja, testy odbioru, dokumentacja | `06_WALIDACJA.md`, `08_TESTY_ODBIORU.md` | 17a2ae5 i dalsze |

## Sprawdzone

* Testy SH: 67 testów w `tests/test_sh_*.py`.
  * Testy na prawdziwym procesie serwera i w przeglądarce Chromium (1366 i 390 px) przechodzą bez błędów strony.
  * Runner `training run --demo --tasks sh_models` działa end-to-end (dane syntetyczne, bez promocji).
* Pełna regresja: 755 testów.
  * Dwie porażki wynikały ze zmian, nie z błędów: oczekiwana liczba zadań treningu 16 → 17 i kolejność stron w sekcji
    „Setupy”. Oczekiwania poprawiono, a powtórzone 18 testów przeszło.
* Błędy znalezione i naprawione w nowym kodzie:
  * F-19: bramka modelu przepuszczała szum;
  * F-20: luka przez wszystkie TP zamykała runner za dużym wolumenem;
  * F-21: wydajność reżimu (replay 12 miesięcy skrócony z ponad 2 h).

## Zablokowane (szczegóły w `07`)

| Bloker | Opis |
|---|---|
| B-DATA | brak historii z MT5 klienta |
| B-COMM | nieznana prowizja |
| B-SWAP | swap nieuwzględniony |
| B-TICKS | brak ticków |
| B-MT5 | brak terminala, testy tylko na symulatorze |
| B-BTC | parametry BTC nieskalibrowane, instrument wyłączony |
| B-ACC | HEDGING tylko na rachunku typu hedging |

## Następny krok po stronie użytkownika

1. Na komputerze z MT5 uruchom `30_SH_WALIDACJA.bat` albo panel **Modele i trening → Trening modeli → Uruchom → zadanie
   SCALPING/HEDGING**.
2. Przeczytaj raport walidacji (`data/sh/validation/`):
   * wynik netto po kosztach;
   * porównanie z regułą naiwną;
   * stabilność w foldach;
   * HEDGE vs NO_HEDGE vs REDUCE.
3. Dopiero przy pozytywnym, stabilnym wyniku i znanej prowizji rozważ test na rachunku DEMO.
