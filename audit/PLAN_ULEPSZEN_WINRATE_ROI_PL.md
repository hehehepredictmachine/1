# Plan ulepszeń – winrate, expectancy, ROI (MasterQUO 1.9.0 → 1.10.0+)

Zasada: najpierw poprawność pomiaru (P0), potem hipotezy strategiczne (P1) i adaptacja (P2), każda osobno z ablation
względem baseline. **Wyższy winrate nie jest celem samym w sobie** – kryterium główne: expectancy netto (R i waluta), ROI
w tym samym okresie przy tym samym budżecie ryzyka, drawdown equity. Status dowodu każdej pozycji P1/P2: **BRAK_DOWODU**
(brak danych brokera) – to są hipotezy autora audytu, nie obietnice.

Legenda statusu: DO_NAPRAWY (błąd poprawności) · DO_BADANIA (hipoteza z mechanizmem) · BRAK_DOWODU · ODRZUCONE.
Nakład: M (mały) / S (średni) / D (duży).

## A. Naprawy poprawności (P0) – zmieniają POMIAR, nie strategię

| # | Propozycja | Istniejący problem | Pliki / funkcje | Mechanizm wpływu | Cel | Status dowodu | Eksperyment / test | Kompromis | Nakład | Priorytet | Kryterium odrzucenia |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Wspólna polityka wyjścia zapisana przy otwarciu (MQ-EXIT-POLICY) dla live/PAPER/etykiet/replay | E: globalne wagi/BE, gubiony cel środkowy, brak time-exit | `execution/manager.py`, `gateway.py`, `paper.py`, `ml/labels.py`, `tools/replay_strategies.py` | to samo R w wykonaniu, etykietach i backteście | wiarygodne R/expectancy | DO_NAPRAWY (ODTWORZONE) | repro E + test zgodności replay = PAPER = etykieta dla tych samych danych | trailing/time-exit na żywo wymaga działającej aplikacji | S | 1 | różne R dla tych samych wejść |
| 2 | Chronologiczne rozstrzyganie po TP1 (kursor ticków), jawne AMBIGUOUS | C | `ml/labels.py:step` | koniec zaniżania wyników BE-po-TP1 | uczciwe etykiety | DO_NAPRAWY (ODTWORZONE) | repro C | więcej AMBIGUOUS bez ticków | M | 2 | BE na minimum sprzed TP1 |
| 3 | Rozliczanie partials: transakcja tylko po pełnym zamknięciu; P/L None = UNSETTLED | B, J | `execution/paper.py`, `stats.py` | winrate/PF tylko z zamkniętych pozycji | poprawny winrate | DO_NAPRAWY (ODTWORZONE) | repro B, J | statystyki „później” | M | 3 | otwarta pozycja w statystykach |
| 4 | Koszty: jedno źródło (`resolve_commission`), nieznany koszt = COST_UNKNOWN (poza treningiem) | A | `ml/service.py:_cost`, `ml/dataset.py:eligible` | etykiety netto = koszty wykonania | brak zawyżenia R | DO_NAPRAWY (ODTWORZONE) | repro A | mniej próbek, dopóki brak historii prowizji | M | 4 | ML liczy 0 przy znanej prowizji |
| 5 | S11: `time_exit_bars=None` jawnie, RR_FROM_FILL w etykiecie/replay | D | `ml/labels.py`, `tools/replay_strategies.py`, `ml/features.py` | S11 obecne w ML i replay | brak selekcji próby | DO_NAPRAWY (ODTWORZONE) | repro D | nowa wersja polityki etykiet (stare próbki oznaczone starą wersją) | M | 5 | TypeError / brak S11 w próbkach |
| 6 | Stan TP1 z wykonania (REQUESTED/UNKNOWN/CONFIRMED/REJECTED), BE po CONFIRMED, rekonsyliacja wolumenu | F | `execution/manager.py` | brak „BE bez zysku TP1” | mniej sztucznych BE | DO_NAPRAWY (ODTWORZONE) | repro F | dłuższa ścieżka UNKNOWN | S | 6 | BE po odrzuconym TP1 |
| 7 | Champion i challenger na tych samych sample_id | G | `ml/registry.py` | uczciwa promocja | mniej przypadkowych promocji | DO_NAPRAWY (ODTWORZONE) | repro G | – | M | 7 | różne zbiory |
| 8 | Purging FIT także gdy blok TUNE pusty; jawny rejestr zużytych okien testu | G | `ml/validation.py`, `ml/registry.py` | brak przecieku przy małych próbach | – | DO_NAPRAWY (POTWIERDZONE_W_KODZIE) | test jednostkowy pustego bloku | – | M | 8 | etykieta FIT po starcie CALIB |
| 9 | Credit/bonus jako przepływy w ROI | – | `stats.account_roi` | ROI nie zawyżone bonusem | poprawny ROI | DO_NAPRAWY (POTWIERDZONE_W_KODZIE) | test z deal type 3/6 | – | M | 9 | bonus liczony jako zysk |
| 10 | Weryfikacja czasu MT5 na Twoim terminalu | I | `mt5/clock.py`, diagnostyka | poprawne as-of | – | BRAK_DANYCH | 06_DIAGNOZA_CZASU_MT5 w kilku sesjach + DST | – | M | 10 | offset ≠ wielokrotność 15 min / niezgodność z UTC PC |

