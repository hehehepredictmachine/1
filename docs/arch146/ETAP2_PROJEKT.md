# Etap 2 – projekt docelowej architektury (Apollo23 1.46.0)

Projekt powstał na podstawie diagnozy (`ETAP1_DIAGNOZA.md`, 140 pozycji z `plik:linia`) i inwentaryzacji modeli (Etap 3.1). **Duże ruchy (Etap 4)
czekają na Twoją zgodę.** Bez zgody robię tylko rzeczy neutralne dla zachowania (§6). Każda zmiana, która mogłaby zmienić decyzję handlową,
jest na liście decyzji (§7) i — jeśli ją przygotuję — trafia za flagę, domyślnie OFF.

## 1. Zasady projektu

1. **Jedno źródło prawdy na pojęcie.** Pozostałe miejsca są widokami (czytają i przeliczają, nie przechowują), adapterami (tłumaczą stary
   interfejs na nowy) albo plikami generowanymi z kodu (inwentarz, mapa modeli). Test architektury pilnuje, żeby nie powstał drugi rejestr.
2. **Przebudowa przez opakowanie, nie przez przepisanie.** Nowy moduł najpierw opakowuje istniejący kod (te same funkcje, te same liczby).
   Stara ścieżka importu zostaje jako cienki alias (shim) z ostrzeżeniem w docstringu. Dzięki temu testy (2454) i `vendor/` działają bez zmian.
3. **Kontrakty publiczne bez zmian:** trasy `/api/v1/...`, klucze `config.json`, pliki w `data/`, launchery `.bat`, polecenia CLI. Nowe rzeczy
   są wyłącznie dodatkami (nowe pole w odpowiedzi, nowe polecenie). Zmiana formatu = alias + migracja + `tools/migration_check.py`.
4. **Dowód neutralności po każdym kroku:** pełne testy + `tools/golden_run.py replay` + `compare` z przebiegiem z Etapu 0. Wynik replay musi
   być identyczny (decyzje ścieżki A, 20 wariantów SH pack). Inaczej krok jest cofany.
5. **LIVE nietknięty.** Nie dotykam `start_mode`, `live_autobind`, `ModeManager`, `execution/gateway.py` ani ścieżek zleceń MT5. Composition root
   odtwarza obecne zachowanie bit w bit, łącznie ze znanym martwym warunkiem `runtime.py:87` (D1).

## 2. Jeden przepływ danych

```
 MT5 (mt5/bridge, mt5/fake w DEMO)
   │ ticki, świece, konto, historia deali (+ zegar serwera: data/pcclock)
   ▼
 marketdata/ ── store, sources, quality ──► dq.core: JEDEN zestaw czystych kontroli (geometria, kolejność, duplikaty, luki, świeżość)
   │                                         polityki per tor: ACTIVE (data/quality) i SH (sh/context) – progi bez zmian
   ▼
 features/ ── kanoniczny słownik cech + rejestr schematów (id, wersja, fingerprint) ── buildery zostają u właścicieli
   │          (strategies/indicators→indicators, scalp SETUP_FEATURES, quant/features, trainhub/features, extind, lab, mm, ml)
   ▼
 modele (producenci) ── rejestr kanoniczny quant/ids.py (id, aliasy, kategoria, środowisko, właściciel, StatusAdapter, UseAdapter)
   │   rodziny (modelhub/families), trainhub, mm, Kronos, TSFM, gold_candles, ML legacy/scalp, extind, lab, Monte Carlo, Quant MetaModel/TabICL
   │   każdy producent zwraca rekord w JEDNYM kontrakcie predykcji (modelhub/contract PMW-PRED-2 / quant PMW-PRED-1 – patrz §4.6)
   ▼
 evaluation/ + quant/ ── ocena kandydatów i MetaModel; zapisy do magazynów ledgerów ── ledgers/: JEDEN widok PMW-LEDGER-VIEW-1 (tylko odczyt)
   ▼
 koordynator ── decision/coordinator.py (ścieżka A, S01–S12) i sh/coordinator.py (ścieżka B) – reguły i progi bez zmian
   ▼
 bramka ryzyka ── risk/engine.py + ModeManager.gate(path) (O1 ścieżka główna) + koszty: costs/ (JEDEN resolver, polityki per tor)
   ▼
 wykonanie ── execution/gateway → paper (PAPER) / MT5 DEMO; LIVE: bez zmian, poza zakresem przebudowy
   ▼
 statystyki ── stats.py, analytics/, evaluation report, exports/ (15 eksporterów 1.46)
```

