# Aktualizacja 1.42.0 – nowy interfejs i pełne uruchomienie modeli / koszyków FX

## Co się zmienia na ekranie

1. **Okno startowe (Windows)** – czarne tło, napis PEPEMARKETWIZARD TEAM, linie postępu startu silnika. Gdy silnik działa, kliknij **WEJDŹ**.
   Wybór danych poprzedniej instalacji, błąd + „Spróbuj ponownie”, logi i zamykanie działają jak wcześniej.
2. **Film intro** – odtwarza się raz na sesję. „PRZEJDŹ DO MENU” albo ESC pomija film. Przy włączonym ograniczeniu ruchu menu pojawia się od razu.
   Ctrl+Alt+B odtwarza intro ponownie.
3. **Menu** – trzy planety: **01 FOREX**, **02 CRYPTO**, **03 OTC**. CRYPTO i OTC pokazują „tryb w przygotowaniu” (bez zmiany profilu bota).
4. **FOREX** – przelot do kuli FOREX. Po lewej **MODEL A** (praca modeli predykcji), po prawej **MODEL B** (silnik sygnałów) – oba z prawdziwych
   danych bota. Cztery planety:
   * **CHARTS** – wykres instrumentu (interwały, wskaźniki, strefy, profil wolumenu, plan transakcji, sygnały AI), okno Kronos i wybór
     interwałów, na których Kronos pracuje (zakładka KRONOS, zmiana wymaga potwierdzenia);
   * **SIGNALS** – lista sygnałów (silnik, scenariusze, SH) z filtrami, bramki ścieżki, ocena wszystkich modeli, strategie, wyniki;
   * **MODELS & BACKTEST** – obserwatorium modeli, trening (pełne parametry, anulowanie, aktywacja, rollback), backtest, Monte Carlo;
   * **ROI** – wynik bota w PAPER / AUTO_DEMO / AUTO_LIVE (BRAK DANYCH, gdy nie ma rozliczonych transakcji).
5. **Panele systemowe** (ikony w prawym dolnym rogu, przycisk **STOP**, chip trybu u góry) – Ustawienia, Tryb pracy, STOP, Diagnostyka
   otwierają się w szufladzie nad bieżącym ekranem. ESC zamyka. Logika jest taka sama jak w 1.41.

Stare adresy (zakładki w przeglądarce) przekierowują automatycznie, np. `#/wykresy` → CHARTS, `#/ustawienia` → Ustawienia.

## Modele w trybie ASSIST

Przy pierwszym uruchomieniu 1.42 aplikacja jednorazowo przełącza modele z OBSERVE na **ASSIST** (Twoja decyzja):
Chronos-2, Granite TTM, TiRex-2 (ścieżki ACTIVE / SCALPING / HEDGING) oraz Kronos (SCALPING / HEDGING).

* ASSIST może tylko **wstrzymać** wejście, gdy świeża prognoza modelu jest przeciwna do strony setupu. Model nigdy sam nie otwiera pozycji.
* Model niedostępny albo z nieaktualną prognozą nie blokuje niczego.
* Ustawienie REQUIRED (jeśli było) zostaje. Każdą rolę możesz zmienić z powrotem na OBSERVE – migracja nie nadpisze Twojej późniejszej zmiany.
* Wpis migracji: `data/upgrade/1.42.0.json`.

## Zlecenia z koszyków FX (90 strategii)

Plany koszyków **FX_SMC / FX_SCALP / FX_HEDGE** (profil FOREX / MT5) przechodzą teraz przez **istniejącą ścieżkę SH** bota:
koordynator → silnik ryzyka z Twoimi limitami (ryzyko na transakcję, dzienny limit straty, liczba pozycji, ekspozycja, depozyt, spread)
→ rezerwacja ryzyka → wysłanie zlecenia zgodnie z trybem wykonania (PAPER / AUTO_DEMO / AUTO_LIVE).

* Jeden plan na zdarzenie rynkowe, każdy sygnał najwyżej raz. Sygnał starszy niż 3 świece (max 30 min) nie jest „goniony”.
* Gdy cena jest już za SL albo minęła TP1 – plan zostaje unieważniony bez zlecenia.
* Wielkość pozycji liczy wspólny silnik ryzyka (nie koszyk). SL i cele planu nie są przesuwane.
* Wyłączenie: `baskets/settings.json` → `"profiles": {"FOREX_MT5": {"execution": "SIGNALS_ONLY"}}` (albo API `PUT /api/v1/baskets/settings`).
* Nowe wejścia otwierają się tylko, gdy w panelu **Tryb pracy** wybrana jest ścieżka główna SCALPING / HEDGING, a tryb wykonania pozwala na zlecenia.
* CRYPTO (FOMO) i OTC (Pocket Option) – bez zmian: sygnał + ręczny ticket.

## Czego 1.42 nie zmienia

Tryb wykonania rachunku, STOP, limity ryzyka, stawki, dźwignia, SL, strategie złota S01–S12, silnik, moduły MQL5 w MetaTraderze.

## Wycofanie

Stary interfejs leży w `archive/ui_1_41/`. Pełny powrót: zainstaluj paczkę 1.41.0 (dane w folderze danych zostają).
Same role modeli: w panelu MODELS albo przez API ustaw OBSERVE. Same zlecenia koszyków: `execution = SIGNALS_ONLY`.
