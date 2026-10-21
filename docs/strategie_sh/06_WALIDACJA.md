# PMW-SH-1 · Walidacja SCALPING / HEDGING – metoda, wyniki i ograniczenia

## Stan faktyczny (bez upiększeń)

**Walidacji na danych klienta nie wykonano.** W tym środowisku nie ma eksportu historii XAUUSD- ani BTC z terminala MT5
klienta. Mechanizm walidacji był uruchamiany tylko na danych **SYNTETYCZNYCH** z symulatora terminala, w testach technicznych.
Wyniki z danych syntetycznych:
* nie są informacją o jakości strategii;
* nie są zapisywane jako raport walidacji, z którego korzysta automat;
* nigdy nie promują modelu.

Gotowość techniczna (kod, testy odbioru) i jakość strategii (wartość oczekiwana po kosztach) to dwie osobne sprawy. Ten
dokument opisuje tylko gotowość techniczną. **Projekt nie jest gotowy do pracy na rachunku rzeczywistym.** AUTO_LIVE jest
zablokowane dla SH w kodzie (`sh/risk.py`, `sh/executor.py`).

## Jak uruchomić walidację na danych klienta

1. Uruchom panel **Modele i trening → Trening modeli → Uruchom**. Zaznacz zadanie „SCALPING/HEDGING: replay strategii…” albo
   uruchom „Start wszystkich”.
   Alternatywnie, z linii poleceń: `python -m masterquo training run --instruments XAUUSD --profile PELNY_TRENING --tasks sh_models`.
2. Runner wykona kolejno:
   * eksport historii z terminala;
   * kontrolę jakości;
   * `python -m masterquo sh train`.
3. Raporty trafiają do:
   * `data/sh/validation/XAUUSD_SCALPING.json`;
   * `data/sh/validation/XAUUSD_HEDGING.json`;
   * katalogu runu: `<instrument>_sh_models_<strategia>_report.json`.

## Metoda (zaimplementowana w `sh/replay.py`)

* **Ten sam kod co na żywo**: `context.snapshot` (z tym samym cache), `setup.evaluate`, `lifecycle.Position`,
  `hedge_fsm.Basket`. Replay nie jest osobną implementacją.
  * Przyrostowy reżim M5 (`IncRegime`) daje identyczne stany jak `market_v2.regime_series` na tym samym oknie (sprawdzono:
    400/400 świec).
* **Bez zaglądania w przyszłość**: wyższe interwały dostępne dopiero po zamknięciu świecy (bisect po czasie zamknięcia).
  Ocena odbywa się na zamkniętej M1, a wejście na otwarciu następnej świecy po stronie wykonywalnej (Ask/Bid) z poślizgiem.
* **Jeden plan naraz na strategię**, jak na żywo (koordynator).
* **Świece niejednoznaczne** (dotknięcie celu i SL w jednej świecy) rozstrzygane są konserwatywnie: wygrywa SL. Raport podaje
  udział takich świec.
  * Luka przez SL: wypełnienie po cenie otwarcia (gorzej niż SL).
  * BE działa dopiero od świecy po potwierdzonym TP2.
* **Rozliczenie całego cyklu**: jeden plan to jedna transakcja.
  * Koszty: spread świecy, poślizg w cenach wykonania, prowizja (jeśli znana).
  * HEDGING: wynik koszyka obejmuje obie nogi, prowizję obu nóg i porównanie wariantów **HEDGE vs NO_HEDGE vs REDUCE** na
    tych samych setupach.
* **Metryki per strategia i instrument**:
  * liczba setupów i statusów oraz najczęstsze powody odrzucenia;
  * trafienia TP1/TP2/TP3 i zdarzenie „TP2 przed SL w horyzoncie”;
  * wartość oczekiwana netto w R i w USD ruchu, z przedziałem 90 % (bootstrap);
  * profit factor, max drawdown, MAE/MFE, czas trzymania, średni koszt;
  * podział na kierunek, sesję, tryb (kontynuacja/odwrócenie) i wyjście;
  * 4 foldy chronologiczne (stabilność w czasie).
* **Porównanie z regułą naiwną** (baseline): co 60 min w kierunku ostatniej godziny, z tymi samymi TP/SL, zarządzaniem i
  kosztami.
* **Model zdarzenia** `sh_tp_model`:
  * podział chronologiczny z embargiem równym horyzontowi;
  * kalibracja Platta;
  * holdout użyty raz;
  * bramka: istotna (> 2 SE) poprawa Brier względem stopy bazowej.
  
  Parametry strategii **nie są optymalizowane na tych danych**, więc nie ma wielokrotnego użycia holdoutu.

## Ograniczenia, które zostają po walidacji

* Brak danych tickowych. Kolejność wewnątrz świecy M1 jest nieznana, dlatego wynik jest konserwatywny dla świec
  niejednoznacznych.
* Swap nie jest uwzględniany. HEDGING trzyma pozycje do 8 h, więc swap przez noc może mieć znaczenie.
* Prowizja: jeśli eksport nie odczyta prowizji z historii transakcji, a profil SH ma `null`, raport pisze to wprost i wynik
  jest zawyżony o prowizję.
* Poślizg pochodzi z profilu (0.05 USD XAUUSD), nie z pomiaru na rachunku klienta.
* Spread pochodzi z kolumny spread świecy M1, która jest wartością ze świecy, a nie spreadem w chwili wejścia.

## Wynik testu technicznego na danych syntetycznych (tylko mechanika)

Uruchomienie `sh train` na 3000 świecach M1 z symulatora:
* SCALPING: 2 setupy, model INSUFFICIENT_DATA;
* HEDGING: 1 setup.

Pokazuje to, że łańcuch działa i że przy braku przesłanek nic nie jest promowane. **To nie jest wynik strategii.**
