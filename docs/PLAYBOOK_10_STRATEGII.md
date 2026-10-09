# Playbook – 10 strategii ACTIVE (S01–S10)

Wygenerowane z kodu (`python tools/make_strategy_cards.py`). Wszystkie strategie: **status walidacji FUNCTIONAL_ONLY_OOS_NOT_RUN** – kompletne,
uruchamialne i przetestowane funkcjonalnie (testy syntetyczne), **bez** potwierdzonej skuteczności na XAUUSD-. Parametry są robocze (nie zoptymalizowane).

Wspólne dla wszystkich (kontrakt MQ-STRATEGY-CONTRACT-1.0.0):
* reguła LONG zapisana raz; SHORT = ta sama reguła na cenach odbitych lustrzanie (p' = 2C − p) – identyczna logika obu kierunków,
* etapy: WATCH (struktura rozpoznana) → EARLY (formacja rozwija się / trigger na świecy tworzącej się) → CONFIRMED (prawdziwy trigger na ZAMKNIĘTEJ świecy + wynik ≥ progu),
* punktacja ACTIVE 0–100: struktura 25, formacja 25, momentum 20 (RSI/MACD/EMA jako JEDNA kategoria – mediana głosów), trigger 15, kontekst HTF 10, dodatkowe 5 (DXY – obecnie niedostępne → 0 pkt, bez skracania mianownika),
* zlecenie: rynkowe po zamknięciu świecy wyzwalającej, wyłącznie przez wspólny gateway i moduł ryzyka (sizing, RR netto, koszty); SL dla SHORT + spread (stop na Ask),
* deduplikacja: setup_id = hash(symbol, rachunek, strategia, kierunek, TF, klucz struktury) – odświeżenia aktualizują wersję; event_id grupuje strategie opisujące ten sam ruch,
* ważność: liczba świec TF setupu (`expires_bars`), po CONFIRMED okno wejścia 3 świece → MISSED_ENTRY; unieważnienie natychmiastowe,
* restart: stan w SQLite (`strategy_setups`), ale po starcie aktywne setupy są oznaczane RESTART_REVALIDATION i wracają tylko po ponownym wykryciu na świeżych danych,
* cooldown: detekcji – brak (struktura publikowana raz, unieważniona nie wraca); powiadomień – tylko EARLY/CONFIRMED/unieważnienie; zleceń – UNIQUE entry_key (1 wejście na setup).

## S01 — TREND_PULLBACK (v1.0.0-EXPERIMENTAL)

**Hipoteza:** W istniejącym trendzie korekta do strefy wartości (EMA20–EMA50) częściej kończy się kontynuacją niż odwróceniem.

**Źródło inspiracji (dostęp):** Grimes – pullback w trendzie jako podstawowy setup kontynuacji; Kaufman – systemy podążania za trendem (METADATA_ONLY, reguła SOURCE_UNVERIFIED)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Trend = EMA20>EMA50, nachylenie EMA50 i ER(20); korekta mierzona w ATR (1–3,5); strefa EMA50−0,25ATR..EMA20+0,25ATR; reakcja = zamknięcie nad high poprzedniej świecy.

**Warunek wyróżniający:** wymagana rozpoznana korekta (nie nowe maksimum)

**Reżim i horyzont:** dopasowanie do reżimu: TREND_UP 1.0, TREND_DOWN 1.0, TRANSITION 0.5, EXPANSION 0.4, COMPRESSION 0.2, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.2, RANGE 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 80 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S01 TREND_PULLBACK - continuation of an existing trend after a measured correction.

LONG rules (SHORT = mirrored prices), setup TF in p["tfs"] (M5, M15), context H1:
  necessary  trend: EMA20 > EMA50, EMA50 slope (10 bars) >= min_slope ATR/bar, ER(20) >= min_er
             swing: the highest high of the last `swing_lookback` bars (impulse extreme) is >= 2 bars old
             correction: depth from that high to the lowest low since = min_depth..max_depth ATR,
                         no close below EMA50 - deep_close_atr x ATR (that would be a trend failure)
  WATCH      trend + correction >= 0.5 x min_depth in progress
  EARLY      a bar (closed in the last `zone_bars`, or the forming bar) traded into the value zone
             [EMA50 - 0.25 ATR, EMA20 + 0.25 ATR]
  TRIGGER    after the zone contact a CLOSED bar closes above the previous bar's high with a bullish body
  invalid.   close below the correction low - 0.2 ATR (CLOSE_BEYOND)
  SL         correction low - sl_buffer ATR (+spread for SHORT)
  targets    TP1 = impulse extreme (retest of the high), TP2 = measured move: entry + impulse length
  exit       time exit after `time_exit_bars`; SL to BE after TP1
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "min_slope": 0.02, "min_er": 0.25, "swing_lookback": 30, "min_depth_atr": 1.0, "max_depth_atr": 3.5, "deep_close_atr": 0.5, "zone_bars": 3, "sl_buffer_atr": 0.2, "time_exit_bars": 36, "expires_bars": 12}`

**Wyjście i zarządzanie:** TP1 = ekstremum impulsu, TP2 = zasięg impulsu od wejścia; BE po TP1; wyjście czasowe 36 świec.

**Near-miss:** korekta < 1 ATR lub brak kontaktu ze strefą → EARLY/WATCH.  **Unieważnienie:** zamknięcie poniżej dołka korekty − 0,2 ATR.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S02 — ADAPTIVE_TREND (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Gdy efektywność ruchu (ER) rośnie, adaptacyjna średnia szybko podąża za ceną; zmiana stanu trendu daje wejście w nowy ruch.

**Źródło inspiracji (dostęp):** Kaufman – Adaptive Moving Average (KAMA) i efficiency ratio (METADATA_ONLY; formuła KAMA szeroko opublikowana, tekst książki niezweryfikowany)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** KAMA(10,2,30) na M15/H1; pasmo histerezy 0,3 ATR (własna adaptacja zamiast filtra z odchylenia KAMA); wejście tylko przy ZMIANIE stanu.

**Warunek wyróżniający:** zmiana stanu trendu (nie korekta jak S01)

**Reżim i horyzont:** dopasowanie do reżimu: TREND_UP 0.9, TREND_DOWN 0.9, TRANSITION 0.7, EXPANSION 0.6, COMPRESSION 0.3, RANGE 0.1, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.1. TF setupu: M15, H1; kontekst: H4; wymagane dane: M15; min. historia: 60 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S02 ADAPTIVE_TREND - trend following with Kaufman's adaptive moving average (KAMA) and ER.

Entry is a CHANGE of the trend state (not a pullback - that is S01). LONG (SHORT mirrored):
  KAMA(er_n=10, fast=2, slow=30) on the setup TF; band = KAMA + band_atr x ATR14 (hysteresis).
  state UP   = close > KAMA + band, KAMA rising over 3 bars; DOWN symmetric; otherwise NEUTRAL.
  necessary  ER(er_n) >= min_er at the trigger bar; previous closed bar NOT in state UP
  WATCH      ER >= 0.6 x min_er, close within 1 ATR below the upper band, KAMA flat or rising
  EARLY      close above KAMA but not above the band yet, or the forming bar above the band
  TRIGGER    CLOSED bar: state turns UP (previous bar not UP)
  invalid.   close below KAMA - band_atr x ATR (state flips back) - level frozen at detection
  SL         min(lowest low of last 5 bars, KAMA - 1 ATR) - 0.2 ATR (+spread for SHORT)
  exit       trailing: close back below KAMA - band (exit_rules.trailing=KAMA_STATE_FLIP);
             TP1 1.5R (partial), TP2 3R - fixed multiples because the hypothesis has no structural target
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M15", "H1"], "er_n": 10, "fast": 2, "slow": 30, "band_atr": 0.3, "min_er": 0.3, "time_exit_bars": 48, "expires_bars": 4}`