## B. Hipotezy strategiczne (P1) – mogą zmienić PRZEWAGĘ; każda: ablation vs baseline 1.10.0

| # | Propozycja | Problem / mechanizm | Pliki | Cel (WR / E[R] / ROI / ryzyko) | Status | Eksperyment | Kompromis | Nakład | Kryterium odrzucenia (ustalone przed wynikami) |
|---|---|---|---|---|---|---|---|---|---|
| 8 | Filtr pełnego kosztu: (spread+prowizja+poślizg)/ryzyko_do_SL ≤ X oraz /oczekiwany_zysk ≤ Y; spread nietypowy dla sesji (percentyl) | koszt zjada małe R | `risk/engine.py` (nowa bramka, domyślnie OFF) | E[R] ↑, obrót ↓ | DO_BADANIA | X ∈ {0.10, 0.15, 0.20}; percentyl spreadu sesji ∈ {90, 95} | utrata okazji przy szerokim spreadzie | M | ROI w tym samym okresie nie rośnie lub DD rośnie > 10% |
| 9 | Dopasowanie reżimu z odmową przy słabym fit | strategie trendu w range | `strategies/selector.py` | E[R] ↑, WR ↑ | DO_BADANIA | próg regime_fit ∈ {0.5, 0.7} | mniej transakcji | M | E[R] CI95 różnicy obejmuje 0 przy spadku obrotu > 40% |
| 10 | Deduplikacja skorelowanych setupów (event_id) i histereza przełączeń AUTO | wiele setupów z jednego ruchu | `selector.py`, `tracker.py` | DD ↓ | DO_BADANIA | min. odstęp przełączeń ∈ {0, 2, 4} świece | spóźnione wejście | M | DD nie spada |
| 11 | Ścisłe vs łagodne triggery, zgodność wyższych TF, okno wejścia | H (łagodne progi) | `config.py` (warianty), profile | WR ↑? E[R]? | DO_BADANIA | H-STRICT-1..3 (protokół) | mniejszy obrót | S | ROI/ryzyko nie lepsze |
| 12 | Odrzucenie wejścia po oddaleniu / opóźnieniu (no chasing) | gonienie ceny | `engine/service`, `gateway` | E[R] ↑ | DO_BADANIA | max_distance_atr ∈ {0.3, 0.5, 1.0} | utrata szybkich ruchów | M | E[R] nie rośnie |
| 13 | 2–3 warianty SL (struktura / +ATR bufor / min dystans wobec kosztów) przy stałym ryzyku | SL zbyt ciasny wobec kosztów | strategie (parametr) | WR ↑, R/transakcję ↓ | DO_BADANIA | 3 warianty, loty przeliczone przy tym samym budżecie | mniejsza wygrana w R | S | E[R] spada mimo WR ↑ |
| 14 | Stały TP vs strukturalny vs partial+BE vs trailing | BE obcina duże wygrane | polityka wyjścia (1) | ROI ↑ / WR ↑ (kompromis) | DO_BADANIA | 4 polityki na tych samych wejściach | WR ↔ średnia wygrana | S | ROI nie rośnie |
| 15 | Sesje / zmienność jako filtry (dopiero po OOS) | – | selektor | – | BRAK_DOWODU | tylko po wynikach OOS, bez data-mining małych koszyków | – | M | koszyk < założonej liczebności |
| 16 | News / rollover / jakość kwotowań jako warunki działania z jawną polityką przy braku kalendarza | `macro_calendar_required=False` | `news/service.py`, `config` | DD ↓ | DO_BADANIA | ON/OFF | utrata okazji | M | brak spadku DD |
| 17 | Rejestrowanie requested_price/fill_price/latencji/odrzuceń; kalibracja modelu kosztów do brokera | brak pomiaru poślizgu | `gateway.py` (`price_requested`, `fill_price` już są), raport | lepsze stres-testy | DO_NAPRAWY (pomiar) | raport rozkładu poślizgu | – | M | – |

