# Analityka PepeMarketWizard 1.13: BB, MAs, FFT, EMD, VMD, Double Bottom

**Zasada nadrzędna:** wszystkie moduły pracują w trybie obserwacyjnym (`analytics.influence = OBSERVE`; konfiguracja nie przyjmuje innej wartości).
- Ich wyniki zasilają wykresy, wyjaśnienia, historię decyzji i testy.
- Nie zmieniają zgody na wykonanie, blokady wykonania (Execution Lock), wielkości pozycji ani limitów ryzyka.
- Ich wpływ na strategię można rozważyć dopiero po porównaniu poza próbą (patrz „Ocena wartości”).

## Przepływ danych

```
MT5 (sesja bota) → MarketBridge: zamknięte świece per TF (UTC) → AnalyticsService (wątek „analytics”)
   ├─ BB + MAs (analytics/ta.py)          – na każdej nowej zamkniętej świecy M1…D1
   ├─ Double Bottom causal_as_of          – M5/M15/H1 (konfigurowalne)  → zdarzenia pattern_events
   └─ kolejka (najnowsze zadanie per TF) → wątek „analytics-heavy”: FFT, EMD, VMD (limit czasu, cache)
         ↓ wynik dla starszej świecy lub konfiguracji jest odrzucany (licznik discarded_stale)
   analytics_snapshots (historia wyników dostępnych w chwili decyzji – nigdy nie nadpisywana)
   → API /api/v1/analytics… → WS „analytics” → strony: Pulpit, Indykatory, Analiza sygnału, Formacje, Diagnostyka
   → engine/chartdata.py: linie EMA i BB na wykresach z TEGO SAMEGO silnika
```

## Wspólny kontrakt wyniku (mq-analytics-1.0.0)

**Pola każdego wyniku:**

| Grupa | Pola |
|---|---|
| wersje i konfiguracja | `schema_version`, `algorithm_version`, `config`, `config_hash` |
| identyfikacja danych | `snapshot_id`, `source_revision` (hash ostatnich 50 świec), `symbol`, `timeframe`, `source`, `input_price_type` |
| czas | `as_of`, `available_at`, `computed_at`, `window_start`, `window_end` |
| stan | `status`, `reason`, `quality_flags` |
| metryki wejścia | `closed_bars_only`, `preview`, `samples`, `latency_ms` |
| wynik | `values` |

**Znaczenie czasów:**
- `as_of` – granica danych, czyli zamknięcie ostatniej świecy wejściowej.
- `available_at` – chwila, od której wynik dało się użyć.
- Dla pivotów Double Bottom czas dostępności jest osobny: dołek staje się znany dopiero po zamknięciu świec po jego prawej stronie.

**Statusy:**

| Status | Znaczenie |
|---|---|
| `ready` | wynik policzony |
| `warming_up` | za mało świec |
| `stale` | dane nieaktualne |
| `unavailable` | np. luka w oknie |
| `error` | błąd danych, konfiguracji lub obliczeń |
| `disabled` | moduł wyłączony |

Brak wyniku to zawsze `null` z podanym powodem – nigdy 0.

## Bollinger Bands i średnie – `analytics/ta.py` (MQ-TA-1.0.0)

**BB** liczone z ceny close, SMA n i mnożnika k (start: 20 i 2 – to nie jest optimum dla XAUUSD-):
- `sigma` – odchylenie standardowe **populacyjne** (ddof=0). Zgodne z MT5 iBands i silnikiem M02I; równość sprawdza test.
- `%b = (close − lower)/(upper − lower)` – **bez przycinania** do 0–1. Gdy okno jest płaskie: `null` z powodem FLAT_WINDOW.
- `bandwidth_ratio = (upper − lower)/middle` i `bandwidth_pct = 100 × ratio` – dwa osobne pola.
- **Squeeze** – percentyl szerokości liczony tylko z wcześniejszych świec (domyślnie 120), próg 20.
- **Zdarzenia** (opis sytuacji, nie polecenia kupna ani sprzedaży):
  - `TOUCH_UPPER/LOWER`, `CLOSE_ABOVE_UPPER/BELOW_LOWER`, `RETURN_INSIDE`, `CROSS_MIDDLE`;
  - `trend_walk` – co najmniej 3 z 5 zamknięć przy paśmie, czyli ruch wzdłuż pasma w trendzie.

**MAs:**
- Rodzaje:
  - SMA;
  - EMA – start od SMA pierwszych n świec, jak w M02I;
  - WMA.
- Wyniki:
  - położenie ceny względem średniej;
  - nachylenie w cenie i w ATR na świecę;
  - uporządkowanie średnich;
  - przecięcia potwierdzone zamknięciem świecy, ze stałym `event_id`.