Wszystkie usługi powstają w **jednym miejscu** (`runtime.py`, §3) i tam są łączone. API, Studio i CLI dostają gotowe usługi z `Runtime`,
niczego nie konstruują same.

## 3. Drzewo docelowe

Pogrubione = nowe moduły; *kursywa* = moduły, które zostają, ale zmieniają rolę na widok/adapter. Reszta pakietów (`strategies/`, `sh/`,
`engine/`, `lab/`, `mm/`, `kronos/`, `tsfm/`, `baskets/` …) zostaje na miejscu.

```
backend/masterquo/
├── runtime.py                  JEDYNY composition root: compose(cfg_dir, demo) -> Services + Runtime(start/stop, Lifecycle wątków)
│                               (przejmuje obiekty tworzone dziś w api/app.py, api/wf32_routes.py, studio, CLI – §5)
├── **registry_io.py**          strict read / blokada OS (jak trainhub/registry.reg_lock) / unikalny tmp + os.replace
│                               dla WSZYSTKICH rejestrów aktywacji i wskaźników (lab ACTIVE.json, mm SHADOW_ACTIVE.json,
│                               Monte Carlo registry.json, quant pointer, trainhub registry.json, rodziny, gold_candles, forecast)
├── quant/ids.py                KANONICZNY rejestr modeli: ALIASES/GROUPS/FAMILY_OWNED/RULES (jak dziś)
│                               + **PRODUCERS**: kategoria, środowisko, moduł właściciela, StatusAdapter, UseAdapter, id REQUIRED
│                               + brakujący producenci: tsfm:tirex2, quant:tabicl_v2, quant:metamodel, research:* (tylko dopisanie)
├── *quant/inventory.py*        generowany widok rejestru (docs/quant/INVENTORY.*) – bez zmian formatu
├── *sh/models.py*              widok: wiersze SH = aliasy id kanonicznych (participation bez zmian)
├── *modelhub/catalog.py*       widok: wiersz na producenta kanonicznego + canonical_id/aliases (stare pola i id zostają)
├── *mm/inventory.py*           widok rejestru dla obszaru mm
├── modelhub/
│   ├── contract.py             kontrakt predykcji (jak dziś) + walidator wspólny dla adapterów
│   └── **check.py**            `python -m masterquo models check [--smoke]` (§4.7) + launcher `.bat`
├── **features/**
│   ├── catalog.py              kanoniczny słownik cech: nazwa z jednostką/oknem, impl -> jedna funkcja, aliasy {rejestr: stara_nazwa}
│   └── schemas.py              rejestr 25 schematów: id, wersja, właściciel, lista cech, fingerprint (hash wyjścia na zamrożonym fixture)
├── **ledgers/**                PMW-LEDGER-VIEW-1: rejestr magazynów (te same funkcje ścieżek co writery), adaptery tabel,
│                               label_policy, instrument/run_mode/data_kind – tylko odczyt, bez migracji, writery bez zmian
├── **costs/**                  jeden resolver kosztów: CostProfile(tor, instrument), spread_policy, unknown_commission_policy;
│   │                           każdy tor deklaruje DZISIEJSZĄ politykę (neutralnie); O7 za flagą (D2)
│   └── (risk/costs.py, sh/setup.py, scalp, evaluation, quant/events wołają resolver z własną polityką)
├── data/quality.py             + **dq core** (czyste kontrole); sh/context.py mapuje na swoje obecne kontrole
├── training/
│   ├── core.py                 + **jedna usługa blokad treningu** ('train:<inst>', 'export:<inst>'), DatasetRef w manifeście
│   │                           (Etap 4: implementacja w liściu L0 `locks.py`, core = wejście `LOCKS` + cienkie wrappery RUNNING.lock)
│   └── **promotion.py**        jedna polityka promocji/aktywacji (krok 1: tylko liczy i loguje; egzekwowanie = decyzja D6/D7)
├── indicators/                 + wskaźniki z strategies/indicators.py (shim zostaje) – zrywa cykl pakietów analysis↔strategies
└── api/
    ├── app.py                  create_app: middleware, sesja, bezpieczeństwo, montowanie routerów; re-eksport body_num,
    │                           deals_coverage_from_utc (importują je testy)
    └── **routes/**             <domena>.py z register(app, rt, ctx) – wzorzec już użyty w wf32_routes/export_routes/owner_routes;
                                ścieżki, metody, nazwy handlerów i kody błędów bez zmian (test: zbiór METHOD+PATH przed == po)
```

