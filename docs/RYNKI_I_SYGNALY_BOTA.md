# Skaner rynków i sygnały bota (1.6.0)

## Skąd są sygnały
Sygnały pochodzą **z Twojego bota** – ze strategii MasterQUO S01–S10. Agent AI (Claude) ich nie tworzy.

Sygnał powstaje, gdy strategia bota potwierdzi setup (etap **CONFIRMED**). Obowiązują te same progi wyniku, parametry i przełączniki strategii
co w zakładce **AUTO / ACTIVE**.

| Rynek | Kto liczy |
|---|---|
| Symbol główny (`mt5.symbol`, domyślnie XAUUSD-) | silnik bota: zdarzenia NEW_CONFIRMED / STAGE_CONFIRMED z ActiveEngine |
| Pozostałe skanowane rynki | skaner uruchamia S01–S10 na świecach M5/M15/H1/H4/D1 danego symbolu z terminala |

## Jak wygląda sygnał
- **Kierunek** – ze strategii.
- **Wejście** – cena w chwili potwierdzenia: Ask dla BUY, Bid dla SELL. Strategie mają plan `MARKET_ON_CONFIRMATION`.
- **SL i cele** – ze strategii, cele z wagami.
- **Wynik setupu** – liczba 0–100 ze strategii.

Pełny opis (wyzwalacz, unieważnienie, powody, brakujące potwierdzenia, punkty wyniku) jest w oknie sygnału.

## Reguły bota (sygnał niespełniający ich ma status ODRZUCONY i jest pokazany z powodem)
- SL i cele muszą być po właściwej stronie ceny.
- Cena nie może odjechać od poziomu wyzwalacza dalej niż `max_distance_atr` z planu strategii.
- **R:R ważony wagami celów** musi być co najmniej równy `risk.rr_block_below` („RR netto – blokada poniżej” w zakładce Ryzyko). To ten sam próg, którego używa bot.
- Spread nie może przekraczać 50% ryzyka.

Bot nie dubluje sygnałów:
- jeden setup daje jeden sygnał;
- kilka strategii opisujących to samo zdarzenie rynkowe, gdy otwarty jest już sygnał, daje jeden sygnał.

## Rozliczanie i statystyki
Rozliczanie odbywa się co 60 s na świecach M15 (Bid):
- ostatni cel = **WIN**; osiągnięcie wcześniejszego celu jest zapisywane (TP1, TP2);
- SL = **LOSS**;
- SL i TP w tej samej świecy = strata;
- po `signals.max_hold_hours` sygnał jest zamykany po ostatniej cenie (**TIMEOUT**).

Statystyki pokazują win rate, średni wynik w R oraz liczbę sygnałów otwartych i odrzuconych. Wynik nie zawiera spreadu, prowizji ani poślizgu.

## Zlecenia
Zlecenia może składać **wyłącznie symbol główny**, przez dotychczasową ścieżkę: tryb wykonania, moduł ryzyka i bramka. Bez zmian.

Sygnały innych rynków to informacja dla Ciebie, z opcjonalnym powiadomieniem na Telegram. Bot nie wysyła dla nich zleceń.

## Skaner rynków
**Źródło symboli** (`markets.source`):
- `MARKET_WATCH` (domyślnie) – symbole z okna Market Watch;
- `LIST` – Twoja lista symboli;
- `ALL` – wszystkie symbole terminala, do `max_symbols`. Ukryte symbole są dodawane do Market Watch.

**Domyślny odstęp skanów:** 120 s.

**Dla każdego rynku:**
- trend H1/H4/D1, RSI, ADX, ATR;
- reżim rynku;
- Daily High/Low i IV walls;
- położenie ceny w σ;
- spread vs ATR;
- obserwacje i ranking do przeglądu (heurystyka);
- kolumna **Setup bota** – najlepszy setup S01–S10 na danym rynku (etap i wynik).

## Ustawienia (Ustawienia → Rynki / Sygnały bota)
- `signals.enabled` – włącza sygnały.
- `signals.scan_other_markets` – S01–S10 na pozostałych rynkach.
- `signals.max_hold_hours` – maksymalny czas trwania sygnału.
- `signals.telegram` – powiadomienie Telegram.
- Ustawienia skanera: `markets.*`.

## API
- `GET /api/v1/markets`
- `POST /api/v1/markets/scan`
- `GET /api/v1/markets/detail|chart`
- `GET /api/v1/bot-signals`
- `GET /api/v1/bot-signals/{id}`

## Ograniczenia
- Strategie S01–S10 powstały dla XAUUSD-. Parametry są względne (w ATR), więc działają na każdym rynku, ale **nie były testowane OOS na innych instrumentach**. Oceniaj je po statystykach, najlepiej na DEMO.
- Na symbolu głównym ML (tryb ASSIST) może zmieniać ranking wyboru strategii. Sygnały powstają jednak z każdego potwierdzonego setupu, a nie tylko z wybranego.
- Symulator (`--demo`) ma rynki syntetyczne – to nie są notowania.
