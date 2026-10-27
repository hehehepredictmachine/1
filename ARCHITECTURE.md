# ARCHITECTURE – PepeMarketWizard 1.18 · audyt architektury (Faza A), 26.10.2026

Ten dokument zastępuje wcześniejszy opis 1.14 i pełni rolę **ARCHITECTURE_AUDIT**. Pozostałe raporty tego audytu:

| Raport z promptu | Plik w repozytorium | Uwagi |
|---|---|---|
| ARCHITECTURE_AUDIT.md | `ARCHITECTURE.md` (ten plik) | zaktualizowany zamiast tworzenia duplikatu |
| COMPONENT_INVENTORY.md | `COMPONENT_INVENTORY.md` | nowy; obejmuje wszystkie warstwy, nie tylko modele |
| DEPENDENCY_MAP.md | `INTEGRATION_MAP.md` | zaktualizowany zamiast tworzenia duplikatu |
| REFACTOR_PLAN.md | `REFACTOR_PLAN.md` | nowy; plan, decyzje do zatwierdzenia, Definition of Done |

## 1. Metoda (dowody, nie deklaracje)

1. **Graf importów (statyczny).** `ast` dla 281 modułów `backend/` – importy na poziomie modułu i wewnątrz funkcji, osiągalność z punktów
   wejścia (`serve`, trening, worker prognoz). Wynik: `INTEGRATION_MAP.md`.
2. **Pomiar działania (dynamiczny).** Bot uruchomiony na symulatorze MT5 pod `coverage`:
   * **pętla bota, 12 min, bez panelu** – co wykonuje się samo, w pętli decyzyjnej;
   * **panel, osobny przebieg** – Chromium przeszedł przez 21 stron panelu klasycznego i 12 ekranów Neural Cyberpunk (0 błędów strony).
   Klasyfikacja modułu: `CALLED` (wykonały się ciała funkcji), `IMPORT_ONLY`, `NOT_LOADED`. Wynik pętli: 149 / 53 / 81 modułów;
   z panelem: 173 / 49 / 61. Kolumna „wywoływany” w `COMPONENT_INVENTORY.md` pochodzi z tego pomiaru.
3. **Przegląd kodu** ścieżek decyzji, ryzyka, wykonania, hedgingu, kosztów, statystyk i rejestrów modeli (ścieżki i linie przy ustaleniach).
4. **Testy reprodukujące** dla każdego potwierdzonego błędu (`tests/test_arch_fixes.py`).

Ograniczenia: brak terminala użytkownika, brokera i historii z jego MT5. Symulator nie odtwarza spreadów, poślizgu, odrzuceń ani prowizji
brokera. „Nie wywołany w pomiarze” oznacza „nie wykonał się w 12 minutach na danych syntetycznych”, a nie „martwy kod” – martwy kod
oznaczam osobno, na podstawie kodu.

## 2. Rzeczywisty przepływ: od ceny do decyzji