### 3a. Mapa warstw i strażnik importów leniwych (I0084)

Mapa jest danymi w `tools/cycles.py` (`LAYERS`, każdy pakiet i moduł najwyższego poziomu `masterquo` ma warstwę; nowy pakiet bez warstwy
= błąd testu):

| Warstwa | Komponenty |
|---|---|
| L0 liście | `masterquo` (pakiet), paths, timeutil, version, events, registry_io, sysres, secrets_store, resources, assets, media, prefs, config, presets, contracts (rekordy kontraktów, tylko stdlib), settings_store (pliki ustawień), localapi (klient lokalnego API dla CLI), runtimes (rejestr środowisk modeli), procs (rejestr procesów treningu serwera, I0100), locks (jedna usługa blokad treningu i eksportu PMW-LOCKS-1, Etap 4; wejście `training.core.LOCKS`) |
| L1 dane | db, mt5, marketdata, data, markets, news, notify, licensing, stats |
| L2 analizy | indicators, analysis, analytics, svp, zones, orderflow, plans |
| L3 rdzeń handlowy | strategies, risk, engine, execution, decision, sh, baskets |
| L4 SHADOW / badania / modele | lab, ml, tsfm, kronos, quant, modelhub, trainhub, mm, extind, scalp, forecast, evaluation, montecarlo, research, apollo, trader_life_game, ledgers (widok PMW-LEDGER-VIEW-1), features (słownik cech PMW-FEAT-DICT-1) |
| L5 kompozycja | runtime, api, `__main__`, train_all, bootstrap, diagnostics, upgrade, desktop, agent, exports, studio, training, wf32_services (usługi modułów v3.2 budowane przez Runtime) |

Krawędź w obrębie jednej warstwy jest dozwolona; import z warstwy niższej do wyższej to krawędź „w górę”. `tools/cycles.py` zbiera przez
`ast` WSZYSTKIE importy wewnętrzne (modułowe, w funkcjach/metodach i dynamiczne `__import__`/`import_module` z literałem). Dzisiejsze
krawędzie w górę (56 par moduł → moduł po scaleniu fali 2b, m.in. sh → lab/kronos/tsfm/modelhub/trainhub/mm/montecarlo, decision →
quant/tsfm/evaluation, engine → extind/scalp; do liści bez importów wewnętrznych: config/sh.models → quant.ids, config → strategies.ids,
ml → training.promotion – kandydaci do przeniesienia do L0 w Etapie 4) są zapisane jako baseline w `tests/data/layer_baseline.json`. Test
(`tests/test_arch146_w2_tools_cli.py::TestLayerGuard`) nie przechodzi przy NOWEJ parze w górę; para usunięta jest tylko informacją.
Klucz to para modułów, numery linii są informacyjne (edycja pliku nie psuje strażnika). Po przeglądzie zmiany baseline odświeża
`python tools/cycles.py --write-baseline` (także po scaleniu każdej grupy, która dodaje komponent albo parę w górę – test je wskaże). Przeniesienie importów i porty wstrzykiwane przez `runtime` (wzorzec `scalp.extind`,
`sh.predictions_provider`) to Etap 4. Strażnik nie zmienia kodu wykonywanego ani decyzji.

