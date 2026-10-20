# PMW-UPD-14 – VAMD, Pullback + SMC (BoS/CHoCH/IDM/x), bounded Katz FD, Buffer Inspector

Stan: kod zaimplementowany i przetestowany na danych TEST_ONLY.
- Brak treningu na prawdziwych danych.
- Brak oceny przewagi (`NO_VALIDATED_EDGE`).
- Brak kompilacji native (`NOT_EXECUTED_METAEDITOR_UNAVAILABLE`).

Moduły działają w trybie OBSERVE/SHADOW:
- nie składają zleceń,
- nie zmieniają SL/TP ani Execution Lock,
- nic nie aktywuje się automatycznie.

## Moduły (`backend/masterquo/lab/context_ind/`)
| Profil | Plik | Najważniejsze reguły |
|---|---|---|
| PWM_VAMD_ATR_WILDER_SMA_v1 | `vamd.py` | m=(C−C_{t−P})/ATR (Wilder, seed=średnia A TR); baseline=SMA B ATR **z bieżącym**; alpha=min(max_decay, base_decay·ATR/baseline); y wypukle między poprzednim y a m; rozgrzewka 63 bary (14/50); ATR/baseline=0 → brak wartości (nigdy epsilon); podgląd świecy formującej tylko na kopii |
| PWM_KATZ_BOUNDED_v1 | `fractal.py` | okno N cen; L=suma |Δp|, d=max |p−p0| (nie punkt końcowy); den≤eps → saturacja 2 (CONSERVATIVE_CHOP_SATURATION); clip [1,2] z flagą; płasko (tolerancja w tickach) → NO_MOTION i reset wygładzania; EMA(S) z seedem; strefy TREND≤1.40 (bez strony), CHOP≥1.65 |
| PWM_PULLBACK_CLOSED_v1 | `smc.py` | jedna strona szukania; nowe ekstremum / przełamanie referencji / outside bar wg tabeli; WICK/CLOSE; porównania na siatce ticka; równość nie potwierdza; ledger append-only (origin, bar potwierdzenia, available_at) |
| PWM_SMC_PULLBACK_BAR_ATOMIC_v1 | `smc.py` | jeden slot H i L; seed z pierwszej pary H>L; kolejność w barze: pullback → pending trail + IDM ratchet + test IDM (nie na barze przełamania) → przełamanie zamknięciem → OPPOSITE_BREAK_FALLBACK → kandydat sweep z wcześniejszego baru staje się x (relokacja = nowa wersja punktu) → BoS/CHoCH → ALTERNATION_ANCHOR → nowy pending; zdarzenia z lokalnym seq; widok as-of z wersji punktów |
| Buffer Inspector | `buffers.py` | koperty `pmw-bufreport-1` / `pmw-bufbridge-1` (sha256 treści); heurystyki LINE_LIKE / SPARSE_EVENT_LIKE / INTEGER_STATE_LIKE / EMPTY_OBSERVED / UNKNOWN jako hipotezy; mapowanie VERIFIED_TECHNICAL tylko z kompletem pól (jednostki, semantyka kierunku, sentinel pusty, czy 0 jest poprawne, shift, PLOT_SHIFT, potwierdzenie, symbol, TF); most: whitelist, kontekst, wersja mapowania, epoch/seq (idempotentnie), TTL, wartości skończone → `AVAILABLE_UNVALIDATED` (diagnostyka) |
| CONTEXT_MOVE_M5_V1 / FS_VS_CONTEXT_v1 | `task.py` | etykiety rynkowe r_h=(C[i+h]−C[i])/ATR14, h=3/6/12 M5, progi ±0.15√h; 23 cechy liczone przyczynowo (stan silników po zamknięciu baru); CLASS_FREQ/LOGREG/XGB; ablacje core → +VAMD → +FD → +SMC; kalibracja deterministyczna: 24 zadeklarowane konfiguracje, tylko dev, rejestr wszystkich prób |

## Runtime, API, panel, agent
- **Runtime.** `ContextSections`, wywoływane z komórki Structure Intelligence:
  - jeden producent na (instrument, TF, hash profilu);
  - każdy zamknięty bar jest przetwarzany po kolei, a powtórny odczyt nic nie zmienia;
  - rewizja historii albo zmiana profilu tworzy nowy epoch;
  - zdarzenia SMC trafiają do ledgera `data/context_ind/<inst>/ledger/*.jsonl`, z unikalnym `ledger_id` (instrument|TF|profil|epoch|event).
- **Fakty dla scenariuszy.** Sekcja `context` w komórce zawiera VAMD, FD, SMC oraz `would_block`:
  - `would_block` to wyłącznie diagnostyka SHADOW, a nie trigger;
  - brak blokady nie jest sygnałem.
- **API.** Endpointy:
  - `GET /api/v1/lab/context`, `/lab/vamd`, `/lab/fractal-regime`, `/lab/smc?as_of=`;
  - `GET /lab/buffers/reports[/{id}]`;
  - `POST /lab/buffers/reports/import` (tylko plik z `MQ_MT5_FILES_DIR\PMW`);
  - `GET/POST /lab/buffers/mappings`, `POST /lab/buffers/mappings/validate`, `POST /lab/buffers/mappings/{id}/rollback`;
  - `GET /lab/buffers/source`;
  - `POST /lab/context/calibrate` (krok `calibrate` / `dataset` / `train`; asynchroniczne zadanie z postępem i anulowaniem przez `/structure-intelligence/jobs`).

  GET nie trenuje i nie zmienia wykresów w terminalu.