**Wyjście i zarządzanie:** trailing: powrót pod KAMA − pasmo; TP1 1,5R, TP2 3R (brak celu strukturalnego w hipotezie).

**Near-miss:** ER < 0,3 przy przecięciu → EARLY.  **Unieważnienie:** zamknięcie poniżej KAMA − pasmo (poziom z chwili wykrycia).

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S03 — CHANNEL_BREAKOUT (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Wybicie poza zakres N poprzednich świec sygnalizuje początek ruchu kierunkowego.

**Źródło inspiracji (dostęp):** Kaufman – breakout kanału (Donchian) jako klasyczny system (METADATA_ONLY, reguła SOURCE_UNVERIFIED)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Kanał z 20 świec POPRZEDZAJĄCYCH (świeca wybicia nie ustala progu); bufor 0,1 ATR; limit wielkości świecy 2,5 ATR (bez gonienia).

**Warunek wyróżniający:** przebicie kanału z historii

**Reżim i horyzont:** dopasowanie do reżimu: EXPANSION 1.0, COMPRESSION 0.6, TREND_UP 0.6, TREND_DOWN 0.6, TRANSITION 0.5, RANGE 0.3, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 60 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S03 CHANNEL_BREAKOUT - Donchian channel breakout.

LONG (SHORT mirrored). Channel = highest high / lowest low of the N bars BEFORE the evaluated bar
(the breakout bar never sets its own threshold).
  necessary  channel width >= min_width_atr x ATR (a 1-bar-wide "channel" is noise)
  WATCH      close within watch_dist_atr x ATR below the upper channel
  EARLY      forming bar trades above the channel, or the closed bar broke it intrabar
             (high > upper) without closing beyond the buffer
  TRIGGER    CLOSED bar closes above upper + buffer_atr x ATR and its range <= max_bar_atr x ATR
             (a larger bar = chasing -> stays EARLY with BREAKOUT_BAR_TOO_LARGE)
  invalid.   close back below the channel midpoint
  SL         upper - sl_atr x ATR (back well inside the channel) (+spread for SHORT)
  targets    measured move: TP1 = upper + 0.5 x width, TP2 = upper + 1.0 x width
  exit       time exit; BE after TP1
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "n": 20, "min_width_atr": 2.0, "watch_dist_atr": 0.5, "buffer_atr": 0.1, "max_bar_atr": 2.5, "sl_atr": 1.0, "time_exit_bars": 30, "expires_bars": 4}`

**Wyjście i zarządzanie:** TP = połowa i cała szerokość kanału; BE po TP1.

**Near-miss:** świeca > 2,5 ATR → EARLY (BREAKOUT_BAR_TOO_LARGE).  **Unieważnienie:** zamknięcie poniżej środka kanału.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S04 — VOLATILITY_COMPRESSION_BREAKOUT (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Po okresie niskiej zmienności częściej następuje jej ekspansja; kierunek wyznacza wyjście z pudełka kompresji.

**Źródło inspiracji (dostęp):** Kaufman/Chan – zmienność i reżimy (METADATA_ONLY, SOURCE_UNVERIFIED); własna formalizacja percentylowa

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Kompresja = percentyl szerokości Bollingera ≤ 15% z 120 świec przez ≥ 5 świec, pudełko znane przed świecą sygnału; odległość wejścia ≤ 1 ATR.

**Warunek wyróżniający:** historyczna kompresja (nie sam kontakt z kanałem)

**Reżim i horyzont:** dopasowanie do reżimu: COMPRESSION 1.0, EXPANSION 0.8, TRANSITION 0.5, RANGE 0.5, TREND_UP 0.3, TREND_DOWN 0.3, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 150 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S04 VOLATILITY_COMPRESSION_BREAKOUT - expansion out of a previously recognised compression.

The distinguishing condition is the historical compression, not a channel touch (that is S03).
  compression bar  Bollinger width(20,2) percentile among the previous `pct_lookback` bars <= max_pct
  box              >= min_bars_in_box consecutive compression bars ending no more than `max_box_age`
                   bars before the evaluated bar (the evaluated bar never defines its own box);
                   box = their high/low; box height <= max_box_atr x ATR
  LONG (SHORT mirrored)
  WATCH      compression box active (the last closed bar is still a compression bar), price nearer the top
  EARLY      forming bar above the box, or close above the box by less than the buffer
  TRIGGER    CLOSED bar closes above box top + buffer_atr x ATR, entry distance from the top
             <= max_entry_atr x ATR (else TOO_FAR_FROM_BOX - no chasing)
  invalid.   close back below the box midpoint
  SL         box midpoint - 0.1 ATR (+spread for SHORT)
  targets    TP1 = top + 1 x box height, TP2 = top + 2 x box height
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "pct_lookback": 120, "max_pct": 0.15, "min_bars_in_box": 5, "max_box_age": 6, "max_box_atr": 3.0, "buffer_atr": 0.15, "max_entry_atr": 1.0, "time_exit_bars": 24, "expires_bars": 3}`

