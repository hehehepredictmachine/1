# M06H — audyt danych / metodologia

**Ziarno danych**: 1 rekord = świeca M1 XAUUSD od konkretnego brokera; 1 rekord zdarzenia = rozpoznany publikacyjny termin w UTC; 1 rekord transakcji = sygnał weryfikowany przez oryginalne M06 na tickach z tego samego symbolu. `source_id` jest etykietą, a nie kryptograficzną certyfikacją feedu.

**Czas i lookahead:** brak lokalnych naiwnych timestampów. Zdarzenia kalendarzowe przyszłe można było znać z wyprzedzeniem jedynie przy potwierdzonym zapisie przed decyzją. Późniejsze poprawki i dopisane wartości `actual` nie mogą tworzyć historycznej wiedzy wstecz. Horyzont zamknięcia świecy musi mieścić się w jednym foldzie, inaczej `PURGED_FOLD_BOUNDARY`. Analiza ruchu po wiadomościach jest retrospektywnym opisem, nie polityką decyzyjną.

**Porównywalność:** kontrola z tego samego UTC minute-of-day w innym dniu i w obrębie folda; nie jest to dopasowanie do pełnych warunków zmienności/sezonowości. Wykluczono kontrolne okna ±`control_blackout_minutes` od istniejących wydarzeń; nieznane wydarzenia nadal stanowią potencjalne zakłócenie. Ten sam dzień eventów grupuje bootstrap (brak sztucznej niezależności trzech horyzontów).

**Kontrola próbek**: liczone są braki M1, brak kontrolnych par, odrzucone przypadki poza foldem i brak przynajmniej `min_final_oos_events`. Jakość nie może wynikać wyłącznie z wysokiej liczby pojedynczych minut przy niewielkiej liczbie publikacji. Dodatnia `mean_excess_abs_bp` nie oznacza wzrostu win rate ani poprawy wyników netto.

**Potencjalne biasy**: dobór czasu dnia, wyłącznie dostępnych danych brokera, niepełność kalendarzy BLS/FF/MM, wielokrotne testowanie horyzontów, revised macro times, brak kwotowań w godzinach skrajnego spreadu, reakcja w tej samej minucie co publikacja, przerwy rynkowe/weekendy. Bez szerokiej próbki i niezależnej weryfikacji nie wyciągać wniosków przyczynowych.

**Metryki strategii**: powstają tylko przez oryginalny M06 ze sprawdzalnym sygnałem, Bid/Ask i prowizją. `M06H` porównuje usunięte transakcje, nie dokłada nowych wejść i nie modeluje rebalansowania kapitału. Warianty kosztów stresowych z M06 są wyłącznie scenariuszami, nie potwierdzonym taryfikatorem brokera. Foldami musi zarządzać ten sam, zamrożony protokół dla M06H i M06.

**Wynik audytu**: gotowy *techniczny silnik badawczy* na wejściu kontrolowanym. **Brak dostarczonej historii rzeczywistych sygnałów, ticków brokera i wielomiesięcznego archiwum M04N**, więc aktualny projekt nie może ogłosić ani dodatniego expectancy, ani procentowej skuteczności. Do przejścia dalej: archiwizować feed, zebrać M1 i ticki, zbudować point-in-time ledger z zamrożonych strategii, wykonać kosztowy walk-forward/OOS i forward DEMO.