```
MT5 terminal ──► MT5Worker (1 wątek; serializacja wszystkich wywołań; od 1.24 bez Execution Lock)
                   │
                   ▼
                MarketBridge (bufory M1…D1, świeca otwarta osobno, zegar serwera→UTC, konto, deale, ticki)
                   │
   ┌───────────────┼─────────────────────────────────────────────────────────────────────────────┐
   │  ŚCIEŻKA WYKONAWCZA A – profil ACTIVE (S01–S12)                                                │
   │  EngineService.light_cycle → dq (data/quality) → ActiveEngine: MarketRegimeEngine + scan S01–S12 │
   │  → SetupTracker → StrategyAutoSelector (rank = 0,35·fit + 0,65·score) → risk/engine (RR_NET,     │
   │  sizing, limity) → agent (VETO) → legacy ML (bramka tylko w ASSIST) → ModeManager.gate (+O1)    │
   │  → decision.build → ExecutionGateway (PAPER: PaperBroker / AUTO_*: worker) → PositionManager     │
   │  → managed_positions / trades → stats                                                            │
   ├───────────────────────────────────────────────────────────────────────────────────────────────┤
   │  ŚCIEŻKA WYKONAWCZA B – SCALPING / HEDGING (SHService)                                           │
   │  nowa zamknięta M1 → sh/context (własne dq + RegimeMachine v2) → sh/setup (checklista, P z       │
   │  sh_tp_model gdy READY) → coordinator → sh/risk (własne limity) → [AR-01/O1: STOP, wiązanie       │
   │  rachunku, ścieżka główna z ModeManager.gate] → SHExecutor (PAPER / AUTO_DEMO; AUTO_LIVE        │
   │  odmowa) → sh_plans / sh_events (od tej iteracji w statystykach per silnik – AR-04)              │
   ├───────────────────────────────────────────────────────────────────────────────────────────────┤
   │  SHADOW / OBSERVE (bez ścieżki do zleceń): ForecastService (proces .venv_candles), ScalpService   │
   │  (Range→Sweep→Retest), LabService, NSS, Structure Intelligence, Liquidity, Analytics, BotSignal-  │
   │  Service + MarketScanner (inne rynki), MMService (od 1.21 na każdej zamkniętej M5 + drift – AR-08)│
   ├───────────────────────────────────────────────────────────────────────────────────────────────┤
   │  NOWE (SHADOW, słuchacz obu ścieżek): ActiveEngine.listeners + SHService.listeners → Evaluation-   │
   │  Service → SetupCandidate → assess (P zdarzenia, EV, p*, niepewność, ekspozycja) → ledger →       │
   │  dojrzewanie z zamkniętych M1. Bez referencji do gateway / PaperBroker / SHExecutor               │
   └───────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Pomiar 12 min (symulator, świeża instalacja, tryb PAPER):** 21 decyzji ścieżki A – 19× WAIT, 2× NO_TRADE, wszystkie BLOCKED
(`RISK_LIMITS_NOT_CONFIGURED` 21, `AI_UNAVAILABLE_NO_KEY` 21, `COST_MODEL_UNKNOWN_COMMISSION` 18). Setupy S01/S07/S09/S10/S12 w
etapach WATCH/EARLY. Ścieżka B: 2 sygnały (WAIT „reżim przejściowy bez zgodnych interwałów”, NO_TRADE „reżim TRANSITION”); silnik
ryzyka SH ani gateway nie zostały wywołane – brak setupu, który doszedłby do ryzyka. Bot poprawnie odmawiał.

## 3. Odpowiedzi na pytania Fazy A

### 3.1 Struktura projektu
`backend/` (281 modułów w chwili pomiaru, z `gold_candles*`, ok. 58 tys. linii bez `vendor/`), `frontend/src` (42 pliki TSX, dwa panele: klasyczny – 22 strony, Neural
Cyberpunk – 12 ekranów), `mql5/` (kod natywny, nieskompilowany), `tests/` (76 plików, 856 testów w 1.21), `config/` (profile strategii i instrumentów),
launchery `.bat` i `PepeMarketWizard.exe`. Jeden proces bota + proces potomny prognoz (`.venv_candles`) + procesy treningu.

### 3.2 Modele i trening
35 wpisów w żywym rejestrze `sh/models.py` (18 deterministycznych, 16 trenowanych, agent). Modele trenowane: gold_candles, Scalp A/B,
legacy ML (DT/XGB), Lab (6 rodzin), indicator context, ML scalp, NSS (TCN), Structure Intelligence (7 rodzin), flow reaction, context move,
`sh_tp_model`, master models (HDC/GPR/event engine/STE-FlowNet). Runner treningu ma 17 zadań. **Żaden model nie ma artefaktu
wytrenowanego na danych klienta** (B-DATA) – na świeżej instalacji wszystkie trenowane modele mają status NOT_TRAINED/NO_CHAMPION.

### 3.3 Strategie i generowanie setupów
* Ścieżka A: S01–S12 (trend pullback, adaptive trend, wybicia kanału / kompresji / sesji, breakout-retest, failed-breakout reclaim, powrót do
  średniej ×2, wyczerpanie, EMA pullback, rodzina walls/range) na M5/M15 (S12: M1/M5); router = StrategyAutoSelector z tabelą `regime_fit`.
* Ścieżka B: SCALPING (kontynuacja/odwrócenie M1, TP 2,5/3/5 USD) i HEDGING (koszyk z hedgem, TP 3,5/5/9).
* SHADOW: Scalp Range→Sweep→Retest, reguły master models (Multi-Indicator, SMC FVG), scenariusze lab, sygnały innych rynków.
* **Proponowany pakiet S1–S6 już istnieje** (mapowanie w `REFACTOR_PLAN.md` §3) – nowe pliki strategii byłyby duplikatami.

### 3.4 Które modele są aktywne, a które istnieją tylko w kodzie
* Wpływ na decyzję ścieżki A mają tylko: legacy ML (wyłącznie tryb ASSIST, domyślnie SHADOW) i agent Claude (VETO; bez klucza nie blokuje).
* Wpływ na decyzję ścieżki B: `sh_tp_model` (gdy READY; jest NOT_TRAINED) i deterministyczne bramki SH.
* Pozostałe modele działają w SHADOW/OBSERVE albo wcale: flow reaction i context move – trening bez inferencji na żywo (F-17); HedgeController
  scalp – logika decyzji nie wykonuje się (F-16; pomiar: 2/8 funkcji, tylko konstruktor i nazwa trybu marży); `mm/drift.py` – brak wywołań
  poza testami; master models – liczone tylko, gdy panel pyta `/api/v1/mm/live` (pomiar pętli: 1/84 funkcji).

### 3.5 Jak dziś liczone są prawdopodobieństwo, EV i ryzyko
| Wielkość | Ścieżka A (S01–S12) | Ścieżka B (SH) |
|---|---|---|
| prawdopodobieństwo | `setup_score` 0–100 = heurystyka (nie P). P tylko z legacy ML: zdarzenie „net R > 0 wg planu”, kalibrowane, bramka w ASSIST z progiem z bloku kalibracji | `score` = heurystyka; P(TP2 przed SL) z `sh_tp_model` (Platt na bloku kalibracji), próg stały `tp_model_min_prob = 0,55` |
| EV | **nie jest liczone**; jest RR_NET = (Σ wᵢ·zysk do TPᵢ − koszt)/(strata do SL + koszt) | **nie jest liczone**; jest RR netto całego cyklu (`net_rr`) |
| ryzyko | `risk/engine.py`: budżet % equity, limity dzienne / DD / otwarte ryzyko / depozyt / ekspozycja (kalkulatory brokera); domyślnie limity **nieustawione** → blokada | `sh/risk.py`: własne limity %, koszyk HEDGING, typ rachunku, prowizja wymagana w AUTO |
| koszty | prowizja z historii deali, `slippage_stress_points` 20 pkt | spread + 2·`slippage_usd` + prowizja; spread liczony podwójnie (AR-06) |

### 3.6 Duplikaty i niespójności (szczegóły: `INTEGRATION_MAP.md`, `REFACTOR_PLAN.md`)
Dwie ścieżki wykonawcze z dwoma silnikami ryzyka (AR-02), dwie definicje reżimu w ścieżkach decyzyjnych (AR-05), trzy modele kosztów (AR-06),
co najmniej cztery rejestry cech i ponad osiem ledgerów predykcji (AR-10), trzy implementacje wejścia po sweepie płynności (S07/S12, SH
SCALPING-odwrócenie, scalp SHADOW), trzy rejestry modeli (żywy `sh/models.py`, statyczny `MAPA_MODELI_I_TRENINGU.*` z 1.15, `mm/inventory.py`).

## 4. Rejestr ustaleń

Waga: **K** krytyczne (bezpieczeństwo/kapitał), **W** wysokie, **Ś** średnie, **N** niskie.

| ID | Waga | Gdzie | Ustalenie | Dowód | Status |
|---|---|---|---|---|---|
| AR-01 | K | `sh/service.py` `_tick`/`cycle` | SCALPING/HEDGING czytał z `ModeManager.gate()` tylko nazwę trybu – **STOP (kill switch) nie zatrzymywał nowych planów SH**, ignorowane były też powody wiązania rachunku w AUTO_DEMO | `test_arch_fixes.ShStopGate` – przed poprawką plan otwarty przy STOP (stan OPEN) | **naprawione**: SH respektuje STOP, Execution Lock i powody rachunku; zarządzanie otwartymi planami trwa |
| AR-02 | W | `engine/service.py`, `sh/service.py`, `risk/engine.py`, `sh/risk.py` | Dwie niezależne ścieżki wykonawcze na tym samym instrumencie. W PAPER żadna nie widzi pozycji drugiej (SH: `foreign_positions` tylko w AUTO_DEMO; legacy: `managed_positions`). Możliwe dwie równoległe ekspozycje lub przeciwne kierunki | przegląd kodu | **O1 wdrożone (1.20)**: jedna ścieżka główna na instrument, druga tylko analizuje; widok łącznej ekspozycji (tylko odczyt) |
| AR-03 | W | `engine/decision.py`, `strategies/selector.py`, `sh/setup.py` | Brak P(TP przed SL) i EV w decyzji ścieżki A; router z wagami 0,35/0,65 bez wyników OOS; próg P w SH stały (0,55), nie z kosztów i R:R | przegląd kodu | kontrakt + silnik oceny w SHADOW (wdrożone); użycie jako bramki – **decyzja O2** |
| AR-04 | W | `stats.py`, `/api/v1/stats` | Statystyki, win rate, PF, R i krzywa equity liczone tylko z `trades`; wyniki planów SH (`sh_plans`) nie są wliczane | `grep INTO trades` – zapisują tylko gateway/manager/paper | statystyki per silnik + łącznie; 1.21: metryki §22 (średni zysk/strata, max DD, per strategia, per miesiąc) |
| AR-05 | Ś | `strategies/regime.py`, `lab/market_v2.py`, `sh/context.py` | Dwie różne definicje reżimu decydują w ścieżkach A i B – ten sam rynek może być TREND dla A i TRANSITION dla B | przegląd kodu | **O4 wdrożone (1.20)**: oba reżimy zapisywane przy każdej ocenie; wybór kanonicznego po zebraniu danych |
| AR-06 | Ś | `risk/costs.py`, `sh/setup.py`, `scalp/replay.py` | Trzy modele kosztów; SH liczy spread podwójnie (wejście po Ask, a spread także w koszcie round-trip) → RR netto zaniżone (konserwatywnie) | `sh/setup.py:150` i koszt w `sh/setup.py` (krok 7) | plan: jeden model kosztów; zmiana progu przejścia SH wymaga decyzji |
| AR-07 | Ś | `config.py` `MLPromotion.max_brier_vs_baseline = 0.0` | Bramka promocji legacy ML: Brier ≤ bazowy bez marginesu błędu – ta sama słabość co F-19 w `sh_tp_model` (szum może przejść), częściowo łagodzona przez wymóg net R i błędu kalibracji | przegląd kodu | **O8 wdrożone (1.21)**: zysk Briera > 2 błędy standardowe (jak `sh_tp_model`); modele bez SE wymagają retreningu |
| AR-08 | Ś | `mm/service.py` | Inferencja master models tylko na żądanie panelu – ledger GPR ma luki, gdy panel jest zamknięty; `mm/drift.py` niewywoływany | pomiar pętli: 1/84 funkcji `mm/*` | **wdrożone (1.21)**: własny wątek SHADOW na każdej zamkniętej M5, dryf kalibracji GPR z `mm/drift.py` |
| AR-09 | Ś | `scalp/hedge.py`, `sh/hedge_fsm.py` | HedgeController scalp nie podejmuje decyzji (F-16). Aktywny hedge to koszyk HEDGING, który na rachunku netting **blokuje się**, bez alternatywy REDUCE | pomiar: 2/8 funkcji; `sh/risk.py` `account_hedging` | **O3 wdrożone (1.20)**: na NETTING REDUCE zamiast hedge, dopuszczone po walidacji replay na danych klienta |
| AR-10 | N | wiele | Duplikaty infrastruktury: ≥4 rejestry cech, >8 ledgerów predykcji, 2 implementacje jakości danych, 3 rejestry modeli | `INTEGRATION_MAP.md` §3 | plan konsolidacji |
| AR-11 | N | dokumentacja | Opisy architektury nieaktualne (1.13–1.15), sześć nakładających się raportów audytu | daty i wersje w nagłówkach | ARCHITECTURE/INTEGRATION_MAP zaktualizowane; **O5 (1.21)**: sześć starych raportów w `docs/archiwum/` z indeksem |
| AR-12 | N | `api/app.py` | 241 endpointów w jednym pliku (ok. 2300 linii) | `grep -c @app.` | plan (podział na routery bez zmiany ścieżek) |
| AR-13 | Ś | `strategies/*`, `sh/*`, `scalp/*` | Pakiet S1–S6 z promptu pokrywa się z istniejącymi S01–S12 i SH; nowe moduły byłyby duplikatami | §3.3 | mapowanie zamiast nowych plików |
| AR-14 | N | `config.RiskLimits` | Świeża instalacja: ścieżka A w PAPER nie handluje (limity nieustawione), a ścieżka B handluje w PAPER na własnych limitach – niespójne domyślne zachowanie | pomiar 12 min | rozwiązane przez O1: bez wybranej ścieżki głównej żadna ścieżka nie otwiera nowych wejść |
| AR-15 | N | pakiety | Cykle importów pakietów (analysis↔lab, analysis↔strategies, analytics↔scalp, extind↔scalp) rozwiązane importami leniwymi | graf importów | plan |
| AR-16 | N | hedging | Brak hedgingu korelacyjnego międzyinstrumentowego – w allowliście są tylko XAUUSD i BTC, korelacja niestabilna | `assets/registry.py` | NIE DOTYCZY (udokumentowane) |

| AR-17 | W | `risk/engine.py`, `sh/risk.py` | Limity dziennej straty i liczby pozycji liczone osobno w każdej ścieżce – żadna nie widzi wyniku drugiej (w PAPER także strat) | przegląd kodu | **wdrożone (1.21)**: wspólny strażnik portfela `risk/portfolio.py` w `ModeManager.gate(path=…)` – wynik dnia i pozycje obu ścieżek wobec ostrzejszego limitu |

Ustalenia F-01…F-21 z audytu SH (`docs/strategie_sh/01_AUDYT_ARCHITEKTURY.md`) pozostają ważne; nowe numery AR-xx ich nie dublują.

## 5. Gotowość do integracji scalping + hedging

* **Gotowe:** wspólna analiza SH, cykl życia z partialami i BE po potwierdzonym TP2, idempotentne akcje, rekonsyliacja, replay z konserwatywnym
  rozstrzyganiem świec niejednoznacznych, porównanie HEDGE / NO_HEDGE / REDUCE w walidacji, kontrola typu rachunku, Execution Lock.
* **Brakujące, by działało jako jeden mechanizm:** wspólna ekspozycja portfela dla obu ścieżek (AR-02), jedno źródło P i EV dla każdego setupu
  (AR-03 – kontrakt i silnik w SHADOW już są), statystyki obejmujące oba silniki (AR-04), alternatywa REDUCE dla rachunków netting (AR-09),
  wytrenowane i skalibrowane modele zdarzeń na danych klienta (B-DATA).
* **Wniosek:** architektura pozwala na integrację na poziomie SHADOW teraz; używanie prawdopodobieństwa jako bramki ma sens dopiero po
  treningu i walidacji na historii klienta. Tryb LIVE pozostaje zablokowany.