**Wyjście i zarządzanie:** TP = 1× i 2× wysokość pudełka.

**Near-miss:** zamknięcie za daleko od pudełka → EARLY (TOO_FAR_FROM_BOX).  **Unieważnienie:** zamknięcie z powrotem poniżej środka pudełka.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S05 — SESSION_RANGE_BREAKOUT (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Zakres początkowego okna sesji wyznacza poziomy, których wybicie w oknie handlu ma kierunkową kontynuację.

**Źródło inspiracji (dostęp):** Koncepcja opening range breakout – literatura ogólna (SOURCE_UNVERIFIED); godziny sesji = konfiguracja do zbadania na feedzie brokera

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Londyn 08:00 Europe/London (60 min), Nowy Jork 08:30 America/New_York (30 min); DST przez zoneinfo; zakres zamrożony po zamknięciu ostatniej świecy okna.

**Warunek wyróżniający:** zamrożony zakres sesji

**Reżim i horyzont:** dopasowanie do reżimu: EXPANSION 1.0, COMPRESSION 0.7, TRANSITION 0.6, TREND_UP 0.5, TREND_DOWN 0.5, RANGE 0.4, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.1. TF setupu: M5; kontekst: H1; wymagane dane: M5; min. historia: 40 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S05 SESSION_RANGE_BREAKOUT - breakout of an initial session range (opening range).

Sessions are configuration studied on the broker feed (an OTC gold CFD has no single exchange
open). Each session: local start time in an IANA time zone (DST handled by zoneinfo), range
length and trading window. Bars are M5 in UTC.
  range      high/low of the M5 bars inside [start, start + range_minutes); frozen only after the
             last bar of the window has CLOSED and >= 80% of the expected bars exist
  LONG (SHORT mirrored), only inside [range end, range end + trade_minutes)
  WATCH      range frozen, price inside it
  EARLY      forming bar above the range, or close above it by less than the buffer
  TRIGGER    CLOSED M5 bar closes above range high + buffer_atr x ATR(M5)
  invalid.   close back below the range midpoint; the setup expires at the end of the window
  SL         range midpoint (range >= 1 ATR) or range low (narrow range) - 0.1 ATR (+spread SHORT)
  targets    TP1 = high + 1 x range, TP2 = high + 2 x range
  dedupe     one setup per session, date and side
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"sessions": [{"name": "LONDON", "tz": "Europe/London", "start": "08:00", "range_minutes": 60, "trade_minutes": 180}, {"name": "NEW_YORK", "tz": "America/New_York", "start": "08:30", "range_minutes": 30, "trade_minutes": 150}], "buffer_atr": 0.1, "min_coverage": 0.8, "time_exit_bars": 36}`

**Wyjście i zarządzanie:** TP = 1× i 2× zakres; wygaśnięcie z końcem okna handlu.

**Near-miss:** wybicie bez zamknięcia ponad bufor → EARLY.  **Unieważnienie:** zamknięcie poniżej środka zakresu.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S06 — BREAKOUT_RETEST (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Przebity poziom, który po powrocie utrzymuje się (retest), potwierdza zmianę roli poziomu.

**Źródło inspiracji (dostęp):** Grimes – wybicie i test poziomu (METADATA_ONLY, SOURCE_UNVERIFIED)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Poziom = potwierdzony pivot 3/3; sekwencja wybicie → retest (low ≤ poziom + 0,3 ATR) → reakcja (zamknięcie nad high świecy retestu ≤ 3 świece).

**Warunek wyróżniający:** obowiązkowa sekwencja wybicie→retest→reakcja

**Reżim i horyzont:** dopasowanie do reżimu: EXPANSION 0.8, TREND_UP 0.8, TREND_DOWN 0.8, TRANSITION 0.6, COMPRESSION 0.4, RANGE 0.3, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 80 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S06 BREAKOUT_RETEST - break of a confirmed level, return to it, reaction.

The sequence break -> retest -> reaction is mandatory; before the retest only WATCH/EARLY exist.
LONG (SHORT mirrored):
  level      most recent confirmed swing high (pivot 3/3) known before the break, max age `level_age`
  break      a CLOSED bar k (within the last `max_since_break` bars) closes above level + buffer
  WATCH      break done, no retest yet, price <= level + watch_dist_atr x ATR above the level
  EARLY      retest: a bar after k (closed or forming) with low <= level + retest_tol_atr x ATR and no close
             below level - fail_atr x ATR
  TRIGGER    CLOSED bar after the retest bar (<= 3 bars later) closes above the retest bar high
  invalid.   close below level - fail_atr x ATR
  SL         min(retest low, level) - 0.2 ATR (+spread for SHORT)
  targets    TP1 = highest high since the break, TP2 = 2R
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "level_age": 60, "max_since_break": 20, "buffer_atr": 0.1, "watch_dist_atr": 2.0, "retest_tol_atr": 0.3, "fail_atr": 0.5, "time_exit_bars": 30, "expires_bars": 6}`