- Kontekst według jawnych reguł:
  - TREND_UP / TREND_DOWN – uporządkowanie, cena i nachylenie zgodne;
  - CONSOLIDATION – nachylenie najwolniejszej średniej poniżej 0,02 ATR na świecę;
  - CORRECTION;
  - MIXED.
- SMA o okresie środka BB jest oznaczona `same_as_bb_middle`, żeby nie dawała drugiego głosu za tym samym zjawiskiem.

## FFT, EMD, VMD – `analytics/signal.py`

**Implementacja: numpy i scipy, które bot już instaluje.** Bez nowych zależności, z następujących powodów:
- sktime to duży pakiet dla jednego transformatora;
- nazwa „EMD” na PyPI jest niejednoznaczna: EMD-signal/PyEMD to Empirical Mode Decomposition, a „pyemd” to Earth Mover’s Distance.
- VMD to opublikowany algorytm ADMM (Dragomiretskiy i Zosso, 2014).
- EMD to standardowy sifting z kryterium SD i limitami.
- Poprawność sprawdzają testy na mieszaninach o znanych składowych.

**Wspólne zasady:**
- **Okno:** ostatni **ciągły** odcinek zamkniętych świec, domyślnie 256.
  - Luka lub przerwa sesji w oknie skracają odcinek.
  - Gdy odcinek jest krótszy niż minimum: `unavailable GAP_IN_WINDOW`.
  - Brakujących świec nie wypełniamy zerami ani ostatnią ceną.
- **Przyczynowość:** liczone są tylko dane do t.
  - VMD rozszerza okno lustrzanym odbiciem samego okna (tylko obserwowane próbki).
  - EMD jako węzły obwiedni bierze punkty końcowe okna.
  - Rewizję końca okna **mierzymy**: ta sama analiza na oknie kończącym się 5 świec wcześniej. Wynik trafia do pól `end_revision_vs_lag` i `omega_change_vs_lag` oraz do flag jakości.
- **Zasoby i limity:**
  - jeden wątek roboczy i kolejka, w której najnowsze zadanie per TF wygrywa;
  - cache z kluczem: moduł, TF, ostatnia świeca, rewizja, hash konfiguracji;
  - limit czasu VMD (`timeout_seconds`) i limity parametrów w konfiguracji;
  - przekroczenie limitu daje flagę `TIMEOUT` i status `error`, nigdy pozornie poprawną liczbę.

**FFT:**
- Wejście: log-stopy zwrotu (domyślnie) albo log close z trendem liniowym usuniętym; 1 próbka = 1 świeca.
- Metoda: periodogram z oknem Hann, `scaling=spectrum`, bez zero-paddingu.
- Wynik: dominujące okresy (w świecach i minutach), udział mocy, stabilność względem okna sprzed 5 świec.
- Flagi jakości:

| Flaga | Kiedy |
|---|---|
| `NO_DOMINANT_PEAK` | brak wyraźnego szczytu widma |
| `UNSTABLE_DOMINANT_PERIOD` | dominujący okres zmienia się między oknami |
| `DOMINANT_NEAR_NYQUIST` | okres < 2,5 świecy – to szum świeca do świecy, nie cykl rynkowy |
| `PERIOD_TOO_LONG_FOR_WINDOW` | okres za długi względem okna |

**EMD:**
- Wynik: IMF z udziałem energii i średnim okresem (z przejść przez zero), residuum, maksymalny błąd rekonstrukcji (z definicji około 0), rewizja końca okna.

**VMD:**
- Parametry: K modów (start 4), alpha 2000, DC=True; wejście jest normalizowane do jednostkowej wariancji, więc tolerancja nie zależy od skali ceny.
- Wynik: częstotliwości środkowe, okresy, energia, błąd rekonstrukcji, zbieżność i liczba iteracji, zmiana częstotliwości między oknami.
- Przypisanie trend/cykl/szum to **hipoteza** według częstotliwości: najniższa = trend, najwyższa = szum.

> Trzy transformacje tej samej ceny **nie są trzema niezależnymi potwierdzeniami** i nie przewidują kierunku.

## Double Bottom – `analytics/double_bottom.py`, `analytics/library.py`

**Pochodzenie:** własna implementacja jawnej specyfikacji. Idea funkcjonalna pochodzi z artykułów MQL5 Part 84, 85 i 86, ale **kod artykułów nie był użyty**.

**Statusy:**

| Status | Znaczenie |
|---|---|
| `INVALID` | brak dopuszczalnej pary dołków (z powodem) |
| `CANDIDATE` | para dołków bez rozstrzygnięcia |
| `CONFIRMED` | pierwsze rozstrzygające zamknięcie powyżej neckline |
| `FAILED` | pierwsze rozstrzygające zamknięcie poniżej dołków |

Pierwsze rozstrzygnięcie jest ostateczne: późniejsze fałszywe wybicie nie zmienia statusu.