## 4. Jedno źródło prawdy – pojęcie po pojęciu

| Pojęcie | Dziś (diagnoza) | Docelowo (źródło prawdy) | Pozostałe miejsca | Zmienia decyzje? |
|---|---|---|---|---|
| **Tożsamość modelu** | 8 katalogów deklaratywnych + 2 agregaty; panel czyta tylko niepełny `/api/v1/models/catalog`; TiRex-2, TabICL, MetaModel, research poza rejestrem | `quant/ids.py` (+ `PRODUCERS`) | `sh/models`, `modelhub/catalog`, `mm/inventory`, `quant/inventory`, `docs/quant/INVENTORY.*`, mapa modeli: widoki/generowane | nie (tylko prezentacja i dopisanie id) |
| **Stan i rola modelu** | ≥10 magazynów „aktywnej wersji”; role statyczne w `sh/models` rozjeżdżają się z dynamicznym `use`; cykl SH zapisuje statusy z `matrix(rt=None)` | StatusAdapter (stan z istniejących sond) + UseAdapter (OFF/SHADOW/OBSERVE/ASSIST/REQUIRED z ustawień) per producent | magazyny aktywacji zostają u właścicieli, ale zapis przez `registry_io` | nie |
| **Rejestry aktywacji** | 4 rejestry czytają nieczytelny plik jako pusty i zapisują go z powrotem (utrata stanu, **K**) | `registry_io` (strict read + blokada + atomowy zapis) | wszyscy właściciele rejestrów | nie (ochrona danych) |
| **Cechy** | 25 schematów wersjonowanych samymi nazwami; te same nazwy = różne formuły | `features/catalog.py` + `features/schemas.py` (id, wersja, fingerprint) | buildery zostają u właścicieli; artefakty zapisują fingerprint, przy ładowaniu porównanie | nie (fingerprint obecnego kodu = obecne zachowanie; artefakty bez fingerprintu = legacy jak dziś) |
| **Ledger** | 15 tabel + 3 pliki, każdy z innym kluczem; 4 definicje wyniku tego samego kandydata | `ledgers/` PMW-LEDGER-VIEW-1 (widok) | writery bez zmian | nie |
| **Koszty** | ≥4 konwencje w torach decyzyjnych, 3 źródła prowizji, 3 jednostki poślizgu, 4 polityki nieznanej prowizji | `costs/` resolver; każdy tor deklaruje swoją dzisiejszą politykę | `risk/costs.py`, `sh/setup.py`/`sh/risk.py`, scalp, evaluation, quant/events – wołają resolver | **nie** w wersji neutralnej; O7 i ujednolicenie = D2/D3 |
| **Jakość danych** | 2 żywe bramki z różnymi regułami (ACTIVE `data/quality.py`, SH `sh/context.py`) | wspólny rdzeń czystych kontroli | polityki per tor (które kontrole blokują, progi) bez zmian | nie |
| **Kontrakt modelu** | modelhub PMW-PRED-2 i quant PMW-PRED-1 + własne słowniki rodzin/MM/Kronos | jeden walidator kontraktu w `modelhub/contract.py`; adaptery tłumaczą | – | nie |
| **Orkiestracja treningu** | 1 rdzeń (runner) + ≥10 ścieżek równoległych, 7 mechanizmów blokad | `training/core.py`: jedna usługa blokad + DatasetRef; runner = jedyny orkiestrator wieloetapowy | ścieżki per model zostają jako kroki/CLI, ale biorą blokadę z core | nie (polityka promocji: D6/D7) |
| **Instrumenty** | listy instrumentów w kodzie w kilku miejscach | `instruments_v1.json` przez `mq_instruments.profiles()` | – | nie |
| **Composition root** | 5 miejsc tworzy usługi i wątki (`runtime.py`, `api/app.py`, `wf32_routes`, Studio, CLI) | `runtime.py` | API/Studio/CLI dostają usługi z `Runtime` | nie (D1 pozostaje jak dziś) |

## 5. Mapa „stary moduł → nowe miejsce”