**Wyjście i zarządzanie:** TP1 = maksimum po wybiciu, TP2 = 2R.

**Near-miss:** brak retestu → WATCH; retest bez reakcji → EARLY.  **Unieważnienie:** zamknięcie poniżej poziomu − 0,5 ATR.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S07 — FAILED_BREAKOUT_RECLAIM (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Nieudane wyjście poza zakres i szybki powrót do środka często kończy się ruchem w przeciwną stronę.

**Źródło inspiracji (dostęp):** Grimes – failure test / nieudane wybicie (METADATA_ONLY, SOURCE_UNVERIFIED). Bez danych zleceń nie twierdzimy, kto „zebrał płynność”

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Poziom = dolna krawędź 20 poprzednich świec; wyjście > 0,1 ATR poza; powrót zamknięciem nad poziom + 0,1 ATR w ≤ 3 świecach.

**Warunek wyróżniający:** zaobserwowane wyjście i powrót

**Reżim i horyzont:** dopasowanie do reżimu: RANGE 0.9, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.8, TRANSITION 0.6, COMPRESSION 0.5, EXPANSION 0.4, TREND_UP 0.3, TREND_DOWN 0.3. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 60 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S07 FAILED_BREAKOUT_RECLAIM - an observed move outside a level that fails and returns inside.

Describes price behaviour only (no claim about who "took liquidity" - there is no order data).
LONG = failed breakdown below support (SHORT mirrored = failed breakout above resistance):
  level      lower edge of the prior range = min low of the N bars before the excursion (Donchian, prior bars)
  excursion  a bar k in the last `max_bars_out`+1 bars trades below level - out_atr x ATR
  WATCH      price is currently outside (last close or forming bar below the level)
  EARLY      close back above the level but by less than the buffer, or the forming bar back above it
  TRIGGER    CLOSED bar within `max_bars_out` bars after the excursion low closes above level + buffer_atr x ATR
  invalid.   close below the excursion low (CLOSE_BEYOND)
  SL         excursion low - 0.2 ATR (+spread for SHORT)
  targets    TP1 = range midpoint, TP2 = opposite range edge
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "n": 20, "min_width_atr": 1.5, "out_atr": 0.1, "max_bars_out": 3, "buffer_atr": 0.1, "time_exit_bars": 24, "expires_bars": 4}`

**Wyjście i zarządzanie:** TP = środek i przeciwna krawędź zakresu.

**Near-miss:** powrót bez bufora → EARLY.  **Unieważnienie:** zamknięcie poniżej ekstremum wyjścia.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S08 — RANGE_EDGE_REVERSION (v1.0.0-EXPERIMENTAL)

**Hipoteza:** W rozpoznanej konsolidacji odrzucenie krawędzi prowadzi do ruchu w stronę środka zakresu.

**Źródło inspiracji (dostęp):** Grimes – zakresy i ich krawędzie; Kaufman – systemy przeciwtrendowe (METADATA_ONLY, SOURCE_UNVERIFIED)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Zakres z 40 świec PRZED sygnałem: ER ≤ 0,25, wysokość 2–8 ATR, ≥ 2 dotknięcia każdej krawędzi; świeca odrzucenia zamyka się w górnej połowie.

**Warunek wyróżniający:** zakres znany przed sygnałem, bez wymogu wyjścia poza (różnica vs S07)

**Reżim i horyzont:** dopasowanie do reżimu: RANGE 1.0, TRANSITION 0.5, COMPRESSION 0.4, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.4, EXPANSION 0.1, TREND_UP 0.1, TREND_DOWN 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 70 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S08 RANGE_EDGE_REVERSION - rejection of the edge of a previously recognised consolidation.

The range must be known BEFORE the signal bar (computed on the `lookback` bars ending at i-1).
A prior excursion outside the range is NOT required (that is S07).
  range      top/bottom = max high / min low of the window; ER(lookback) <= max_er;
             height between min_h_atr and max_h_atr ATR; >= min_touches touches of each edge zone
             (bar high >= top - edge_frac x height, resp. low <= bottom + edge_frac x height),
             touches separated by >= 3 bars
  LONG (SHORT mirrored)
  WATCH      range recognised, close in the lower `watch_frac` of the range
  EARLY      the last closed (or the forming) bar trades into the lower edge zone
  TRIGGER    CLOSED rejection bar: low in the edge zone, close in the upper half of the bar and above
             bottom + edge_frac x height, no close below bottom - 0.25 ATR
  invalid.   close below bottom - 0.3 ATR
  SL         min(signal low, bottom) - 0.3 ATR (+spread for SHORT)
  targets    TP1 = range midpoint, TP2 = top - edge_frac x height
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "lookback": 40, "max_er": 0.25, "min_h_atr": 2.0, "max_h_atr": 8.0, "edge_frac": 0.15, "min_touches": 2, "watch_frac": 0.3, "time_exit_bars": 24, "expires_bars": 6}`

