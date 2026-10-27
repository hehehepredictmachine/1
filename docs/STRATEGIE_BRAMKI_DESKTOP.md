# Strategie – inwentaryzacja bramek sygnału i zlecenia (1.24, DK6)

Cel: sygnał i zlecenie oceniane **osobno**; usunąć zdublowane / sprzeczne blokady; brak opcjonalnego AI, modelu lub wskaźnika
nie zatrzymuje analizy bez uzasadnienia; zostają: wymagania brokera, jednoznaczny rachunek i tryb, jawne limity użytkownika, STOP,
idempotencja i prowadzenie istniejących pozycji. Bez deklarowania wyższej skuteczności – wynik porównania przed/po w §4.

## 1. Ścieżka główna S01–S12 (profil ACTIVE) – węzły drzewa decyzji (`engine/decision.py`)

| Węzeł | Rodzaj | Co blokuje | Domyślnie | Ocena / decyzja |
|---|---|---|---|---|
| DATA | sygnał + zlecenie | dane do analizy niepełne (FAIL) / brak świeżych ticków do wejścia (PARTIAL) | zawsze | **zostaje** – bez aktualnych danych nie ma podstaw ani do sygnału, ani do ceny wejścia |
| MARKET | sygnał + zlecenie | rynek zamknięty; okno wydarzenia makro HIGH (`macro_block_high_impact`); brak kalendarza tylko gdy `macro_calendar_required` | kalendarz **nie** wymagany | **zostaje**; brak kalendarza nie blokuje (było już złagodzone w 1.x) |
| STRATEGY | sygnał | brak setupu wybranej strategii | – | **zostaje** (warunki konieczne strategii) |
| TRIGGER | sygnał | setup nie jest CONFIRMED (wyzwalacz na zamkniętej świecy) | – | **zostaje** – to definicja sygnału |
| RISK | zlecenie | limity użytkownika nieustawione; RR netto < `rr_block_below`; **nieznana prowizja**; brak stresu poślizgu; spread > limit; min. lot; margin; dzienny limit; maks. pozycji; cooldown; geometria planu vs cena; stops level; tryb symbolu | limity puste | **zostaje** – jawne limity użytkownika i warunki brokera. Nieznana prowizja: **zostaje blokadą** (rachunek „Zero” nie dowodzi zerowych kosztów); naprawa = wpisanie prowizji (także 0, jeśli użytkownik ją zna) w Centrum sterowania → Ryzyko i koszty |
| AI | zlecenie | polityka `VETO` (domyślna): blokuje tylko jawny sprzeciw Claude; czeka ≤ 60 s po potwierdzeniu, jeśli ocena trwa | VETO | **zmiana (wyświetlanie)**: brak klucza / agent wyłączony / brak modelu = od razu „nie wymagane” (wcześniej przed potwierdzeniem setupu węzeł pokazywał „oczekuje”, co wyglądało na blokadę; po potwierdzeniu i tak przepuszczał) |
| ML | zlecenie | tylko tryb ASSIST z modelem poniżej zwalidowanego progu | SHADOW | **zostaje** – SHADOW i brak modelu nie blokują |
| PERMISSION | zlecenie | tryb SIGNALS; brak / inny rachunek niż potwierdzony; typ rachunku ≠ tryb; LIVE na danych syntetycznych; STOP; brak ścieżki głównej; druga ścieżka; strażnik portfela; **strategia bez zgody na handel** | S11, S12 bez handlu | **zmiana**: patrz §2 |

## 2. Zmiana: wybór AUTO a strategie „tylko sygnały”

Problem (kolizja bramek): selektor AUTO (`strategies/selector.py`) wybierał najlepszy setup **spośród wszystkich skanowanych strategii**,
również tych, które z założenia tylko sygnalizują (domyślnie S11 i S12 – kandydaci bez walidacji; przełącznik `trade=false`). Gdy taki
setup był najwyżej w rankingu, węzeł PERMISSION blokował zlecenie (`STRATEGY_TRADE_DISABLED_S12`), a setup strategii dopuszczonej do
handlu – nawet potwierdzony – nie mógł zostać wybrany, bo selekcja i histereza trzymały strategię „tylko sygnały”.

Po zmianie (AUTO): selekcja do wykonania obejmuje tylko strategie z `trade=true`. Strategie „tylko sygnały” dalej skanują, publikują
sygnały (tracker, sygnały bota, Telegram) i są widoczne w rankingu kandydatów z oznaczeniem „tylko sygnał”. Konflikt kierunków
(LONG vs SHORT w tym samym horyzoncie) liczony jest między kandydatami do wykonania. Tryb MANUAL bez zmian (wybór użytkownika jest
wiążący – jeśli wybierze strategię bez zgody na handel, decyzja pokaże jawny powód).

## 3. Ścieżka SCALPING / HEDGING (`sh/risk.py`)

