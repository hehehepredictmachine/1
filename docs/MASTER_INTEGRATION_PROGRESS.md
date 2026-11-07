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