| Stary moduł / miejsce | Nowe miejsce | Co zostaje w starym miejscu |
|---|---|---|
| obiekty tworzone w `api/app.py` (security, presets, rejestr procesów, AccountCenter, Hyperliquid/Universe, TrialLedger) i `api/wf32_routes.py` (IndicatorEngine) | `runtime.compose()` | API czyta `rt.<usługa>` |
| `api/app.py` – 436 tras w jednej funkcji `create_app` (3976 linii) | `api/routes/{core,trading,market,models,training,quant,sh,lab,mm,kronos_tsfm,analytics,baskets,exports,...}.py` | `create_app` montuje routery; re-eksport funkcji używanych w testach |
| `api/*` sięga do prywatnych pól usług (6 miejsc) i `bridge._lock` (8 miejsc) | publiczne metody usług (np. `bridge.deals_snapshot()`, `ml.clear_prediction_cache()`) wołające dokładnie ten sam kod | – |
| `lab/protocol.py:320-344`, `mm/artifacts.py:112-145`, `montecarlo/validate.py:312`, quant pointer, `trainhub/registry.py` (`_reg`/`_save_reg`) | `registry_io.py` | funkcje właścicieli wołają `registry_io` |
| `studio/importer` – zapis `registry.json` trainhub bez `reg_lock` | `trainhub.registry.register_imported_version()` pod blokadą | – |
| `sh/models.py` (statyczny rejestr ról), `modelhub/catalog.py`, `mm/inventory.py` | widoki `quant/ids.PRODUCERS` | dotychczasowe pola i id w odpowiedziach API |
| `strategies/indicators.py` | `indicators/` (ten sam kod) | shim `from masterquo.indicators... import *` |
| `risk/costs.py`, `sh/setup.py:244-261`, `sh/risk.py:99-101`, `scalp/strategy.py:553`, `evaluation/service.py:124-138`, `quant/events.py:225-230`, etykiety ML/trainhub/extind | `costs/` (resolver + polityki per tor) | wywołania resolvera z dzisiejszą polityką |
| `data/quality.py` i `sh/context.py` (kontrole DQ) | wspólny rdzeń w `data/quality.py` | polityki per tor |
| locki: `training/runner` `RUNNING.lock`, `trainhub/registry.reg_lock`, blokady rodzin, Studio, Quant train, ML w bocie, 12_/17_ `.bat` | `training/core.py` – usługa blokad (Etap 4: `locks.py` L0, nazwy `train`/`export`/`registry`/`job`) | cienkie wrappery (te same pliki blokad, rekordy właściciela i TTL) |
| reguła „APPROX/syntetyczny nigdy championem” (tylko w `ml/offline.py`) | `training/promotion.py` (krok 1: liczy i loguje dla wszystkich ścieżek) | egzekwowanie dla ścieżki w bocie = D6 |
| ledgery: `evaluation`, `quant/ledger`, `mm` ledger, `decision/ledger`, `scalp`, `ml` (+3 pliki) | `ledgers/` (widok) | writery bez zmian |
| `docs/quant/INVENTORY.*`, `MAPA_MODELI`, `COMPONENT_INVENTORY` (tabele ręczne, 7 nieaktualnych) | generowane z `quant/ids.PRODUCERS` + `models check` | – |

## 6. Kolejność prac i co robię bez zgody

**Neutralne – robię od razu (Etap 3 i początek 4):**

1. Etap 3: weryfikacja każdego modelu, `models check [--smoke]`, tabela 3.6.
2. Naprawy błędów, które nie zmieniają decyzji, z testem, który przed poprawką nie przechodzi:
   - `registry_io` (utrata stanu rejestrów aktywacji, K);
   - Studio RUNNER_GROUP `KeyError 'quick'` (K, wszystkie 28 zadań grupowych runnera w Studio padają);
   - import Studio bez `reg_lock`;
   - nieaktualny `test_train_all` (19 → 20 zadań);
   - Kronos `forecast_id` przy ponownej prognozie;
   - brakujące id w rejestrze kanonicznym;
   - podwójny wiersz breakout w katalogu;
   - statusy SHADOW raportowane mocniej niż robi kod (hdc/ste/gpr).