- **Panel.** Karta „Kontekst” na stronie Structure Intelligence:
  - wykres lightweight-charts z trzema panelami (cena + SMC/pullback/provisional trail/zdarzenia, VAMD, FD);
  - osobne przełączniki widoczności;
  - wybór stanu as-of;
  - tooltip zdarzeń (id, czas publikacji, powód);
  - tabela would_block;
  - Buffer Inspector: import raportu, tabela buforów, formularz mapowania z walidacją, rollback, stan mostu.
- **Agent.** Wiedza C01–C07 (`PMW-CTX-KNOWLEDGE-1.0.0`), prompt `MQAI-AGENT-PROMPT-2.0.0`. `explain_cell` korzysta wyłącznie z wartości z sekcji `context`.

## Polecenia (z katalogu `backend`)
```
python -m masterquo context-indicators audit --asset XAUUSD
python -m masterquo context-indicators calibrate --asset XAUUSD
python -m masterquo context-indicators replay --asset XAUUSD
python -m masterquo context-indicators dataset --asset XAUUSD
python -m masterquo context-indicators train --asset XAUUSD --families LOGREG,XGB --profile standard
python -m masterquo context-indicators pipeline --asset XAUUSD --out raport.json
python -m masterquo context-indicators buffers-verify --report <MQL5\Files\PMW\PWM_BUFFER_REPORT.json> [--mapping mapping.json]
python -m masterquo context-indicators export-fixture [--files-dir <MQL5\Files>]
python -m masterquo context-indicators native-parity [--export <PWM_CONTEXT_EXPORT.txt>]
```
- Dane syntetyczne są odrzucane, chyba że podasz `--allow-synthetic-fixture`; wynik ma wtedy rolę TEST_ONLY.
- Launcher: `29_CONTEXT_INDICATORS.bat`.
- Train-all: zadanie `context_indicators` (runner, 16 zadań).

## Native MQL5 (`mql5/ContextIndicators/`)
- `Include/PMW/PMW_ContextCore.mqh`: port 1:1 rdzeni Python. Logikę SMC/pullback sprawdzono transliteracją na 160 przebiegach (0 różnic), ale **nie kompilowano**.
- `PWM_VAMD.mq5`: bufory 0 y, 1 kolor, 2 alpha, 3 m. `PWM_FractalRegime.mq5`: bufory 0 smooth, 1 kolor strefy, 2 bounded, 3 kod jakości.
- `PWM_SMCStructure.mq5`: 8 buforów według manifestu (active H/L, trend_code, event_mask z bitami BOS_UP 1 … FALLBACK 1024, potwierdzenia pullback i publikacje struktury na barze potwierdzenia). Linia struktury jest rysowana obiektami `PWMSMC_` jako geometria.
- `PWM_BufferFixture.mq5`: fixture capability (DATA, COLOR_INDEX z legalnym 0, CALCULATIONS, DRAW_NONE z zerami, strzałki EMPTY_VALUE, custom empty 0, PLOT_SHIFT=3, opóźniona gotowość).
- `PWM_BufferInspector.mq5`: skrypt; skanuje indeksy 0..511, wynik jest FULL albo PARTIAL; PLOT_SHIFT obcych wskaźników raportuje jako UNKNOWN.
- `PWM_IndicatorBridge.mq5`: eksport jednego zmapowanego bufora, tylko zamknięte bary.
- `PWM_ContextSelfTest.mq5`: ręczne przypadki Katz/VAMD oraz eksport `PWM_CONTEXT_EXPORT.txt` do parytetu.

Instalacja: `29_CONTEXT_INDICATORS.bat` → 9. Ten krok:
- wykrywa `metaeditor64.exe` i jego wersję;
- tworzy kopię zapasową poprzednich plików;
- kompiluje z logiem;
- zapisuje `ctx_native_status.json`;
- zapisuje fixture CSV.

Instalator nie zmienia AutoTrading i nie uruchamia handlu.

## Ograniczenia (stan rzeczywisty)
- WS: brak osobnego typu aktualizacji; panel odpytuje REST co 20 s.
- Ledger, profile, mapowania i rejestr prób są w plikach JSON/JSONL zapisywanych atomowo, a nie w migracjach DB.
- Brak REAL_USER_DATA: kalibracja i trening wykonano tylko na danych testowych.
- Brak MetaEditora/Windows: native nie skompilowane ani nie uruchomione.
- Ekonomia replay/PAPER z kosztami nie jest jeszcze podłączona do filtrów kontekstu, więc brak potwierdzenia przewagi netto.

## Rollback
Kroki:
- usuń kartę z `StructureIntel.tsx` i sekcję `self.ctx` z `si_service.py`;
- usuń profil: `data/context_ind/<inst>/profile.json` (poprzednie wersje to `profile_<ts>.json`);
- cofnij mapowania przez `POST /lab/buffers/mappings/{id}/rollback`;
- przywróć pliki MQL5 z `MQL5\PMW_backup_*`.
