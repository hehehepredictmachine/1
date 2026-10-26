# REFACTOR_PLAN – PepeMarketWizard 1.18 · plan zmian po audycie architektury (26.10.2026)

Plan wynika z ustaleń w `ARCHITECTURE.md` (AR-01…AR-16), inwentarza `COMPONENT_INVENTORY.md` i mapy `INTEGRATION_MAP.md`.
Zasady: najpierw to, co poprawia bezpieczeństwo i daje dowody; zmiany zachowania bota dopiero po zatwierdzeniu (sekcja 4);
nic z tego planu nie włącza LIVE i nie przedstawia przewidywanego wyniku jako osiągniętego.

## 1. Co już zrobiono w tej iteracji

| Krok | Zakres | Wpływ na zlecenia | Dowód |
|---|---|---|---|
| AR-01 | SCALPING/HEDGING respektuje STOP (kill switch), Execution Lock i powody wiązania rachunku z `ModeManager.gate()`; otwarte plany nadal zarządzane | **tak – blokuje** nowe plany SH, gdy użytkownik dał STOP (poprawka błędu bezpieczeństwa, nie nowa funkcja) | `tests/test_arch_fixes.py` (przed poprawką 2 testy czerwone) |
| B | Wspólny kontrakt `SetupCandidate` / `SetupAssessment` dla S01–S12, SCALPING i HEDGING z walidacją (strona SL/TP, wagi, skończoność, **lookahead = błąd kontraktu**) | brak | `evaluation/contract.py`, `tests/test_evaluation.py` |
| D | Silnik oceny: P nazwanego zdarzenia, G/L netto, p* = L/(G+L), EV, przedział Wilsona z liczności kalibracji, jakość wykonania, konflikt portfela; decyzja SHADOW ACCEPT/REDUCE/DEFER/REJECT | brak (SHADOW) | `evaluation/engine.py` |
| D/H | `EvaluationService`: ocenia **każdy** setup obu ścieżek (także zablokowane później przez koordynator, ryzyko lub STOP), zapisuje w ledgerze w formacie `mm.ledger`, dojrzewa wynik z zamkniętych M1 (trafienia TP przed SL, MFE/MAE w R, wynik planu netto), raport per silnik × decyzja | brak (słuchacz tylko do odczytu) | `evaluation/service.py`, `evaluation/outcome.py`; podpięty w `runtime.py` |
| H1 (odczyt) | Łączna ekspozycja obu ścieżek: FLAT / SINGLE_ENGINE / STACKING / CONFLICT | brak (tylko odczyt) | `evaluation/exposure.py`, `/api/v1/eval/exposure` |
| AR-04 | Statystyki per silnik i łącznie (S01–S12 z `trades`, SCALPING/HEDGING z zamkniętych `sh_plans`) jako nowe pole `engines` w `/api/v1/stats`; dotychczasowe pole `bot` bez zmian | brak | `stats.engine_stats`, test regresji |

Sprawdzenie w działającym runtime (symulator, 4 min, `serve --demo` w procesie): słuchacz ścieżki A wywołany 96 razy, słuchacz SH 5 razy
(każda nowa zamknięta M1), 2 setupy S06 CONFIRMED oceniono jako DEFER – brak skalibrowanego modelu zdarzenia, próg p* odpowiednio 0,526 i
0,285, prowizja nieznana (DEGRADED). SH nie wygenerował setupu READY (WAIT: sprzeczne interwały). To dowód działania połączeń, nie wynik
strategii – dane są syntetyczne.

API (wszystkie tylko do odczytu): `/api/v1/eval/status`, `/api/v1/eval/assessments?engine=&limit=`, `/api/v1/eval/report`,
`/api/v1/eval/exposure`.

## 2. Plan faz B–H (priorytet malejąco)