3. Test architektury: brak cykli, każdy producent ma adapter i smoke, brak drugiego rejestru, `vendor/` bez zmian.

**Duże ruchy – po Twojej zgodzie na ten projekt (Etap 4), każdy osobnym commitem z replay = identyczny:**

1. Rejestr kanoniczny `PRODUCERS` + widoki (`sh/models`, `modelhub/catalog`, `mm/inventory`).
2. `features/` (słownik, schematy, fingerprint).
3. `ledgers/` (widok).
4. `costs/` w wersji neutralnej (polityki dzisiejsze) + flaga O7 domyślnie OFF.
5. DQ core.
6. Usługa blokad treningu + DatasetRef + `training/promotion.py` (krok 1).
7. Composition root w `runtime.py`.
8. Podział `api/app.py` na routery.
9. Zerwanie cyklu `analysis↔strategies`.
10. Sprzątanie: martwy kod potwierdzony testem (OTC ~460 linii, ~18 funkcji).

Endpointy bez wywołującego **nie są usuwane** (to kontrakt publiczny), tylko oznaczane w raporcie.

## 7. Decyzje do zatwierdzenia

Każda pozycja zmienia zachowanie handlowe, ryzyko danych albo środowisko, więc **nie wdrażam jej bez Twojej zgody**. „Flaga” = kod przygotowany,
domyślnie OFF, golden replay z flagą OFF identyczny.

