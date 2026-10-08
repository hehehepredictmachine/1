# MasterQUO M06T — raport walidacji

Status: **RESEARCH_ONLY**

Sygnały wejściowe: 2; rozliczalne kandydaty: 2.

| Tryb | Wszystkie zakończone | OOS zakończone | Średnia R OOS |
|---|---:|---:|---:|
| MVP | 1 | 0 | N/D |
| SMC | 1 | 1 | -1.50892857 |
| SCALPING | 0 | 0 | N/D |

## Ograniczenia

Wynik jest badawczą symulacją kwotowań, a nie historią faktycznych zleceń MT5.
Nie ma autoryzacji LIVE ani udowodnionej przewagi OOS. Braki ticków, niezarejestrowane koszty i niekompletny kalendarz ograniczają wnioski.

## Weryfikacja

- Wymagany eksport ticków Bid/Ask od brokera, historia sygnałów i dziennik M06R.
- Zamrożone parametry wejścia, wolumen, koszty, zakresy DEV/OOS.
- Wynik netto w M06 nie jest faktycznym wykonaniem zleceń.
