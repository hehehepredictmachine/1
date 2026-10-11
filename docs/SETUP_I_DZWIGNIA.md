# Wybór setupu, szczegóły scenariusza i dźwignia (1.8.0)

## Wybór setupu (pasek „Setup” nad kartą sygnału)
| Tryb | Co robi silnik | Co pokazuje monitor |
|---|---|---|
| **AUTO** | dotychczasowy automatyczny wybór najlepszego setupu | szczegóły setupu wybranego przez silnik |
| **WYBRANY SETUP** + strategia | analizuje i wybiera **tylko** tę strategię (np. S11) | jej scenariusze i szczegóły; gdy brak – dokładnie, czego brakuje |
| **WSZYSTKIE** | wybór automatyczny bez zmian | listę wszystkich scenariuszy; „Szczegóły” otwiera konkretny |

* **Strategia** = metoda z rejestru (S01…S11). **Scenariusz** = konkretne wykrycie tej strategii: identyfikator `MQA-…`, symbol `XAUUSD-`,
  kierunek, interwał, czas powstania.
* Wybór **nie wymusza sygnału ani zlecenia** – scenariusz musi zostać wykryty i przejść wszystkie bramki (dane, rynek, ryzyko, AI wg polityki,
  ML wg trybu, tryb wykonania). Zapis: baza programu, osobno dla każdego rachunku (serwer:login); po zmianie rachunku – jego własne ustawienia.

## Szczegóły setupu
* **Kierunek scenariusza (BUY/SELL)** to tylko rozważany kierunek. O wejściu mówi osobne pole **Możliwość wejścia: DOSTĘPNE / ZABLOKOWANE**
  z przyczynami. DOSTĘPNE oznacza zgodę reguł bota; wysłanie zlecenia zależy jeszcze od trybu wykonania (SIGNALS/PAPER/AUTO).
* Checklista: warunek, wymagany próg (z parametrów strategii), aktualna wartość, status ✓ / ✗ / ? (BRAK DANYCH) / • (odczyt), powód.
  Warunki oparte na zamknięciu świecy są spełnione dopiero po jej zamknięciu.
* **Wynik ACTIVE 0–100** to heurystyka zgodności z regułami i reżimem – nie prawdopodobieństwo wygranej (brak kalibracji).
* Historia strategii – wyłącznie z rozliczonych transakcji bota (okres i liczba transakcji); bez nich: „brak statystyk”.

## Dźwignia / limit ekspozycji (Ustawienia → Ryzyko)
* **AUTO** – limit = dźwignia rachunku odczytana z MT5 (`account_info().leverage`).
* **RĘCZNIE** – limit planowania i ekspozycji bota (1:1 … 1:500, nie wyżej niż dźwignia rachunku).
  **Nie zmienia dźwigni u brokera.**
* Trzy wartości: dźwignia rachunku, Twój limit, **efektywna ekspozycja** = nominał pozycji w walucie rachunku / equity
  (nominał z kalkulatora brokera `order_calc_profit`, bez założonej wielkości kontraktu).
* Wymagany margin zawsze liczy broker (`order_calc_margin`) dla `XAUUSD-` – dźwignia nie jest podstawiana do uproszczonego wzoru.
  Symulacji innej dźwigni brokera nie ma (brak zweryfikowanego modelu marginu dla instrumentu).

## Jak liczony jest wolumen
Największy wolumen spełniający **jednocześnie**: budżet ryzyka do SL (z prowizją i stresem poślizgu; Bid/Ask bez podwójnego liczenia),
wolny margin pomniejszony o margin zleceń oczekujących i bufor, limit ekspozycji (otwarte pozycje + zlecenia oczekujące + nowa pozycja),
maks. wolumen symbolu. Wynik zaokrąglany w dół do kroku i ponownie sprawdzany kalkulatorami brokera; minimalny lot ponad którykolwiek
limit → ZABLOKOWANE z powodem. Wyższa dźwignia nie zwiększa procentu ryzyka i nie przesuwa SL/TP. Strata przy SL jest **szacowana**
(luki i poślizg mogą ją zwiększyć). Przed wysłaniem zlecenia bramka porównuje wersję ustawień, przelicza ryzyko na bieżących danych i wykonuje
`order_check`; zmiana ustawień lub mniejszy dopuszczalny wolumen blokuje wysyłkę. Otwarte pozycje i zlecenia nie są zmieniane.

## Do sprawdzenia na Twoim terminalu
* dźwignia `account_info().leverage` i margin `XAUUSD-` (broker może liczyć margin złota inaczej niż z dźwigni rachunku – monitor pokazuje
  „dźwignię instrumentu wg marginu brokera”),
* `order_calc_profit` / `order_calc_margin` dla `XAUUSD-` przy otwartym rynku (wolumen, nominał),
* zachowanie przy zleceniach oczekujących i na rachunku netting/hedging,
* prowizja rachunku (Koszty) – bez niej RR po kosztach jest oznaczony jako niepełny.