## C. Adaptacja oparta na dowodach (P2) – dopiero po OOS / forward

| # | Propozycja | Status | Warunek startu | Kryterium odrzucenia |
|---|---|---|---|---|
| 18 | Ranking AUTO wg zweryfikowanego E[R] netto z karą za niepewność | BRAK_DOWODU | ≥ zdefiniowana liczba niezależnych eventów na strategię (protokół) | ranking nie poprawia ROI vs reguły |
| 19 | Shrinkage słabo reprezentowanych strategii/reżimów do wspólnego prioru | BRAK_DOWODU | jw. | – |
| 20 | Meta-labeling (ML ocenia POPRAWNY setup, nie obchodzi warunków) | DO_BADANIA | SHADOW ≥ okres forward | brak poprawy wartości polityki |
| 21 | Wybór modelu i progu wg wartości polityki w czasie, osobny blok progu / cross-fitting | DO_BADANIA | – | próg wybrany na tym samym bloku co kalibracja |
| 22 | Drift z powrotem do reguł bazowych | istnieje (`ml/service._monitor`) – weryfikacja | – | – |
| 23 | Wkład Claude jako filtra (OFF/ADVISORY/VETO/REQUIRED) – najpierw SHADOW | DO_BADANIA | koszt API i opóźnienie mierzone | brak stabilnej poprawy E[R] → ADVISORY |
| 24 | DXY/instrumenty powiązane | BRAK_DOWODU | wiarygodne źródło as-of | brak wkładu w ablation |
| 25 | Zarządzanie ekspozycją/DD jako osobne badanie ryzyka (bez utożsamiania lewara z przewagą) | DO_BADANIA | – | – |
| 26 | Monitor warunków / braków / kosztów / unieważnienia | wdrożone w 1.8–1.10 (strona „Warunki setupu”) | – | – |
| 27 | Panel porównania strategii z liczebnością i niepewnością (nie tylko winrate) | DO_BADANIA (UI) | dane | – |

## D. Odrzucone

| Propozycja | Powód |
|---|---|
| Martingale / uśrednianie straty | zwiększa ryzyko ruiny, brak mechanizmu przewagi |
| Handel bez SL / rozszerzanie SL po stracie | narusza budżet ryzyka |
| Zwiększanie częstości wejść dla aktywności | koszty rosną liniowo, przewaga nie |
| Wybór parametrów po najwyższym wyniku historii | overfitting (wielokrotne testowanie) |
| Większa dźwignia jako „lepsza strategia” | zmienia ryzyko, nie expectancy |
| Arbitralne dokładanie wskaźników | brak mechanizmu, rośnie liczba prób |

## E. 5–10 zmian o najlepszym stosunku uzasadnienia do nakładu (kolejność wdrożenia)

1. P0-1 wspólna polityka wyjścia (bez niej żadna metryka nie jest porównywalna).
2. P0-3 rozliczanie partials + UNSETTLED.
3. P0-2 kursor TP1→BE w etykietach.
4. P0-4 jedno źródło kosztów w ML.
5. P0-5 S11 None / RR_FROM_FILL.
6. P0-6 stan TP1 z wykonania.
7. P0-7/8 uczciwe porównanie modeli i purging.
8. P1-17 pomiar poślizgu/latencji (dane do dalszych badań).
9. P1-8 filtr pełnego kosztu (pierwsza hipoteza – najprostszy mechanizm).
10. P1-14 porównanie polityk wyjścia (największy potencjalny wpływ na ROI vs WR).

Punkty 1–7 wdrożono w 1.10.0 (każdy z testem; rollback = ZIP 1.9.0 + kopia `data\`). Punkty 8–10 wymagają danych brokera.

## F. Co podnosi winrate, co ROI, gdzie kompromis (hipotezy)

* **Winrate ↑, ROI niepewne:** partial TP1 + BE (14), szerszy SL (13), ścisłe triggery (11). Ryzyko: mniejsza średnia wygrana.
* **ROI ↑, winrate ↔/↓:** filtr kosztów (8), brak gonienia ceny (12), polityka bez BE z celem strukturalnym (14).
* **Ryzyko ↓:** deduplikacja (10), news (16), ekspozycja (25).
* Pomiar (P0) może początkowo **obniżyć** raportowany winrate/ROI – to nie pogorszenie bota, tylko usunięcie zawyżeń.