**Wyjście i zarządzanie:** TP = środek i przeciwna krawędź (−15%).

**Near-miss:** dotknięcie bez odrzucenia → EARLY.  **Unieważnienie:** zamknięcie poniżej dołu zakresu − 0,3 ATR.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S09 — STATISTICAL_MEAN_REVERSION (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Duże odchylenie z-score ceny od średniej kroczącej częściowo wraca – hipoteza do testu, nie założenie stacjonarności złota.

**Źródło inspiracji (dostęp):** Chan – mean reversion na odchyleniu od średniej / Bollinger (METADATA_ONLY, SOURCE_UNVERIFIED)

**Własna formalizacja i adaptacja do XAUUSD- CFD:** z = (close − SMA40)/std40; WATCH ≤ −1,5, EARLY ≤ −2; trigger = zawrócenie z i świeca wzrostowa; filtr ER(20) < 0,35 (brak silnego trendu).

**Warunek wyróżniający:** mierzalne odchylenie statystyczne (bez ręcznych granic jak S08)

**Reżim i horyzont:** dopasowanie do reżimu: RANGE 1.0, EXHAUSTION_OR_REVERSAL_CANDIDATE 0.7, TRANSITION 0.6, COMPRESSION 0.3, EXPANSION 0.3, TREND_UP 0.1, TREND_DOWN 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 60 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S09 STATISTICAL_MEAN_REVERSION - return after a measurable deviation from a rolling mean.

Hypothesis (to be tested, not assumed): a large z-score deviation of the close from its rolling
mean tends to partially revert. Price stationarity is NOT assumed; the rule is disabled in an
efficient trend (ER filter) where deviations tend to persist.
  estimator  z = (close - SMA(n)) / stdev(n), n = 40 on the setup TF
  necessary  ER(20) < max_er (no strong trend on the setup TF)
  LONG (SHORT mirrored)
  WATCH      z <= watch_z (-1.5)
  EARLY      z <= entry_z (-2.0) at the last closed bar (or the forming bar's close)
  TRIGGER    CLOSED bar: min z over the last 3 bars <= entry_z, z rising vs previous bar and a bullish close
  invalid.   close below SMA - stop_z x stdev (deviation keeps expanding), frozen at detection
  SL         min(SMA - stop_z x stdev, lowest low of 3 bars - 0.3 ATR) (+spread for SHORT)
  targets    TP1 = SMA - 1 x stdev (partial reversion), TP2 = SMA (full reversion)
  exit       time exit after `time_exit_bars` bars without reversion
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "n": 40, "watch_z": -1.5, "entry_z": -2.0, "stop_z": -3.5, "max_er": 0.35, "time_exit_bars": 20, "expires_bars": 4}`

**Wyjście i zarządzanie:** TP1 = SMA − 1σ, TP2 = SMA; wyjście czasowe 20 świec.

**Near-miss:** z nie zawraca → EARLY.  **Unieważnienie:** odchylenie rośnie do −3,5σ (poziom zamrożony).

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.

## S10 — EXHAUSTION_STRUCTURE_REVERSAL (v1.0.0-EXPERIMENTAL)

**Hipoteza:** Słabnący impuls (dywergencja lub nadmierne rozciągnięcie) z potwierdzoną zmianą struktury poprzedza odwrócenie.

**Źródło inspiracji (dostęp):** Grimes – zmiana struktury rynku; momentum/dywergencja (METADATA_ONLY, SOURCE_UNVERIFIED). Sam RSI nie jest triggerem

**Własna formalizacja i adaptacja do XAUUSD- CFD:** Impuls ≥ 3 ATR do ekstremum ≤ 12 świec temu; wyczerpanie = dywergencja RSI (+2) lub rozciągnięcie ≥ 2,5 ATR od EMA20; trigger = zamknięcie nad ostatni niższy szczyt.

**Warunek wyróżniający:** potwierdzona zmiana struktury (bez wymogu S07)

**Reżim i horyzont:** dopasowanie do reżimu: EXHAUSTION_OR_REVERSAL_CANDIDATE 1.0, TRANSITION 0.6, EXPANSION 0.4, RANGE 0.4, TREND_UP 0.3, TREND_DOWN 0.3, COMPRESSION 0.1. TF setupu: M5, M15; kontekst: H1; wymagane dane: M5, M15; min. historia: 80 zamkniętych świec (warm-up).

**Reguły (z kodu):**
```
S10 EXHAUSTION_STRUCTURE_REVERSAL - reversal after a weakening impulse AND a confirmed change of
local structure. An overbought/oversold RSI alone is never the trigger, and a prior failed breakout
(S07) is not required.
LONG = reversal after a down impulse (SHORT mirrored):
  impulse    lowest low of the last `lookback` bars at bar x (x not older than `max_extreme_age`),
             impulse = highest high of the `lookback` bars before x minus low[x] >= min_impulse_atr x ATR
  exhaustion at least one, measured at x:
             (a) divergence: an earlier confirmed swing low q (3..lookback bars before x) with
                 low[x] < low[q] and RSI14[x] > RSI14[q] + 2   (momentum lower low not confirmed)
             (b) stretch: (EMA20[x] - low[x]) / ATR >= stretch_atr
  structure  last confirmed swing high (pivot 3/3) before x = the last lower high (CHoCH level)
  WATCH      impulse + exhaustion, price below the CHoCH level
  EARLY      close within 0.5 ATR of the CHoCH level, or the forming bar above it
  TRIGGER    first CLOSED bar after x closing above CHoCH + buffer_atr x ATR
  invalid.   close below the extreme low
  SL         extreme low - 0.2 ATR (+spread for SHORT)
  targets    TP1 = 50% retracement of the impulse, TP2 = 78.6% retracement
```

**Parametry robocze (do badań, nie zoptymalizowane):** `{"tfs": ["M5", "M15"], "lookback": 30, "max_extreme_age": 12, "min_impulse_atr": 3.0, "stretch_atr": 2.5, "buffer_atr": 0.1, "time_exit_bars": 30, "expires_bars": 8}`

**Wyjście i zarządzanie:** TP = 50% i 78,6% zniesienia impulsu.

**Near-miss:** zbliżenie do poziomu CHoCH → EARLY.  **Unieważnienie:** zamknięcie poniżej ekstremum.

**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.
