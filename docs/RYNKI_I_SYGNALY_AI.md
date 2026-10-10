# Skaner rynków i sygnały AI (1.5.0)

## Skaner wszystkich rynków (`backend/masterquo/markets/`)
Analizuje symbole z **Twojego terminala MT5** – tylko odczyt, najniższy priorytet zapytań (pętla symbolu głównego ma pierwszeństwo).

| Źródło (`markets.source`) | Co skanuje |
|---|---|
| `MARKET_WATCH` (domyślnie) | symbole widoczne w oknie Market Watch – bez zmian w terminalu |
| `LIST` | dokładne nazwy brokera z `markets.symbols` (ukryte są dodawane do Market Watch) |
| `ALL` | wszystkie symbole terminala, do `max_symbols` (ukryte są dodawane do Market Watch) |

Dla każdego symbolu, z **zamkniętych** świec H1/H4/D1:
- trend EMA20/50/200 na H1/H4/D1;
- RSI14, ADX14, ATR14, kanał Donchiana 20;
- zmiana D1 i 5D;
- reżim rynku: trend ↑/↓, konsolidacja, wysoka zmienność albo mieszany;
- poziomy dzienne i IV walls (ten sam moduł co dla XAUUSD-);
- położenie ceny w σ;
- spread względem ATR H1.

Skaner dodaje też **obserwacje**:
- korekta do EMA20 w trendzie;
- wybicie z kanału Donchiana;
- cena przy IV wall;
- RSI D1 skrajne;
- wysoki spread.

**Ranking 0–100** służy tylko do ułożenia listy do przeglądu – to heurystyka, nie prawdopodobieństwo i nie sygnał.

Strategie S01–S10, decyzje, ryzyko i zlecenia bota **nadal działają wyłącznie na symbolu głównym** (`mt5.symbol`, domyślnie XAUUSD-).

## Sygnały AI (`backend/masterquo/agent/signals.py`)
Claude (ten sam klucz, model i dzienny budżet co agent) przygotowuje dla wybranego rynku **BUY / SELL / NO_TRADE**:
- wejście MARKET albo LIMIT;
- SL;
- 1–3 TP;
- pewność modelu;
- horyzont i ważność;
- uzasadnienie, warunek unieważnienia i ryzyka.

Model widzi zamrożony kontekst przez narzędzia tylko do odczytu:
- przegląd rynku;
- świece M15–D1;
- wskaźniki;
- poziomy zmienności;
- kontekst makro, oznaczony jako dane zewnętrzne;
- historię własnych sygnałów.

Dla symbolu głównego dostaje też stan silnika MasterQUO.

**Walidacja deterministyczna:**
- SL i TP po właściwej stronie;
- TP w kolejności;
- SL ≥ `min_sl_atr_h1` × ATR H1 i ≤ `max_sl_atr_d1` × ATR D1;
- R:R do TP1 ≥ `min_rr`;
- LIMIT po właściwej stronie ceny i nie dalej niż `max_entry_distance_atr_h1` × ATR H1;
- spread ≤ 50% ryzyka.

Propozycja niezgodna z tymi regułami dostaje status **REJECTED** i jest pokazana z powodem.

**Rozliczanie** na świecach M15 (Bid), co 60 s:
- LIMIT czeka na dotknięcie ceny do końca ważności (EXPIRED);
- w świecy wejścia liczy się tylko SL;
- SL i TP w tej samej świecy = strata;
- ostatni TP = WIN; osiągnięcie wcześniejszego TP jest zapisywane (TP1, TP2);
- po `max_hold_hours` sygnał jest zamykany po ostatniej cenie (TIMEOUT).

Statystyki: win rate, średni wynik w R, liczba sygnałów. Wynik nie zawiera spreadu, prowizji ani poślizgu.

**Sygnały nie są wysyłane do terminala** – to propozycje do Twojej oceny. Bot nie składa na ich podstawie zleceń.

Automatyczne sygnały są domyślnie wyłączone (`ai_signals.auto_top_n = 0`). Gdy je włączysz, Claude analizuje N najwyżej ocenionych rynków co `auto_interval_minutes` minut. Każde zapytanie kosztuje i wlicza się do dziennego budżetu.

## API
- `GET /api/v1/markets`
- `POST /api/v1/markets/scan`
- `GET /api/v1/markets/symbols?all=1`
- `GET /api/v1/markets/detail?symbol=`
- `GET /api/v1/markets/chart?symbol=&tf=`
- `GET|POST /api/v1/ai-signals`
- `GET /api/v1/ai-signals/{id}`

## Ograniczenia
- Analiza innych rynków jest ogólna. Strategie MasterQUO S01–S10 i ML są skalibrowane pod złoto i na innych symbolach nie działają.
- Jakość sygnałów AI nie jest znana z góry – oceniaj ją po statystykach z wielu sygnałów, najlepiej na DEMO.
- „Pewność” to subiektywna ocena modelu, nie prawdopodobieństwo zysku.
- Symulator (`--demo`) ma rynki syntetyczne (EURUSD-, GBPUSD-, USDJPY-, US30-, ukryte XAGUSD- i BTCUSD-). To nie są notowania.
