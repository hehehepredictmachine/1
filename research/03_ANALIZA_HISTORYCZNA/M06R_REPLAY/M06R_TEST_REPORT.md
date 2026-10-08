# Audyt M06R v1.0.0-CANDIDATE

**Testy offline, wyłącznie dane symulowane i lokalne kopie oryginalnych referencyjnych silników.**

| Zakres | Liczba testów | Wynik |
|---|---:|---|
| M06R_TESTS (historyczne wejście, PIT, lifecycle, eksporter) | 57 | PASS |
| M06R_INTEGRITY_MACRO_TESTS (SHA-256, SHORT, archiwum wydarzeń) | 20 | PASS |
| M06H_TESTS (niezmieniona walidacja poprzedniego M06H) | 76 | PASS |
| M07_M03E_PROFILE_TESTS (niezmieniony detektor M07) | 61 | PASS |
| **Nowy zestaw i integracje** | **214** | **PASS** |
| M02_TESTS | 67 | PASS |
| M03_TESTS | 64 | PASS |
| M02I_TESTS + M02I_TIMEFRAME_PROFILE_TESTS | 133 | PASS |
| **Wszystkie zestawy wykonane osobno** | **478** | **PASS** |

Nie były to rzeczywiste testy terminala MetaTrader 5 u użytkownika ani backtest na rzeczywistych tickach, a 478 testów obejmuje poprzednie silniki; nie oznacza 478 niezależnych testów nowych strategii.

## Scenariusze bezpieczeństwa

- Świeca otwarta / future available / błędny OHLC / niezgodny symbol / cofnięty czas / duplikat: odrzucenie.
- Brak jednego z sześciu timeframe: przerwanie zamiast uzupełniania syntetycznym resamplingiem D1/H4.
- Wymagana nowa zamknięta świeca dla każdej kolejnej fazy; na tej samej świecy nie ma pięciu potwierdzeń.
- Unieważnienie wyprzedza potwierdzenie; dłuższa przerwa w setup TF prowadzi do GAP_REVIEW.
- Znane z wyprzedzeniem CPI może dawać ostrzeżenie makro; publikacja poznana dopiero później nie działa wstecz.
- Pliki po eksporcie zmienione w sposób niezgodny z SHA-256 są odrzucane. SHA-256 nie potwierdza oryginalnego pochodzenia brokera.
- Przepływ bez ticków Bid/Ask i rzeczywistych kosztów: `strategy_net_performance.status=NOT_RUN`.
- Żadnych zleceń i automatycznej zgody na handel: `BLOCKED`.

## Test integracyjny CLI

Przykład na syntetycznych 260 świecach każdego TF: 3/3 kroki przetworzone przez M02/M02I/M03 ze statusem PASS, 0 kompletnych setupów, 0 CONFIRMED, wynik netto NOT_RUN. Raport JSON poprawny składniowo. W demonstracji świadomie ograniczono replay do 3 kroków, więc pole `truncated_by_step_limit` ma wartość `true`.

## Niezweryfikowane

1. Rzeczywista historia świec i ticków użytkownika z terminala MT5 Zero.
2. Audyt brakujących świec, rewizji danych brokera, jakości spójności wielointerwałowej.
3. Głęboka walidacja OOS i walk-forward z zamrożonymi profilami.
4. Ceny wejścia/SL/TP, prowizja/poślizg/swap, rzeczywiste wyniki netto.
5. Zyskowność, win-rate, stabilność przy różnych sesjach i newsach, forward DEMO.

Status: **CANDIDATE / PENDING APPROVAL**. Brak produkcyjnego wdrożenia.