**Reguły** – wszystkie parametry są w konfiguracji `analytics` i w `config_hash` wyniku:

| Reguła | Wartość |
|---|---|
| pivot | 3/3 świece – znany dopiero po zamknięciu prawych świec |
| odstęp dołków | 5–60 świec |
| neckline | najwyższy high między dołkami |
| głębokość | ≥ 0,05 % ceny; w trybie EXTENDED (wersja DB-1.1.0-EXT) dodatkowo ≥ 1 ATR |
| podobieństwo dołków | różnica ≤ 0,25 × głębokość |
| symetria | ≤ 3 |
| wcześniejszy spadek | ≥ 0,5 × głębokość |
| wybór pary | najnowszy drugi dołek → najgłębsza struktura → najwcześniejszy pierwszy dołek |

- `pattern_id` = hash(symbol, TF, czasy dołków, wersja reguł).
- Wynik zgodności kształtu **nie jest prawdopodobieństwem zysku**. Strefa retestu i zasięg to hipotezy.

**Tryby pracy:**
- `offline_full_sample` – próbka z biblioteki sprawdzana na wszystkich jej świecach.
- `causal_as_of` – skaner bieżących danych, tylko zamknięte świece. Każdy nowy stan jest zapisywany jako zdarzenie z `available_at`.
- Błąd danych (np. zła geometria OHLC, duplikat) daje status `error`, a nie formację `FAILED`.

**Biblioteka** – strona Formacje i biblioteka:
- **Próbki:** zapis z zakresu zamkniętych świec (surowe OHLCV, symbol, TF, granice, hash, pochodzenie, notatka).
  - Duplikat nie nadpisuje istniejącej próbki.
  - Import i eksport JSON (schema `mq-pattern-library-1`) z walidacją.
- **Walidacja:** `VALIDATE SELECTED` i `VALIDATE ALL` to zadania z `job_id`, postępem i anulowaniem.
  - Lista próbek i konfiguracja są zamrażane przy starcie zadania.
  - Każdą próbkę sprawdza ta sama funkcja co walidacja pojedyncza – test potwierdza identyczne współrzędne.
  - Liczone są statusy oraz ERROR i MISSING (usunięte próbki, luki w ID).
  - Raport JSON i CSV ma nowy identyfikator za każdym razem; powodzenie obliczeń i eksportu jest raportowane osobno.
  - Anulowane zadanie ma status CANCELLED i nigdy nie jest przedstawiane jako pełna walidacja.
- **SHOW ON CHART:** wykres próbki z dokładnymi współrzędnymi walidatora (dołki, neckline, zdarzenie rozstrzygające). Renderer nie szuka dołków ponownie.

## Ocena wartości dla strategii – jeszcze nie wykonana

Na danych z Twojego MT5 trzeba porównać na tych samych okresach:
1. obecny system;
2. + BB/MAs;
3. + każdy z modułów VMD, FFT, EMD osobno;
4. + Double Bottom;
5. wybraną kombinację.

**Metoda:** chronologiczny walk-forward, koszty, końcowy okres testowy poza doborem parametrów. Przed porównaniem zapisz kryteria i liczbę sprawdzanych konfiguracji.

**Ograniczenia biblioteki formacji:** jest wybierana ręcznie, więc nie jest reprezentatywną próbą rynku. Do oceny skanera potrzebne są też zakresy bez formacji, czyli fałszywe trafienia i braki wykrycia.

## Konfiguracja (`data\config.json`, sekcja `analytics`)

| Grupa | Pola |
|---|---|
| ogólne | `enabled`, `timeframes`, `bars` |
| BB | `bb_period`, `bb_k`, `bb_squeeze_lookback`, `bb_squeeze_pct` |
| średnie | `mas` – lista `{id, type SMA/EMA/WMA, period, visible}` |
| analiza sygnału | `signal_enabled`, `signal_timeframes`, `signal_window`, `fft_input`, `vmd_k`, `vmd_alpha`, `vmd_max_iter`, `emd_max_imfs`, `timeout_seconds` |
| Double Bottom | `db_timeframes`, `db_mode` (SOURCE_COMPAT / EXTENDED), `db_min_separation`, `db_max_separation`, `db_max_bottom_diff_frac`, `db_min_depth_pct`, `db_profile` (samodzielna struktura / kontekst dla strategii) |
| archiwum | `snapshot_retention` |

**Zasady konfiguracji:**
- Nieprawidłowe wartości są odrzucane przy zapisie.
- Zmiana parametrów zmienia `config_hash`, więc wyniki liczą się od nowa (nowa wersja).
- Widoczność linii na wykresie nie zmienia reguł strategii.

**Powrót do 1.12:** migracja 0013 tylko dodaje tabele. Przed uruchomieniem 1.12 usuń sekcję `analytics` z `config.json`.