| Faza | Cel z promptu | Stan po tej iteracji | Następny krok | Wymaga decyzji |
|---|---|---|---|---|
| B – Projekt | wspólny kontrakt danych i wyniku oceny | **zrobione** (SHADOW) | dodać `features` per strategia do kontraktu, gdy powstanie model na nich trenowany | – |
| C – Porządkowanie | usunięcie duplikatów bez utraty funkcji | zmapowane (`INTEGRATION_MAP.md` §5) | (1) `sh/models.py` jedynym rejestrem – `MAPA_MODELI_I_TRENINGU.*` generowana z niego; (2) jedna funkcja jakości danych z dwoma profilami; (3) podział `api/app.py` na routery bez zmiany ścieżek; (4) konsolidacja raportów audytu (§5) | koszt: O5 |
| D – Integracja modeli | P(TP przed SL \| X), kalibracja, niepewność, ensemble bez arbitralnych wag, EV | silnik i ledger w SHADOW; źródła P: `sh_tp_model` (zdarzenie zgodne), legacy ML (zdarzenie „net R > 0” – oznaczane EVENT_MISMATCH) | (1) model zdarzenia TP-przed-SL dla S01–S12 trenowany na etykietach z `evaluation/outcome.py` (te same reguły co ledger); (2) ensemble **tylko** gdy ≥2 skalibrowane modele tego samego zdarzenia – wagi ze stackingu na bloku kalibracji, nie ręczne; do tego czasu `model_agreement = NO_INDEPENDENT_EVIDENCE` | O2 |
| E – Strategy Pack | S1–S6 | **istnieją** (mapowanie §3) – nowe pliki byłyby duplikatami (AR-13) | statystyki i raport ledgera per strategia; wyłączanie strategii na podstawie pogorszenia (reguła z ledgera, nie z małej próby) | O6 |
| F – Hedging Engine | H1–H5 bez otwierania przeciwnej pozycji po stracie | H4 i H5 istnieją w SH (§3.2); H1 – widok ekspozycji (odczyt); H2 – limity SH + legacy, bez wspólnego; H3 – nie dotyczy | alternatywa REDUCE dla rachunków netting; wspólny limit ryzyka obu ścieżek | O1, O3 |
| G – Backtest i trening | realizm egzekucji, metryki, separacja danych | replaye SH i scalp są konserwatywne (świeca niejednoznaczna = SL); trzy modele kosztów | jeden model kosztów (AR-06); zaostrzenie bramki promocji legacy ML (AR-07); inferencja master models w pętli bota (AR-08) | O4, O7, O8 |
| H – Integracja końcowa | jeden router, decyzja oceny w przepływie | router S01–S12 i koordynator SH działają osobno; ocena SHADOW obejmuje oba | po decyzjach O1/O2: ocena jako bramka (najpierw ASSIST w PAPER), raport porównawczy SHADOW vs rzeczywiste decyzje | O1, O2 |

### 2.1 Mapowanie trybów z promptu

| Tryb z promptu | Odpowiednik w projekcie | Uwagi |
|---|---|---|
| RESEARCH | lab, `mm`, trening CLI, audyt (`tools/`) | bez dostępu do zleceń |
| BACKTEST | `sh/replay.py`, `scalp/replay.py`, `tools/backtest_ema_pullback.py`, walidacja runnera | wspólne koszty – AR-06 |
| PAPER | `execution_mode = PAPER` (PaperBroker + SH symulacja) | domyślny |
| DEMO | `AUTO_DEMO` (wymaga potwierdzonego rachunku demo) | wiązanie rachunku egzekwowane przez `ModeManager` (od AR-01 także w SH) |
| LIVE | `AUTO_LIVE` | **zablokowany**: Execution Lock `LOCKED`, SH odmawia AUTO_LIVE; żaden test ani trening go nie przełącza |

## 3. Pakiet strategii i moduły hedgingowe z promptu → istniejący kod

### 3.1 Scalping S1–S6

| Prompt | Istniejące implementacje | Brakujące wymagania §13 promptu | Propozycja |
|---|---|---|---|
| S1 Trend Pullback Scalper | S01 TREND_PULLBACK, S11 EMA20_PULLBACK_2_5R (S02 ADAPTIVE_TREND), SH SCALPING – kontynuacja | P zdarzenia (brak modelu dla S01–S12), statystyki per strategia z ledgera | ocena w ledgerze (jest), model zdarzenia po zebraniu etykiet |
| S2 Liquidity Sweep Reversal | S07 FAILED_BREAKOUT_RECLAIM, S12 RANGE_RECLAIM, SH SCALPING – odwrócenie, scalp Range→Sweep→Retest (SHADOW) | trzy implementacje tego samego wzorca | **nie usuwać przed porównaniem** – ledger zbiera wyniki S07/S12/SH; scalp SHADOW – do dopisania jako źródło kandydatów (O6) |
| S3 Momentum Breakout Scalper | S03 CHANNEL_BREAKOUT, S06 BREAKOUT_RETEST, S12 BREAKOUT_RETEST | ryzyko powrotu do zakresu oceniane heurystycznie | jw. |
| S4 Mean Reversion Scalper | S08 RANGE_EDGE_REVERSION, S09 STATISTICAL_MEAN_REVERSION | blokada w silnym trendzie istnieje w `regime_fit` routera | jw. |
| S5 Volatility Expansion Scalper | S04 VOLATILITY_COMPRESSION_BREAKOUT (S03) | pokrycie kosztów: RR_NET w ryzyku, EV w ledgerze (SHADOW) | jw. |
| S6 Session-Aware Scalper | S05 SESSION_RANGE_BREAKOUT, boksy sesji (`analytics/session_engine.py`), okna newsów (`news/service.py`), filtr spreadu | kalendarz makro częściowy | uzupełnienie kalendarza (zewnętrzne źródło – wymaga klucza użytkownika) |