| # | Sprawa | Dowód | Warianty | Wpływ | Rekomendacja |
|---|---|---|---|---|---|
| **D1** | `execution.start_mode = AUTO_LIVE` (domyślnie) nigdy nie jest stosowany – martwy warunek | `runtime.py:66-73,87`; `config.py:224-228,806-810`; `execution/modes.py:190-194` | (a) zostawić i opisać; (b) jawnie oznaczyć `start_mode` jako nieużywany (status + opis pola), bez zmiany wartości; (c) naprawić warunek | (c) = bot startuje w AUTO_LIVE i wiąże rachunek REAL – **łamie zasadę 1, nie zrobię tego** | (b) |
| **D2** | O7: SH liczy spread jako koszt mimo wejścia po Ask/Bid **oraz** sizing SH liczy prowizję dwa razy | `sh/setup.py:244-261`, `sh/risk.py:99-101,133`; na jednej geometrii net RR SH 0.8636 (NO_TRADE przy progu 0.9) vs ACTIVE 0.8035 vs scalp 1.0164 | (a) bez zmian; (b) flaga `costs.unified_v2`: spread poza kosztem w SH i prowizja raz w sizingu | więcej setupów SH przechodzi próg RR; większy wolumen SH przy tym samym ryzyku % | przygotować za flagą OFF; włączyć razem z O2 (jak w REFACTOR_PLAN) |
| **D3** | Wspólny sizing / wspólna semantyka `cost_price` w `SetupCandidate` | `decision/contracts`, `evaluation/service._sh`, etykiety ledgera Quant | (a) bez zmian; (b) flaga: jedna funkcja sizingu i `cost_price` = koszty poza ceną + `cost_includes_spread` | zmienia etykiety Quant i progi HOLD w ASSIST | flaga OFF, decyzja razem z D2 |
| **D4** | Quant ASSIST: kolumny reżimu są w treningu, a w inferencji ich brak | `rejestry_cech` W (fabryka kandydata SH: ledger vs koordynator) | (a) bez zmian; (b) jedna fabryka kandydata za flagą zgodności, OFF = dzisiejsze wejście koordynatora | zmienia wejście MetaModelu w ASSIST | wspólna fabryka z flagą OFF + test równości cech; włączenie = Twoja decyzja |
| **D5** | Rola ASSIST rodziny modeli przetrwa aktywację/rollback artefaktu bez APPROVED lub syntetycznego | `diag trening#1`; poprawka 1.46 cofnięta przy odbiorze | (a) bez zmian; (b) przy zmianie aktywnej wersji `use` spada do SHADOW, gdy artefakt nie przechodzi bramki | taki model może dziś wstrzymywać setupy SH | (b) |
| **D6** | Promocja championa ML w bocie pomija regułę „APPROX/syntetyczny nigdy championem” | `ml/service.py:366` vs `ml/offline.py` | (a) bez zmian; (b) jedna polityka promocji dla obu ścieżek | champion steruje bramką ML w ASSIST (domyślnie `ml.mode=SHADOW`) | (b); krok 1 (tylko log) robię neutralnie |
| **D7** | TEST_INSTALACJI „nigdy nie aktywuje”, a ML (`--no-approx`), Monte Carlo i master_models aktywują | `diag trening` W | (a) bez zmian; (b) jeden parametr `--no-activate` przekazywany każdemu krokowi | zmienia, które artefakty są aktywne po teście instalacji | (b) |
| **D8** | Ścieżka Quant traktuje stan Kalman `*_CANDIDATE` jako kierunek (poprawka 1.46 objęła tylko tablicę dowodów) | `quant/adapters.py:191`; `_dir_of('BULLISH_CANDIDATE') == 1` (sprawdzone poleceniem) | (a) bez zmian; (b) kandydat = brak kierunku | zmienia cechy MetaModelu (w ASSIST – HOLD) | (b) z retreningiem MetaModelu |
| **D9** | Nieaktualna relacja DXY (STALE) przechodzi do cech MetaModelu jako ważna | `quant/adapters.py:123-126`, `quant/features.py:108-111` (potwierdzone uruchomieniem) | (a) bez zmian; (b) STALE → brak cechy (maska) | zmienia cechy MetaModelu | (b) z retreningiem |
| **D10** | Trainhub: `htf_stale` odrzuca wiersze tylko w treningu, inferencja daje READY na zamrożonym HTF | `rejestry_cech` W | (a) bez zmian; (b) ten sam warunek w inferencji → DEGRADED | prognozy TH zasilają cechy `fc:*` Quant | (b) |
| **D11** | Adapter Quant dla Monte Carlo zawsze DISABLED (czyta klucze `last`/`result`, których `status()` nie ma) | `quant/adapters.py:148-150` (potwierdzone uruchomieniem) | (a) bez zmian; (b) naprawić odczyt | MC zaczyna zasilać Quant (nowe wejście) | (b), ale jako zmiana wejść – Twoja zgoda |
| **D12** | Aktywny TH_BASELINE zostaje „mówcą” grupy M5_DIRECTION | inwentarz trainhub (potwierdzone uruchomieniem) | (a) bez zmian; (b) baseline nie jest mówcą, gdy jest model z umiejętnością | zmienia głos grupy w SH | do decyzji |
| **D13** | Model agenta Claude: `claude-fable-5-2` (następca `claude-fable-5-1`, tańszy: $8/$40 vs $10/$50) nie ma w tabeli cen i liście fallback | `agent/service.py:30-45`, `config.py:159-162`; ID i ceny sprawdzone w aktualnej dokumentacji | (a) bez zmian; (b) dopisać do tabeli cen i fallback (domyślny model dalej wybierasz Ty) | żaden, dopóki go nie wybierzesz | (b) – dopisanie jest neutralne, zrobię je, jeśli nie zgłosisz sprzeciwu |
| **D14** | Retencja `quote_forecasts`/`quote_outcomes` (~51 tys. + 51 tys. wierszy/dobę w głównej bazie) | `ledgery` W | (a) bez zmian; (b) retencja (usuwa historię); (c) tylko jedna transakcja na migawkę (neutralne) | (b) usuwa dane | (c) teraz; (b) wyłącznie na Twoje polecenie |
| **D15** | Sieć dla wag Hugging Face / download.pytorch.org | proxy zwraca 403; Kronos oficjalne wagi, Chronos-2, Granite TTM, TiRex-2, TabICL = NIEZWERYFIKOWANE | (a) zostaje NIEZWERYFIKOWANE; (b) osobne środowisko chmurowe z dostępem do tych hostów | tylko weryfikacja | (b) – poproszę przez okno zatwierdzenia środowiska |
| **D16** | 25 poprawek 1.46 cofniętych przy odbiorze (zasada 1/2) i 161 pozycji „Do decyzji” z `docs/AUDYT_1_45.md` | `docs/AUDYT_1_45.md` §„Do decyzji właściciela” | – | – | bez zmian w tej przebudowie; lista zostaje w audycie |
| **D17** | Rekord Quant `rule:news` jest zawsze READY (także przy niewczytanym kalendarzu), a pola `blackout` / `next_event_in_s` są zawsze puste | `quant/adapters.py:96-102` czyta klucze, których `news/service.py:132-137` nie zwraca (smoke `rules`) | (a) bez zmian; (b) READY tylko przy wczytanym kalendarzu, blackout z `news.macro()` | zmienia publikację Quant; decyzja zmienia się tylko, gdy `rule:news` jest w `decision.required_models` | (b) |
| **D18** | Rekordy rodzin modeli gubią `data_kind` (`SYNTHETIC_TEST` → `None`), więc Quant nie odrzuca artefaktu syntetycznego w migawce REAL | `modelhub/families/service.py:435` vs `base.kind_class`; `quant/checks.py:65-66` (smoke `families`, 9 rodzin) | (a) bez zmian; (b) `kind_class(...)` | rodzina wytrenowana na syntetyce przestaje zasilać cechy Quant na rachunku REAL | (b) |
| **D19** | Ranking AUTO: bonus `rank_adjust` legacy ML w ASSIST wyniósł +46,5 pkt na danych testowych i może zdominować ranking | smoke `ml` (`ml/service.py` rank_adjust) | (a) bez zmian; (b) limit bonusu | tylko w `ml.mode=ASSIST` | do decyzji (informacja) |
| **D20** | Aktywacja prognoz złota / scalp przyjmuje run z oceną REJECTED (sprawdzana tylko jakość danych, nie wynik walidacji) | `gold_candles_runtime/common.py:158-173`, `scalp_infer.activatable` (smoke `scalp_gold`) | (a) bez zmian; (b) odmowa aktywacji REJECTED | prognozy są SHADOW – wpływ tylko przez cechy Quant | (b) |
| **D21** | Adapter prognoz złota publikuje READY dla horyzontów REJECTED i `BLOCKED_SESSION_BREAK`; scalp A i złoto oznaczone UNCALIBRATED mimo kalibratora | `modelhub/adapters.py:40-49`, `quant/adapters.py:352` | (a) bez zmian; (b) stany i kalibracja zgodnie z rejestrem | zmienia cechy Quant (`fc:*`) | (b) z retreningiem MetaModelu |
| **D23** | Model Markov3/MarkovDiff wytrenowany na danych testowych (TEST_ONLY) jest wczytywany do komórki SI (SI, NSS i model reakcji flow mają bramkę TEST_ONLY) | `lab/flow_context/cli.py`, `service.py` (smoke `lab`); od 1.46 arch komórka pokazuje `model_role`/`data_kind` | (a) bez zmian (oznaczenie już jest); (b) nie ładować TEST_ONLY | tylko panel; istniejący test `test_flow_context` oczekuje ładowania | **(b) – wdrożone w 1.46 arch:** komórka SI nie wczytuje Markov TEST_ONLY (`MODEL_TEST_ONLY_NOT_LOADED`), model TEST_ONLY nie zastępuje RESEARCH w `markov/latest.txt` |
| **D22** | Okno Event GRU: jednostki cięte co 16 zdarzeń od początku segmentu – ostatnia pełna jednostka spóźnia się 0–15 zdarzeń (540 s przy TTL 900 s, rekord okresowo STALE) | inwentarz `mm` (`mm/event_engine`) | (a) bez zmian; (b) cięcie od końca | zmienia wejście modelu – wymaga retreningu | do decyzji |

Decyzje O1–O8 z `REFACTOR_PLAN.md` zostają nienaruszone. Trzy implementacje wejścia po sweepie (S07/S12, odwrócenie SH, scalp SHADOW) zostają
do porównania w ledgerze (O6).