| Kontrola | Ocena / decyzja |
|---|---|
| setup READY, TTL, duplikat, jeden właściciel pozycji, notowanie świeże, spread, equity, dzienny limit, maks. pozycji, cooldown, min. wolumen, budżet koszyka, typ rachunku dla HEDGING | **zostają** (warunki brokera, limity, idempotencja) |
| `model_mode == PEŁNA` (skalibrowany model zdarzenia) | **zmiana**: wymagany tylko dla AUTO LIVE. AUTO DEMO działa także w trybie OGRANICZONYM (score) – rachunek demo nie ryzykuje pieniędzy, a bez tego nie da się przetestować ścieżki na demo. Brak modelu nie blokuje sygnałów ani PAPER (bez zmian) |
| prowizja instrumentu znana | **zostaje** dla DEMO/LIVE (pełny koszt) |
| AUTO LIVE: walidacja ścieżki na danych klienta (REAL_USER_DATA, znana prowizja, n ≥ 30, dodatnia wartość oczekiwana) | **zostaje** (DK1 – zamiast bezwarunkowej odmowy) |

## 4. Porównanie przed / po (te same dane, po kosztach, poza próbą)

Wykonano: `python tools/replay_strategies.py --synthetic 180 --seed 3 --trade-policy BOTH` (ten sam kod skanera, trackera i
selektora co na żywo; wejście na otwarciu następnej świecy M5, SL pierwszy przy niejednoznacznej świecy, koszty w R; wynik surowy:
`docs/BRAMKI_PRZED_PO_SYNTHETIC.json`). PRZED = reguły 1.23 (wybór spośród wszystkich strategii, wybrana S11/S12 nie otwiera pozycji),
PO = reguły 1.24 (wybór tylko spośród strategii z prawem handlu).
Te same dane, ten sam model kosztów {"spread": 0.12, "slip": 0.05, "commission": 0.035}, krok M15, wynik w R po kosztach, podział chronologiczny DEV/VAL/OOS 60/20/20 (cięcia ['2026-08-10T16:54:00Z', '2026-09-18T15:27:00Z']). Status: **FUNCTIONAL_REPLAY_SYNTHETIC - wyniki nie są dowodem skuteczności**.

| Wariant / segment | Transakcje | Expectancy R | PF | Win | Maks. DD R |
|---|---|---|---|---|---|
| PRZED (1.23) – całość | 820 | 0.144 | 1.27 | 419/820 (51%) | 52.56 |
| PRZED (1.23) – DEV | 499 | 0.196 | 1.41 | 260/499 (52%) | 11.31 |
| PRZED (1.23) – VAL | 178 | -0.09 | 0.88 | 82/178 (46%) | 52.56 |
| PRZED (1.23) – OOS | 143 | 0.257 | 1.56 | 77/143 (54%) | 6.28 |
| PO (1.24) – całość | 913 | 0.144 | 1.27 | 465/913 (51%) | 48.43 |
| PO (1.24) – DEV | 545 | 0.192 | 1.39 | 277/545 (51%) | 15.78 |
| PO (1.24) – VAL | 202 | -0.049 | 0.93 | 98/202 (49%) | 48.43 |
| PO (1.24) – OOS | 166 | 0.223 | 1.49 | 90/166 (54%) | 10.47 |

Wybór AUTO trzymający strategię „tylko sygnały” (brak pozycji): przed 358, po 0. Zmiany wyboru: przed 6019, po 6520.

Uwaga: wynik na danych syntetycznych pokazuje tylko działanie łańcucha i różnicę w liczbie wejść – nie jest dowodem skuteczności.

Wniosek (bez interpretacji ponad dane): zmiana usuwa sytuację, w której wybór trzymała strategia „tylko sygnały” (358 → 0) i zwiększa
liczbę wejść o ok. 11 %. Na całym okresie wartość oczekiwana po kosztach jest taka sama (0,144 R); w segmencie OOS niższa (0,223 vs
0,257 R) przy większym obsunięciu (10,5 vs 6,3 R). Na danych syntetycznych nie ma podstaw, by twierdzić, że zmiana poprawia albo
pogarsza wynik – uzasadnieniem zmiany jest usunięcie kolizji bramek (sygnał strategii niedopuszczonej do handlu blokował wykonanie
strategii dopuszczonej), a nie skuteczność. Przełączniki „handel” per strategia (Ustawienia → AUTO / ACTIVE) pozostają w rękach
użytkownika.

Wyniki: przy własnych danych użytkownika uruchom poniższe polecenie (patrz niżej). Dane w tym środowisku: **wyłącznie
syntetyczne** (symulator terminala) – liczby dowodzą tylko, że łańcuch działa identycznie dla obu wariantów i jak zmienia się liczba
transakcji; **nie są dowodem skuteczności** i nie mogą być podstawą decyzji o LIVE.

Uruchomienie na własnych danych (Windows, po eksporcie historii z MT5: `python -m masterquo export` lub panel Trening → eksport):

```
python tools/replay_strategies.py --csv-dir <folder z D1.csv..M1.csv> --trade-policy BOTH --commission <prowizja/strona/jednostkę> --slippage <poślizg>
```
