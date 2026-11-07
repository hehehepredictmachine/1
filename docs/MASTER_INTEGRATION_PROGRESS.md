# Postęp integracji – wydanie 1.33.0 (wszystkie aktualizacje)

Źródło zadania: pakiet `PepeMarketWizard_Prompty_Wdrozenia_Wszystkich_Aktualizacji.zip` (SHA-256
`6ca0e38756856b93b1ed0c7ac8a93e5a0fce2998702a312b380347f6e4a3dc99`, dwa identyczne pliki) – `00_START_PROMPT.md` + 4 specyfikacje:
AUD (audyt, 15 rodzin modeli, trening), IND (wskaźniki, DXY, plany Scalp/Hedge, SVP), STU (Data & Training Studio),
ARC (architektura analizy i decyzji). Baza: 1.32.0 (commit `5e5d82a`), gałąź `claude/masterquo-ai-bot-mt5-f7uaht`.

Macierz wymagań: `docs/INTEGRATION_MATRIX.md` + `integration_manifest.json` (jedno źródło: `tools/integration_matrix.py`).

## Zasady rozstrzygnięte przed pracą
* **Execution Lock** – specyfikacje ARC/START wspominają o jego zachowaniu, AUD i polecenie użytkownika z 1.30 mówią, że jest
  wycofany i nie wolno go przywracać. Obowiązuje polecenie użytkownika: **nie przywracam**; zachowane są tryby SIGNALS/PAPER/
  AUTO DEMO/AUTO LIVE, STOP nowych wejść, limity i wymagania brokera.
* **Licencje / role** – usunięte w 1.30 na prośbę użytkownika; nie przywracam (AUD 2: „nie przywracaj”).
* Brak rzeczywistego MT5/Windows/GPU w środowisku pracy: kod, adaptery i testy offline powstają w całości; operacje zależne od
  brakującego zasobu są blokowane z powodem (BLOCKED_DATA / BLOCKED_DEPENDENCY), nigdy udawane.

## Decyzje architektoniczne
* Zależności: `statsmodels`, `arch`, `pandas`, `patsy` – do głównego środowiska (hash-pinned, `requirements-win.txt`); ARIMA/SARIMAX/
  GARCH/kointegracja liczą się w procesie bota poza wątkiem MT5. PyTorch (LSTM/GRU), Gymnasium + Stable-Baselines3 (PPO) –
  **osobne środowisko `.venv_deep`** i proces roboczy (wzorem `.venv_kronos`), żeby nie zmieniać bibliotek bota ani Kronosa.
* Nowe moduły: `indicators/` (kontrakt PMW-IND-1 i silniki), `plans/` (kontrakt planu PMW-PLAN-1), `svp/` (profil + strefy
  MANUAL/ALGORITHM/AI), `modelhub/families/` (15 rodzin), `studio/` (osobna aplikacja), `decision/` (DecisionRecord).

## Dziennik
| Data | Etap | Zmiany | Testy | Stan / następny krok |
|---|---|---|---|---|
| 2026-11-07 | U0 | przeczytane 5 dokumentów, inwentaryzacja runtime / bridge / TF / modelhub / trainhub / mm / zones | – | dalej: U1 kontrakt + M3 |
| 2026-11-07 | U1 | kontrakt PMW-PRED-2 (`modelhub/contract.py`: liczby skończone bez bool, schematy wyników per zadanie, horyzont >0 int lub sekundy, nowe typy VOLATILITY/PAIR_RELATION/MICROSTRUCTURE/FILTER_STATE/RL_ACTION/NLP_SENTIMENT, JSON bez NaN); M3 (rejestr TF, FakeMT5, fallback M1→M3 z flagą `complete`, eksport, TrainHub TF_S/HTF_OF, Kronos TF + horyzont); `dxy_missing` = rzeczywista dostępność (MQ-FEAT-1.2.0 + adapter starszych modeli); Kronos REQUIRED powiązany z odciskiem (symbol, horyzont, ustawienia, pasmo, rewizje wag) – nieaktualne dopuszczenie wstrzymuje setup | `test_integration_u1` (9), `test_kronos_bot`, `test_zones`, `test_time_and_data`: 83 OK; 26 plików powiązanych z predykcjami: 460 OK | AUD 3.1 odtworzone 4/4 i naprawione; AUD 3.2 cache – nie odtworzono (klucz z wersją + invalidate po aktywacji). Dalej: U2 |
| 2026-11-07 | U2 | `indicators/` (kontrakt PMW-IND-1; AVWAP SESSION/EVENT/MANUAL z czasem źródła i potwierdzenia + wersje kotwic; percentyl spreadu z próbkowaniem stałym zegarem i odniesieniem do tych samych slotów wcześniejszych sesji; semiwariancja 20/60 M1 z obsługą luk; cechy profilu sesji z DSVIE; OFI / nierównowaga / microprice z adapterem `market_book_*` przez kolejkę MT5 + archiwum; relacja XAUUSD×DXY na zwrotach H1 bez forward-fill, beta bez bieżącej obserwacji); `IndicatorService` w runtime (kontekst `view.context["indicators"/"dxy"]`, SCALPING/HEDGING jako OBSERVE, narzędzia agenta `get_pmw_indicators`/`get_dxy_relation`, API `/api/v1/indicators/*`); DSVIE RVOL: parametry historii i minimum, odrzucanie niepełnych sesji, `interval_relative_volume`; FakeMT5: arkusz demo | `test_indicators_u2` 30 OK; regresja 86 plików backendu OK po poprawkach | wykryta i naprawiona regresja U1: `TF_POLL` bez M3 (pętla mostu); testy liczby TF zaktualizowane o M3 |
| 2026-11-07 | U3 | `plans/` (PMW-PLAN-1: Pepe Scalp Plan / Pepe Hedge Plan z planu SH, koordynatora, ryzyka i maszyn stanów; plan vs fill, SL v2 po BE, cele tylko z danych wykonania, noga HEDGE, NETTING = niedostępne, warunek koszyka tekstowo; API `/api/v1/plans/chart`); `svp/` (PMW-SVP-1 na silniku DSVIE: tryby SESSION/RANGE/VISIBLE/LIVE/FROZEN, siatka w tickach, zachowanie wag, wersje profili, zamrażanie; strefy MANUAL/ALGORITHM/AI z wersjami i odtworzeniem na czas; reguły stanów; walidacja propozycji AI względem snapshotu; AI na żądanie i AI LIVE z limitem, deduplikacją i odrzuceniem starego wyniku; API `/api/v1/svp/*`; narzędzie agenta `get_svp_profiles`; `ClaudeAgent.propose_zones` z kosztem w `agent_runs`) | `test_plans_svp_u3` 21 OK | dalej: U4 rodziny modeli |