### 3.2 Hedging H1–H5

| Prompt | Stan | Dowód |
|---|---|---|
| H1 Exposure-Aware | widok łącznej ekspozycji obu ścieżek (tylko odczyt); ekspozycja walutowa/czynnikowa – jeden czynnik (XAUUSD albo BTC aktywny naraz) | `evaluation/exposure.py` |
| H2 Drawdown Protection | limity dzienne/DD/otwarte ryzyko osobno w `risk/engine.py` i `sh/risk.py`; STOP działa w obu ścieżkach (AR-01) | brak wspólnego limitu – O1 |
| H3 Correlation-Aware | **nie dotyczy** – jeden aktywny instrument, korelacja XAUUSD/BTC niestabilna (AR-16) | `assets/registry.py` |
| H4 Conditional Hedge | koszyk HEDGING: hedge tylko po zdarzeniu (niekorzystny ruch ≥ trigger) **i** przy ważnej strukturze; inaczej EXIT; REDUCE, gdy hedge droższy od redukcji lub ryzyko nie pozwala; limit aktywacji. Nie jest to „przeciwna pozycja po każdej stracie” | `sh/hedge_fsm.py` `hedge_decision` |
| H5 Effectiveness | walidacja porównuje HEDGE / NO_HEDGE / REDUCE na tych samych setupach | `sh/replay.py`, raport walidacji SH |
| §16 netting | kontrola typu rachunku jest; na netting HEDGING jest blokowany w całości – brak alternatywy | O3 |

## 4. Decyzje (zatwierdzone 26.10.2026) i wdrożenie w 1.20.0

| ID | Wybór użytkownika | Wdrożenie | Zmiana zachowania |
|---|---|---|---|
| **O1** | (c) jedna ścieżka główna na instrument | `execution.primary_path` per instrument (`ACTIVE` / `SH` / brak), reguła w `ModeManager.gate(path=…)` dla decyzji S01–S12 (`engine/service.py`, `execution/gateway.py`) i planów SH (`sh/service.py`); okno Tryb → „4. Ścieżka główna”, `POST /api/v1/mode/primary-path`, wpis w `settings_audit` | **tak**: ścieżka niegłówna analizuje, ale nie otwiera wejść (`NOT_PRIMARY_PATH_*`); **bez wyboru żadna ścieżka nie otwiera nowych wejść** (`PRIMARY_PATH_NOT_SELECTED`). Otwarte pozycje obu ścieżek są zarządzane; transakcje ręczne bez zmian |
| **O2** | (a) SHADOW do 200 ocen | `report.assist_readiness` per silnik: dojrzałe oceny z prawdopodobieństwem, cel 200, Brier vs wskaźnik bazowy | nie: tylko licznik; przejście do ASSIST wymaga osobnej decyzji |
| **O3** | (b) REDUCE zamiast hedge na netting | `hedge.netting_alternative = REDUCE` w profilu HEDGING; `sh/risk.py` dopuszcza HEDGING na NETTING tylko po zaliczonej walidacji replay wariantu REDUCE (`SHService.netting_reduce_validation`: raport na REAL_USER_DATA, n ≥ 30, wynik oczekiwany > 0); bez nogi hedge w ekspozycji i depozycie; zdarzenie hedge → częściowe zamknięcie (istniejąca ścieżka REDUCE) | **tak, po walidacji**: do czasu treningu SH na Twojej historii HEDGING na netting pozostaje zablokowany (z podanym powodem) |
| **O4** | (c) oba reżimy w ledgerze | każda ocena zapisuje reżim `MarketRegimeEngine` (A) i `RegimeMachine v2` (B); `report.regimes` – tabela par z wynikiem planu | nie |
| **O6** | (b) scalp Sweep→Retest w ledgerze | słuchacz `ScalpService.listeners` → `EvaluationService.on_scalp_setup` (silnik `SCALP_SHADOW`, zdarzenie TP1 przed SL, także kandydaci BLOCKED/MISSED) | nie |
| O5, O7, O8 | nie wybrane | bez zmian | – |

