# Mapa paczki 1.23.0 — punkt startowy dla Claude Code

Zrobiono przegląd statyczny struktury i wybranych plików archiwum. To nie jest wynik uruchomienia bota, kompilacji aplikacji Windows ani testu rachunku MT5. Dokumenty w samym projekcie mogą opisywać starsze wersje; każdy element trzeba ponownie sprawdzić w kodzie.

| Obszar | Miejsca do sprawdzenia | Co zaobserwowano |
|---|---|---|
| Desktop | `PepeMarketWizard.exe`, `tools/launcher/`, pliki `.bat` | Wcześniejszy EXE jest launcherem; potrzebna docelowa aplikacja z własnym oknem. |
| Frontend | `frontend/src/`, `frontend/package.json`, `frontend/src/router.ts`, `frontend/src/store.tsx`, `frontend/src/api.ts` | Frontend React/TypeScript. Istnieją starsze ekrany i szkielety nowych widoków. |
| Trzy nowe panele | `frontend/src/features/trading-intelligence/`, `ai-neural-lab/`, `system-control/` | Pliki widoków oznaczają sekcje jako niezintegrowane / etap 1. Obecność komponentów nie dowodzi działania. |
| Dane MT5 | `backend/masterquo/mt5/bridge.py`, `worker.py`, `clock.py`, `fake.py` | Worker pośredniczy w dostępie do MT5. Terminal i rachunek użytkownika nie były dostępne. |
| Decyzje ACTIVE | `backend/masterquo/engine/`, `strategies/`, `risk/` | Strategie S01–S12, wybór i ryzyko do sprawdzenia wraz z bieżącą konfiguracją. |
| Scalping/hedging | `backend/masterquo/sh/`, `scalp/` | Osobna ścieżka SH; w sprawdzonym `sh/executor.py` istnieje odmowa AUTO LIVE dla SH. Przebudowa wymaga audytu i testów, bez udawania, że live jest gotowy. |
| Tryby i STOP | `backend/masterquo/execution/modes.py`, `gateway.py`, `manager.py`, `manual.py`, `paper.py` | W kodzie opisano SIGNALS/PAPER/AUTO_DEMO/AUTO_LIVE i STOP nowych wejść; sprawdź wszystkie wywołania i testy. |
| Execution Lock | `backend/masterquo/config.py`, `runtime.py`, `mt5/worker.py`, `execution/`, `sh/`, `api/app.py`, frontend i testy | Blokada występuje w wielu miejscach, nie tylko w interfejsie. Starszy lock ma przestać wpływać na wykonanie zgodnie z aktualną decyzją użytkownika. |
| Modele i trening | `backend/masterquo/ml/`, `lab/`, `mm/`, `training/`, `train_all.py`, `MODEL_CARDS/` | Istnieją komponenty i karty modeli; ich faktyczne wytrenowanie i rolę w decyzjach trzeba potwierdzić. |
| Stare materiały | `ARCHITECTURE.md`, `INTEGRATION_MAP.md`, `COMPONENT_INVENTORY.md`, `REFACTOR_PLAN.md`, `START_TUTAJ_PL.md` | Przydatne źródła hipotez i map, ale mogą być nieaktualne. W konfliktach pierwszeństwo mają aktualne instrukcje użytkownika i sprawdzony kod. |

## Ważne rozróżnienia

- Trzy dołączone pliki w `01_WIDOKI/` są **makietami poglądowymi**. Nie są połączone z MT5, nie wykonują zleceń, nie udowadniają skuteczności modeli. W części przeglądarek zapis preferencji w podglądzie może być ograniczony przez izolację iframe.
- Symbol `XAUUSD-` to deklaracja użytkownika. Należy zweryfikować metadane brokera i dobrać BTC z jego listy, zamiast zakładać konkretny suffix.
- Nie stwierdzono działania na żywym MT5, kompletności historii klienta ani faktycznego wytrenowania modeli. Nie było uruchomienia backtestu, walidacji strategii ani builda EXE.
- Poprzednie instrukcje zachowania Execution Lock są zastąpione przez aktualną decyzję użytkownika o jego wyłączeniu. Nie oznacza to zezwolenia na testowe zlecenia LIVE.
