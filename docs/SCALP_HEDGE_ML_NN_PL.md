# Scalp XAUUSD-: M5 Range → M1 Sweep/Reclaim → Retest + kontrolowany hedge + ML/NN (MasterQUO 1.12)

**Tryb:** wyłącznie SHADOW.
- `scalp.mode = SHADOW`, `live_trading = false`, `ml_execution = false`, `hedge_execution = false`. Konfiguracja nie przyjmuje innych wartości.
- Moduł zapisuje hipotetyczne decyzje i nigdy nie wysyła zleceń. Nie ma referencji do executora.
- Ochrona już otwartych pozycji bota działa bez zmian, także przy awarii tego modułu (stan `ERROR_RECOVERY`).

Profil badawczy: `config/scalp_profile_v1.json`, `MQ-SCALP-RANGE-SWEEP-1.0.0-RESEARCH`.
- Każdy parametr ma jednostkę. Wszystkie liczby to **hipotezy startowe**, nie optimum.
- Zmiana wartości = nowy identyfikator profilu.

## Jak wystartować (Windows)

| Krok | Plik | Co robi |
|---|---|---|
| 0 | `10_PROGNOZY_INSTALUJ.bat` | jednorazowo: `.venv_candles` (scikit-learn, pandas – pakiety z hashami) |
| 1 | `16_EKSPORT_HISTORII_SCALP.bat [miesiące]` | zamknięte M1/M5/M15/M30/H1 `XAUUSD-` z Twojego zalogowanego MT5 (domyślnie 6 mies.) → `data\scalp\history\<cutoff>\` z `DATA_QUALITY_REPORT.json` |
| 2 | `19_REPLAY_SCALP.bat [prowizja]` | replay po kosztach w trzech wariantach: normalnym, ze stresem kosztów +50% oraz NETTING → `data\scalp\replay\<czas>\summary.json` |
| 3 | `17_TRENING_SCALP_ML.bat [prowizja]` | trening A/B/C (plan, walk-forward, kalibracja, holdout raz) → `data\scalp\runs\<run_id>\report.json` |
| 4 | `18_WALIDACJA_SCALP.bat` | checksumy, kontrakt cech, odczyt przez ścieżkę workera bota |
| 5 | `20_START_SCALP_SHADOW.bat` | start monitora; sekcja: Wykresy bota → „Scalp M5 Range → M1 Sweep → Retest + hedge” |
| — | `21_ROLLBACK_MODELU_SCALP.bat [BRAK]` | poprzedni zgodny model albo brak modelu |

**`<prowizja>`** to prowizja za 1 lot na stronę, w walucie konta. **Domyślnie w paczce: 0.50** – launchery 17 i 19 można uruchomić dwuklikiem.
- Inna wartość: argument launchera (np. `17_TRENING_SCALP_ML.bat 3.5`) oraz w `data\config.json`: `"scalp": {"commission_per_lot_side": 3.5}`.
- Sprawdź ją w warunkach swojego rachunku – profil „Zero” nie oznacza zerowych kosztów.

**Polecenia CLI:**
- `python -m masterquo export-scalp`
- `python -m masterquo scalp-replay`
- `python -m gold_candles_runtime.scalp_train`
- `python -m gold_candles_runtime.scalp_registry {list|validate|activate|rollback|deactivate}`

## Strategia (dokładnie tak, jak w kodzie `backend/masterquo/scalp/strategy.py`)

**Zakres M5.** Na zamknięciu M5 analizowanych jest 12 ostatnich kompletnych M5:
- `L=min(low)`, `H=max(high)`, `W=H−L`, `MID=(H+L)/2`.
- Warunki: `1.2 ≤ W/ATR14(M5) ≤ 4.0` oraz `ER10 ≤ 0.35`.
- Każda granica wymaga ≥2 dotknięć w tolerancji `0.15·ATR`, rozdzielonych ≥2 świecami.
- Zakres jest **zamrażany** (`range_id`, L/H/MID, tolerancja, ATR) i się nie przesuwa.
- TTL to 6 zamknięć M5.
- Unieważnienie: dwa kolejne zamknięcia M1 poza `[L−0.25·ATR, H+0.25·ATR]`.

**Sekcja M1.** W chwili uzbrojenia wybierany jest najnowszy ciąg ≤3 zamkniętych M1 dotykających granicy:
- `Z_low`, `Z_high` z zapisanym `known_at`;
- szerokość ≤ `min(0.5·ATR_M5, 0.25·W)`.
- Sweepem może być tylko M1 zamknięta **po** `known_at`.

**BUY (SELL lustrzanie):**
1. Zamknięta M1 przebija `Z_low−ε` i zamyka się powyżej `Z_high+ε`, gdzie `ε=max(2·tick, 0.05·ATR14(M1))`.
2. Potwierdzenie z rodziny REJECTION, ENGULFING lub DISPLACEMENT.
3. `tick_volume / mediana(20 poprzednich) ≥ 1.2`. Brak danych = UNKNOWN, czyli brak setupu.
4. Retest w ciągu 3 M1: zakres świecy nachodzi na `Z_high±ε`, close wraca powyżej `Z_high+ε`, dołek sweepu pozostaje nienaruszony.
5. Wejście przy pierwszym świeżym kwotowaniu po zamknięciu retestu:
   - limit pogoni `max(2·tick, 0.10·ATR_M5)` po przeliczeniu na cenę wykonania;
   - dalej = MISSED, bez gonienia ceny.
6. Brak BUY nie oznacza SELL. SELL wymaga własnego sweepu nad `Z_high`.

**SL, TP, koszty:**
- SL za ekstremum sweepu/retestu z buforem `max(2·tick, spread, 0.10·ATR_M1)`. SL dla SELL jest poziomem Ask.
- TP1 = MID (50% wolumenu), TP2 = przeciwna granica minus bufor wykonania.
- Jeśli lot nie dzieli się legalnie, stosowany jest wariant pojedynczego TP1.
- Maksymalny czas pozycji to 30 min. Po TP1 SL nie jest przesuwany na BE.
- Filtr geometrii: koszt round trip ≤ 15% zysku brutto do TP1 oraz ważony RR netto ≥ 1.2. To **nie** jest expectancy.

**Wielkość pozycji:**
- Liczona z pełnego ryzyka cash do SL, łącznie z kosztami: 0,25% equity na cały cykl.
- Zaokrąglenie wyłącznie w dół do kroku lota. Gdy minimalny lot przekracza budżet, setup jest pomijany.

**Kontekst M30/M15.** Fade jest blokowany tylko wtedy, gdy **oba** TF jednocześnie mają:
- SAR przeciwny do kierunku pozycji;
- `|nachylenie basis BB| > 0.25 ATR/bar`;
- BandWidth powyżej 80. percentyla ze 100 wcześniejszych barów.

Brak historii = WARMUP (blokada). Skuteczność tego filtra sprawdza ablation EXP-02.

**Stany automatu:**
- Główna ścieżka: WARMUP → SEARCH_RANGE → RANGE_ARMED → WAIT_SWEEP → WAIT_RETEST → ENTRY_CANDIDATE → READY_SHADOW.
- READY_EXECUTION jest nieosiągalny w 1.12.
- Stany boczne: EXPIRED, INVALIDATED, MISSED, BLOCKED, COOLDOWN, ERROR_RECOVERY.
- Każde przejście ma czas, `range_id`, kierunek, dowody i powód (dziennik w monitorze).

**Bramki przed READY.** Logiczne AND, gdzie brak informacji = BLOCKED:
- symbol XAU/USD;
- świeże Bid/Ask ≤ 2 s;
- kontekst;
- świeża decyzja;
- limit pogoni;
- znana prowizja;
- koszt i RR;
- spread;
- wielkość pozycji;
- limity dzienny 1,5% i tygodniowy 4% (equity całego konta, punkt odniesienia zapisany na dysku – restart nie zeruje licznika);
- kalendarz makro (brak świeżego kalendarza = blokada nowych wejść);
- jeden cykl / cooldown 5 min;
- model (profil nie wymaga ML);
- uprawnienie wykonania (zawsze false).

## Silnik świec SCI-1.0.0 (`scalp/candles_sci.py`)

Własny, jawnie zdefiniowany silnik. Nie podszywa się pod produkt o podobnej nazwie. Działa na bazie MQ-CANDLE-1.0.0, z dodatkowymi rodzinami ze specyfikacji:

| Rodzina | Warunki |
|---|---|
| REJECTION | `lower/R≥0.5`, `lower≥2B`, `CLV≥0.7`, `B/R≤0.45` |
| ENGULFING | objęcie korpusu i mocne zamknięcie; jakość impulsu osobno: `B/R≥0.5`, `R/ATR≥0.8` |
| DISPLACEMENT | — |
| HARAMI | — |
| ZERO_RANGE | — |

**Zasady odczytu:**
- Kilka nazw z jednej rodziny na tym samym barze to **jeden** dowód.
- Doji i inside bar dają WAIT.
- `PatternStats` liczy statystykę wyniku tylko z przypadków znanych przed t: shrinkage do baseline, przedział Wilsona, minimum próby.

## Wskaźniki, sesje, źródła zewnętrzne

**Bollinger Bands:** SMA20 ±2σ z odchyleniem **populacyjnym** (jak MT5 iBands).
- Liczone są: %B, BandWidth/cena, percentyl ze 100 wcześniejszych barów i nachylenie w ATR/bar.

**Parabolic SAR:** 0.02/0.2 (Wilder). Przed użyciem dokładnych wartości porównaj je z iSAR w MT5.

**Sesje SESS-1.0.0** – własne reguły; strefy IANA, czyli DST bez ręcznego offsetu:

| Sesja | Godziny lokalne |
|---|---|
| Azja | 09–15 Tokio |
| Londyn | 08–12 |
| Nowy Jork | 08–12 |

Box jest znany dopiero po końcu sesji.

**Adaptery** mają kontrakt `AVAILABLE / UNAVAILABLE / STALE / UNVALIDATED / UNDOCUMENTED_EXTERNAL`. Brak danych = `null`, nigdy 0.

| Adapter | Status w 1.12 | Powód / czego brakuje |
|---|---|---|
| IQ Gold Gann (MT5 134935; MT4 134335) | UNAVAILABLE | brak licencjonowanego eksportu; publiczny opis wersji MT5: brak buforów do EA |
| IQ FX Gann (119707) | UNAVAILABLE | inny produkt niż Gold Gann; nie skonfigurowano |
| IQ Star Lines | UNAVAILABLE | opis autora: astrologia wedyjska; tylko SHADOW po osobnym teście przyrostowym |
| Volatility Master (MT4 111302) | UNAVAILABLE | EX4 nie działa w MT5 |
| Liquidation heatmap | UNAVAILABLE | brak autoryzowanego API; XAUT ≠ XAUUSD- |
| Session Sweep Boxes (zewnętrzny) | UNAVAILABLE | mapowanie buforów niezweryfikowane – używany własny moduł sesji |
| **PAL02M** | **UNDOCUMENTED_EXTERNAL** | potrzebne: pełna nazwa i dostawca, platforma i wersja, udokumentowany interfejs z jednostkami, licencja na odczyt automatyczny, deklaracja repaint |

**Mostek plikowy:** użytkownik z licencjonowanym eksportem może zapisać `data\scalp\external\<ADAPTER>.json` w formacie `{symbol, known_at, values, source, version}`.
- Program sprawdza symbol i wiek danych.
- Wynik oznacza jako UNVALIDATED i nigdy nie promuje go automatycznie.

## Hedge (`scalp/hedge.py`) – nakładka ryzyka, tylko SHADOW

**Rachunek NETTING:** przeciwne zlecenie redukuje pozycję, więc HEDGE_PARTIAL jest zastępowane przez REDUCE.

**Rachunek HEDGING – limity:**
- najwyżej 1 hedge na cykl;
- wolumen ≤ 50% bieżącego base, zaokrąglony w dół;
- jeśli minimalny lot przekracza limit, hedge jest niedozwolony;
- bez dodatkowego budżetu straty.

**HEDGE_PARTIAL** wymaga zwalidowanej polityki z korzyścią względem REDUCE po kosztach. Takiej polityki brak, więc decyzja to SHADOW/REDUCE.

**Wyjście hedge:**
- TTL 3 zamknięte M1;
- 2 zamknięcia w kierunku base z odzyskaną krawędzią;
- albo zamknięcie koszyka.

**Sytuacje awaryjne:**
- Osierocona noga: przeliczenie ekspozycji i zamknięcie samotnego hedge.
- Timeout zlecenia: najpierw rekonsyliacja po kluczu idempotencji, nigdy ponowne wysłanie w ciemno.
- P&L koszyka obejmuje wszystkie nogi, mark-to-close i opłaty.

## ML/NN (`backend/gold_candles_runtime/scalp_*.py`, `.venv_candles`)

**Kontrakt cech SCALP-FEAT-1.0.0** – 30 przyczynowych cech M1:
- zwroty w ATR, geometria świecy;
- BB, SAR;
- aktywność tick volume (z flagą braku);
- pozycja w 60-minutowym zakresie, ER10;
- spread/ATR (z flagą braku), czas.

Wskaźniki pochodzą z tego samego modułu co bot.

**Zadanie A** – kierunek dla horyzontów 1/3/5 min:
- Etykieta: `d=C(t+h)−C(t)`, `τ=max(0.2·ATR_M1, spread + 2·prowizja + 2·poślizg)`, klasy UP/FLAT/DOWN.
- Etykieta nigdy nie przechodzi przez lukę.
- Kandydaci: baseline częstości klas i „bez zmiany”, regresja logistyczna, HistGradientBoosting.
- **Rzeczywista sieć MLP 64/32:** standaryzacja, L2, seed 0, epoki `partial_fit`. Early stopping na **późniejszym** fragmencie development, nigdy na losowym podziale sklearn.
- Kwantyle q10/q50/q90 z HistGradientBoostingRegressor(quantile). Reguła nieprzecinania: sortowanie.

**Zadanie B** – jakość setupu:
- P(TP1 przed SL) z replayu pełnej polityki, liczona na niezależnych cyklach.

**Zadanie C** – porównanie akcji HOLD/REDUCE/CLOSE/HEDGE_PARTIAL:
- Wszystkie akcje oceniane na tej samej dalszej ścieżce.
- Wynik liczony per cykl: punkty decyzji jednej pozycji nie są niezależne.

**Walidacja:**
- `TRAINING_PLAN` jest zapisywany **przed** fitem i wiązany z hashem danych.
- Podział czasu 60/20/20 z granicami o 00:00 UTC.
- Purge według końca etykiety plus embargo 30 min.
- 4 foldy walk-forward w development do wyboru modelu.
- Kalibrator dopasowywany tylko na okresie kalibracji.
- Holdout oceniany raz.
- Raportowane metryki: log loss, Brier, balanced accuracy, recall, ECE, pinball, pokrycie q10–q90.
- Bootstrap bloków dni.

**Minima uruchomienia:**
- MLP: ≥10 000 wierszy train, ≥30 dni, ≥100 na klasę.
- Zadanie B: ≥300 cykli dev i ≥100 w holdout.
- Zadanie C: ≥200 cykli.
- Poniżej minimów status to INSUFFICIENT_DATA.

**Rejestr i artefakty:**
- Rejestr `data\scalp\registry.json` z atomowym zapisem. Aktywny może być tylko model REAL_USER_DATA ze zgodnym kontraktem i checksumami.
- LR, MLP i kalibratory zapisywane jako przenośny JSON.
- Modele drzewiaste jako pickle, ładowany **tylko** po zgodności sha256 z rejestrem.

**Inference:**
- Worker oblicza prognozę na nowej zamkniętej M1 (`scalp_forecast`), bez drugiej sesji MT5.

**Bramka badawcza strategii** (kryteria badań, nie gwarancja):
- ≥30 dni i ≥200 niezależnych cykli OOS;
- dolny kraniec 95% CI expectancy > 0;
- max DD ≤ 5%;
- dodatni wynik przy kosztach +50%.

Hedge wymaga osobnego dodatniego efektu względem REDUCE.

## Replay (`scalp/replay.py`)

**Kolejność zdarzeń:**
- Na wspólnym zamknięciu: M30/M15 → M5 → M1.
- Wypełnienie na otwarciu **następnej** M1: BUY po Ask = bid + spread + poślizg, SELL po Bid.

**Wyjścia i koszty:**
- Wyjścia BUY wyliczane po Bid, SELL po Ask.
- Prowizja na stronę; spread nie jest odejmowany drugi raz.
- Luka przez SL = wypełnienie po open.

**Niejednoznaczny OHLC:**
- SL i TP w jednej świecy → kolejność konserwatywna (SL) i flaga `ambiguous`.
- Wynik oznaczony jest jako `OHLC_APPROX` – to nie jest tickowy backtest.

## Rollback

| Co | Jak |
|---|---|
| model | `21_ROLLBACK_MODELU_SCALP.bat` / `… BRAK` |
| funkcja | `data\config.json`: `"scalp": {"enabled": false}` |
| wersja | 1.12 → 1.11 |

Szczegóły powrotu do 1.11:
- Migracja `0012` tylko dodaje tabelę `scalp_shadow`.
- Przed uruchomieniem 1.11 usuń sekcję `scalp` z `config.json`.
- Katalog `data\scalp\` można zostawić.