Odpowiedź „Something else” w ankiecie przyszła bez treści – nie realizowano nic poza powyższym.

### 4.1 Opcje przedstawione do decyzji (stan sprzed wyboru)

Każda opcja ma wariant domyślny „bez zmian”. Rekomendacja jest moja, decyzja należy do użytkownika.

| ID | Problem | Opcje | Rekomendacja |
|---|---|---|---|
| **O1** | Dwie ścieżki mogą w PAPER/AUTO_DEMO jednocześnie otworzyć pozycje na tym samym instrumencie (STACKING) lub w przeciwnych kierunkach (CONFLICT); każda liczy ryzyko tak, jakby była sama (AR-02, AR-14) | (a) bez zmian; (b) **wspólna bramka ekspozycji**: nowe wejście odrzucane przy CONFLICT, przy STACKING łączne otwarte ryzyko obu ścieżek w limicie; (c) jedna ścieżka główna na instrument (wybór użytkownika), druga tylko SIGNALS | **(b)** – nie wyłącza żadnej strategii, usuwa niekontrolowane łączenie ryzyka |
| **O2** | Ocena P/EV jest SHADOW; decyzja S01–S12 nie używa EV, SH używa stałego progu P ≥ 0,55 | (a) SHADOW do zebrania próby; (b) ASSIST w PAPER: REJECT z oceny blokuje wejście, REDUCE zmniejsza wolumen o połowę; (c) próg SH z p* zamiast 0,55 | **(a) teraz, (b) po ≥ 200 dojrzałych ocenach per silnik** z kalibracją sprawdzoną w raporcie; (c) razem z (b) |
| **O3** | HEDGING na rachunku netting jest blokowany w całości | (a) bez zmian; (b) na netting HEDGING działa bez nogi hedge: przy zdarzeniu hedge → REDUCE (częściowe zamknięcie) | **(b)** – zgodne z §16 promptu; wymaga osobnej walidacji replay wariantu REDUCE |
| **O4** | Dwie definicje reżimu decydują w ścieżkach A i B (AR-05) | (a) bez zmian; (b) jeden kanoniczny reżim do routingu, drugi jako cecha; (c) zapisywać oba w ledgerze i rozstrzygnąć na danych | **(c)** – ledger już zapisuje reżim ścieżki A; dopisać reżim B do kandydatów A (i odwrotnie), decyzja po porównaniu |
| **O5** | Sześć nakładających się raportów audytu w katalogu głównym (AR-11) | (a) bez zmian; (b) przenieść stare do `docs/archiwum/` z indeksem | **(b)** – bez usuwania treści |
| **O6** | Scalp Range→Sweep→Retest (SHADOW) nie jest źródłem kandydatów w ledgerze | (a) bez zmian; (b) dopisać go jako trzecie źródło SHADOW | **(b)** – bez wpływu na zlecenia, daje porównanie trzech implementacji S2 |
| **O7** | SH liczy spread podwójnie w RR netto (AR-06) – konserwatywnie, ale część setupów odpada niepotrzebnie | (a) bez zmian; (b) koszt bez spreadu (spread jest już w cenie wejścia Ask/Bid) | **(b) dopiero z O2**: zmienia liczbę setupów SH przechodzących próg RR netto |
| **O8** | Promocja legacy ML: Brier ≤ bazowy bez marginesu błędu (AR-07) | (a) bez zmian; (b) wymóg poprawy Briera > 2 SE (jak `sh_tp_model`) | **(b)** – może zablokować promocję słabego modelu; nie zmienia działającego czempiona |

## 5. Konsolidacja dokumentacji (propozycja O5)

Aktualne: `ARCHITECTURE.md`, `COMPONENT_INVENTORY.md`, `INTEGRATION_MAP.md`, `REFACTOR_PLAN.md`, `CHANGELOG.md`, `ZNANE_OGRANICZENIA.md`,
`RUNBOOK_PL.md`, `START_TUTAJ_PL.md`, `docs/strategie_sh/*`, `docs/MASTER_MODELE_AUDYT_INTEGRACJA_PL.md`.
Do archiwum (treść zachowana): `ARCHITEKTURA.md` (1.13), `AUDIT.md`, `AUDIT_REPORT.md`, `AUDYT_MASTERQUO.md`, `AUDYT_WEJSCIOWY.md`, `RAPORT_1_3.md`.

## 6. Definition of Done (prompt §26) – stan na dziś

| # | Warunek | Stan | Uzasadnienie |
|---|---|---|---|
| 1 | Kompletna mapa rzeczywistej architektury | **SPEŁNIONY** | `ARCHITECTURE.md` + pomiar wywołań + `INTEGRATION_MAP.md` |
| 2 | Każdy aktywny model ma rolę i interfejs | **SPEŁNIONY** | rejestr `sh/models.py` (35 wpisów, rola i status), `COMPONENT_INVENTORY.md` §2 |
| 3 | Silniki strategii korzystają z centralnego systemu oceny setupów | **NIEUKOŃCZONY** | wszystkie trzy źródła (S01–S12, SH, scalp SHADOW) są oceniane centralnie, ale tylko w SHADOW – zgodnie z decyzją O2 ocena nie wpływa na decyzję przed zebraniem 200 ocen |
| 4 | Prawdopodobieństwa mają cel predykcji i metodę walidacji | **CZĘŚCIOWY** | każde P ma nazwane zdarzenie i źródło; S01–S12 nie mają modelu zdarzenia TP-przed-SL; żaden model nie jest wytrenowany na danych klienta |
| 5 | Niepewność i konflikty modeli | **CZĘŚCIOWY** | przedział Wilsona, REDUCE przy nieznanej/szerokiej niepewności; zgodność modeli: brak dwóch niezależnych skalibrowanych modeli tego samego zdarzenia |
| 6 | Scalping: realistyczne koszty i warunki wykonania | **CZĘŚCIOWY** | wejście po Ask/Bid, prowizja, poślizg, jakość spreadu; spread liczony podwójnie w SH (O7); brak danych o poślizgu brokera |
| 7 | Hedging ocenia ekspozycję i koszt zabezpieczenia | **CZĘŚCIOWY** | koszyk porównuje koszt hedge z redukcją, walidacja HEDGE/NO_HEDGE/REDUCE; na netting REDUCE zamiast hedge po walidacji (O3); brak wytrenowanych modeli na danych klienta |
| 8 | Wszystkie strategie korzystają ze wspólnego Risk Engine | **NIEUKOŃCZONY** | nadal dwa silniki ryzyka; od O1 na instrumencie wejścia otwiera tylko jedna ścieżka, więc ich ryzyko się nie sumuje; wspólne są STOP, wiązanie rachunku i wybór ścieżki |
| 9 | Trening i walidacja odseparowane od danych testowych | **SPEŁNIONY** | chronologiczne podziały z embargo, holdout oceniany raz (`sh/tpmodel.py`, `ml/validation.py`, master models) |
| 10 | Backtest uwzględnia ograniczenia egzekucji | **CZĘŚCIOWY** | konserwatywne świece niejednoznaczne, koszty; brak odrzuceń/requote i częściowych wypełnień brokera |
| 11 | Testy jednostkowe, integracyjne i regresyjne | **SPEŁNIONY** | pełny zestaw testów; nowe: `test_arch_fixes.py` (AR-01, O1, O3), `test_evaluation.py` (B, D, O2, O4, O6) |
| 12 | Dokumentacja odpowiada implementacji | **SPEŁNIONY dla dokumentów tego audytu** | starsze raporty – O5 |
| 13 | Nowe moduły podłączone do przepływu decyzyjnego | **CZĘŚCIOWY** | wybór ścieżki głównej (O1) i wariant REDUCE (O3) działają w przepływie decyzji; `EvaluationService` jest obserwatorem trzech źródeł (O2) |
| 14 | Bot potrafi bezpiecznie odmówić | **SPEŁNIONY** | pomiar 12 min: 21/21 decyzji zablokowanych z powodami; STOP w obu ścieżkach (AR-01); DEFER/REJECT oceny |
| 15 | LIVE nieaktywny bez zgody | **SPEŁNIONY** | Execution Lock `LOCKED`, SH odmawia AUTO_LIVE, żaden test ani trening nie zmienia trybu |

**Projekt nie jest ukończony w rozumieniu §26** – warunki 3 i 8 są nieukończone, a 4–7, 10 i 13 częściowe. Domknięcie 3 i 13 zależy od
zebrania 200 ocen per silnik i decyzji o ASSIST (O2); 4–7 i 10 – od treningu i walidacji na historii klienta (B-DATA); 8 – od połączenia
silników ryzyka (osobna decyzja, poza O1).
