"""Generates MAPA_MODELI_I_TRENINGU.md and MAPA_MODELI_I_TRENINGU.json from the CANONICAL registry.

1.46 (I0012): the list of components is no longer typed by hand - it is quant/inventory.build() (PMW-QUANT-INV-1: sh/models.REGISTRY,
modelhub families, trainhub/learn.MODELS, mm/inventory, lab/SI/flow registries, quant/ids.EXTRA_PRODUCERS; canonical ids and aliases
from quant/ids.py - the same source as docs/quant/INVENTORY.*). ELEMENTS below are only the DESCRIPTIVE overlay (task / data / label /
trainer texts) attached to the registry entry named by _canon(); TF and horizon come from the registry whenever it has them. A registry
entry without an overlay gets the registry's own fields; an overlay that names no registry entry is listed separately as OUTSIDE the
registry (never dropped silently, never invented). Schema mq-model-map-2 = mq-model-map-1 element keys + aliases / legacy_ids / category /
registry_source, plus `outside_registry`.

Status values describe the CODE state of this package (implemented / integrated / tested on synthetic data); none of them is a
statement about model quality on real data - that comes only from a training run's report (data/training/runs/<run>/report.html).

  python tools/model_map.py      (bot's Python environment; offline - a temporary data folder, no running bot, no artifact touched)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
BOTH = ["XAUUSD", "BTC"]
LAB_TASK = "potrójna bariera: TP 1.5×ATR przed SL 1.0×ATR w 12 świecach M5 (LBL-TB-1.0.0); SL i TP w tej samej świecy → SL (konserwatywnie)"
LAB_FE = "FS-1.0.0 (lab/features.py: zwroty, ATR, EMA gap, kinematyka, sesja; sekwencje 32×kanały dla sieci)"
LAB_COMMON = {"task": "klasyfikacja binarna LONG", "data_source": "eksport treningowy M5 (data/training/datasets/<INST>/<run>) albo bufor bota",
              "tf": "M5", "horizon": "12 świec (60 min)", "side": "LONG (tylko długie – nie oznaczać jako oba kierunki)", "features": LAB_FE,
              "label": LAB_TASK, "trainer": "masterquo/lab/protocol.py LabTrainer + training lab-offline (walk-forward 4 foldy, purge/embargo 12, holdout 20% raz)",
              "loader": "lab/protocol.py load_artifact → LabService._infer (bot), kontrola parity przy zapisie",
              "artifact": "data/lab/models/<INST>/<model_id>/model.pkl + manifest.json (+ ACTIVE.json: aktywny per rodzina, rollback)",
              "instruments": BOTH}

ELEMENTS = [
    {"id": "FORECAST_GOLD_CANDLES", "name": "Prognozy świec (gold_candles) – regresja logistyczna wieloklasowa + kalibracja + kwantyle GBR",
     "implementation": "backend/gold_candles/model.py, gold_candles_runtime/plan_train.py", "task": "rozkład kierunku zamknięcia DOWN/FLAT/UP (próg ±0.20×ATR) + kwantyle q10/q50/q90",
     "data_source": "eksport MT5 M5 + M30 dokładnego symbolu (czas serwera → UTC, zmierzony offset / NY_CLOSE)", "tf": "M5 (+ kontekst M30 dołączany od available_at)",
     "horizon": "1/3/6 świec M5 = 5/15/30 min", "side": "nie dotyczy (rozkład)", "features": "gold_candles/features.py (wzorce świec, ATR, pozycja w siatce grid_step z profilu instrumentu, kontekst M30)",
     "label": "klasa zmiany ceny zamknięcia po h świecach względem ATR", "trainer": "gold_candles_runtime.plan_train (.venv_candles; plan zamrożony, fit/kalibracja/holdout chronologicznie)",
     "loader": "gold_candles_runtime.worker → gold_candles.model.forecast (bot: ForecastService, proces per instrument)",
     "artifact": "XAUUSD: data/forecast/runs/<run>/forecast_model.json; BTC: data/instruments/BTC/forecast/runs/…; rejestr registry.json per instrument",
     "instruments": BOTH, "status": "ZAIMPLEMENTOWANE_I_ZINTEGROWANE (XAUUSD: grid 5.0; BTC: grid 500 – hipoteza badawcza); parity loadera; brak testu na realnym MT5 w tym środowisku"},
    {"id": "DOUBLE_RETEST_V2", "name": "Maszyna stanów Double Retest v2", "implementation": "masterquo/forecast/double_retest.py", "task": "reguła setupu (bez trenowania)",
     "data_source": "bary bota", "tf": "M5/M30", "horizon": "—", "side": "oba", "features": "—", "label": "—", "trainer": "brak (reguła)", "loader": "ForecastService",
     "artifact": "—", "instruments": BOTH, "status": "REGUŁA – nie jest modelem do trenowania"},
    {"id": "SCALP_A", "name": "Scalp A – kierunek 1/3/5 min (BASELINE, LR, HGB, MLP 64-32, kwantyle HGB)", "implementation": "gold_candles_runtime/scalp_train.py, scalp_features.py, scalp_infer.py",
     "task": "klasa DOWN/FLAT/UP po kosztach (tau = max(0.2×ATR, koszt))", "data_source": "eksport M1 (+M5…H1 dla kontekstu replayu)", "tf": "M1", "horizon": "1/3/5 min",
     "side": "oba (klasy)", "features": "SCALP-FEAT-1.0.0 (zwroty, ATR, świeca, BB, SAR, wolumen, spread, sesja)", "label": "zmiana ceny względem progu kosztowego",
     "trainer": "gold_candles_runtime.scalp_train --instrument (walk-forward 5 bloków, embargo, kalibracja, holdout)", "loader": "scalp_infer.ScalpModel przez worker (cmd scalp_forecast)",
     "artifact": "data/scalp/runs/<run> (XAUUSD) | data/instruments/BTC/scalp/runs/<run>; registry.json per instrument", "instruments": BOTH,
     "status": "ZAIMPLEMENTOWANE_I_ZINTEGROWANE; profil BTC = kopia reguł XAUUSD (wszystkie progi względne) jako hipoteza"},
    {"id": "SCALP_B", "name": "Scalp B – jakość setupu P(TP1 przed SL) (LR, HGB)", "implementation": "gold_candles_runtime/scalp_train.py train_setup_model",
     "task": "P(TP1 przed SL) cyklu Range→Sweep→Retest", "data_source": "cykle z replayu profilu scalp na eksporcie", "tf": "M1/M5", "horizon": "do 30 min (max_hold)",
     "side": "BUY i SELL (cecha kierunku)", "features": "cechy cyklu z replayu", "label": "tp1_before_sl", "trainer": "scalp_train (te same bloki czasowe)",
     "loader": "scalp_infer.SetupModel (worker setup_quality)", "artifact": "jak Scalp A", "instruments": BOTH, "status": "ZAIMPLEMENTOWANE; zwykle BRAK_PRZESLANEK przy małej liczbie cykli"},
    {"id": "SCALP_C", "name": "Scalp C – ocena polityki HEDGE_PARTIAL vs REDUCE", "implementation": "masterquo/scalp/replay.py, report.hedge_summary",
     "task": "porównanie polityk w replayu OHLC (bez ticków) – NIE jest siecią ani klasyfikatorem", "data_source": "replay eksportu M1", "tf": "M1", "horizon": "cykl",
     "side": "oba", "features": "—", "label": "wynik R polityk", "trainer": "brak (ewaluacja polityki)", "loader": "—", "artifact": "raport runu scalp", "instruments": BOTH,
     "status": "EWALUACJA_POLITYKI – hedge pozostaje SHADOW/REDUCE"},
    # 1.46 arch (I0336): the scalp ML model was missing from the map (owner ml/scalp_task.py, inference ml/service.py)
    {"id": "ML_SCALP_NET_R", "name": "Scalp ML – XGBoost P(net_R > 0) + E[net_R] cyklu scalp (SCALP_NET_PROFIT_MARKET_V1, rodzina SCALP_MARKET)",
     "implementation": "masterquo/ml/scalp_task.py (zbiór, trening, selekcja, paczka), ml/service.py on_scalp_candidate (inferencja), scalp/service.py (wywołanie per kandydat)",
     "task": "klasyfikator P(net_R pełnego cyklu > 0) + regresor E[net_R], osobno per (instrument, profile_hash, strona)",
     "data_source": "kandydaci ScalpMachine z replayu eksportu (profil instrumentu, wejście MARKET z wykonalnym fill)", "tf": "M1 (wyzwalacz scalp; kontekst profilu)",
     "horizon": "pełny cykl scalp (TP1/TP2, BE, wyjście czasowe – scalp/replay.py)", "side": "BUY i SELL – osobne modele",
     "features": "SCALP-NET-FEAT-1.0.0 (scalp/strategy.py NET_FEATURES; brak = NaN, bez 0.0 za brak)",
     "label": "y = 1 gdy net_R > 0 po kosztach (Bid/Ask, prowizja, poślizg); net_R – regresja",
     "trainer": "ml/scalp_task.py (XGBoost CPU hist, 4 foldy walk-forward FIT/TUNE/CALIBRATION/POLICY, Platt, polityka p_min × ev_min, holdout 20% raz)",
     "loader": "ml/scalp_task.selected_bundle → MLService.on_scalp_candidate (predykcja zapisana przed publikacją)",
     "artifact": "data/ml_scalp/<INST>/runs/<run> (fixture_runs dla danych syntetycznych) + registry.json; role OBSERVE / SHADOW_GATE", "instruments": BOTH,
     "status": "ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVE / SHADOW_GATE – polityka hipotetyczna wyświetlana w panelu, nie wysyła zleceń)"},
    {"id": "SCALP_PROFILE", "name": "Profil scalp Range→Sweep→Retest (automat stanów)", "implementation": "masterquo/scalp/strategy.py + config/scalp_profile_v1.json / scalp_profile_BTC_v1.json",
     "task": "reguła", "data_source": "bary bota", "tf": "H1/M30/M15 kontekst, M5 zakres, M1 wyzwalacz", "horizon": "—", "side": "oba", "features": "—", "label": "—",
     "trainer": "brak", "loader": "ScalpService (profil per aktywne aktywo)", "artifact": "—", "instruments": BOTH, "status": "REGUŁA"},
    {"id": "LEGACY_ML_DT", "name": "Legacy ML – Decision Tree", "implementation": "masterquo/ml/{features,labels,models,trainer,registry,service,router,offline}.py",
     "task": "P(setup S01–S12 osiąga cel netto przed SL) dla potwierdzonej wersji setupu", "data_source": "setupy silnika na żywo (HIGH) + backfill z eksportu (APPROX, tylko gdy zadanie o to prosi)",
     "tf": "TF setupu", "horizon": "do wyjścia setupu", "side": "oba (cecha kierunku)", "features": "MQ-FEAT-1.3.0 (ml/features.py; 1.0.0 + cechy stref PMW-ZONE-FEAT-1, semantyka stref SEM-2; modele <= 1.2.0 dostają blok SEM-1)", "label": "MQ-LABEL-1.1.0 (koszty: spread+poślizg+prowizja)",
     "trainer": "ml/trainer.py (bloki fit/tune/calibrate/test, embargo 120 min); offline: training ml-offline", "loader": "ml/registry.py Bundle → MLService.predict (bot, baza aktywnego instrumentu)",
     "artifact": "XAUUSD: data/ml/models + masterquo.sqlite; BTC: data/instruments/BTC/ml/{models,ml.sqlite}", "instruments": BOTH,
     "status": "ZINTEGROWANE per instrument; model z próbek APPROX = RESEARCH_APPROX (nigdy champion automatycznie)"},
    {"id": "LEGACY_ML_XGB", "name": "Legacy ML – XGBoost (CPU)", "implementation": "jak LEGACY_ML_DT", "task": "jak LEGACY_ML_DT", "data_source": "jak LEGACY_ML_DT", "tf": "TF setupu",
     "horizon": "do wyjścia setupu", "side": "oba", "features": "MQ-FEAT-1.3.0", "label": "MQ-LABEL-1.1.0", "trainer": "ml/trainer.py", "loader": "ml/registry.py",
     "artifact": "jak LEGACY_ML_DT", "instruments": BOTH, "status": "jak LEGACY_ML_DT"},
]
for fam, name, st in (("DUMMY", "Lab DUMMY – częstość bazowa", "MODEL_KONTROLNY (nie zapisywany jako artefakt)"),
                      ("RULE", "Lab RULE – reguła odniesienia", "MODEL_KONTROLNY"),
                      ("LOGREG", "Lab regresja logistyczna", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("TREE", "Lab drzewo decyzyjne (≠ legacy Decision Tree: inne pytanie – bariera LONG M5, nie setup S01–S12)", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("MINIROCKET", "Lab MiniRocket (numpy) + klasyfikator liniowy", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("XGB", "Lab XGBoost (CPU)", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("RESNET1D", "Lab ResNet1D (numpy)", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("SEW_SNN", "Lab SEW-SNN (sieć impulsowa, numpy)", "ZAIMPLEMENTOWANE_I_ZINTEGROWANE"),
                      ("LOGREG_PCA", "Eksperyment: LOGREG na PCA", "EKSPERYMENT"),
                      ("LOGREG_GMM_AUG", "Eksperyment: LOGREG z cechami reżimu GMM", "EKSPERYMENT"),
                      ("LOGREG_NEUTRALIZED", "Eksperyment: LOGREG z neutralizacją czynników", "EKSPERYMENT")):
    ELEMENTS.append({"id": f"LAB_{fam}", "name": name, "implementation": f"masterquo/lab/protocol.py fit_family('{fam}'), lab/nets.py, lab/minirocket.py",
                     **LAB_COMMON, "status": st + "; zapisywany jest model oceniany (fit na danych rozwojowych), bez refitu na train+holdout"})
ELEMENTS += [
    {"id": "MONTE_CARLO_PATHS", "name": "Monte Carlo ścieżek cen (PMW-MC-1) – P(TP przed SL w horyzoncie)",
     "implementation": "masterquo/montecarlo/engine.py, validate.py, service.py",
     "task": "prawdopodobieństwo, że cena dojdzie do TP przed SL w H świecach M1 (każdy poziom osobno) + zasięg ruchu ±X; świeca z TP i SL = przedział ostrożny–optymistyczny",
     "data_source": "zamknięte świece M1 bota (na żywo) / eksport MT5 M1 (+ opcjonalne ticki Bid/Ask rozstrzygające kolejność w świecy) – walidacja",
     "tf": "M1", "horizon": "H świec M1 (domyślnie 60; scenariusz SCALPING 30)", "side": "BUY i SELL – strona Bid/Ask, spread ze świecy",
     "features": "brak cech uczonych: losowanie całych świec (OHLC względem otwarcia) – IID / blokowe / warunkowane reżimem ATR i godziną sesji, skalowane do bieżącego ATR",
     "label": "rzeczywiste TP przed SL w H świecach (walidacja; ticki, gdy są) – dane wyłącznie sprzed chwili oceny",
     "trainer": "`python -m masterquo montecarlo validate` / 31_MONTE_CARLO_WALIDACJA.bat / zadanie runnera monte_carlo: walk-forward CAL/TEST z embargo H, model bazowy = klimatologia, Brier / log loss / kalibracja, CI bootstrap, kalibrator izotoniczny",
     "loader": "MonteCarloService (własny wątek; bufor zamkniętych świec bota) → /api/v1/montecarlo/*, /api/v1/sh/scenario",
     "artifact": "data/montecarlo/<INST>/registry.json + runs/<run>/report.json (aktywny kalibrator tylko z REAL_USER_DATA z przewagą; rollback: montecarlo rollback)",
     "instruments": BOTH,
     "status": "ZAIMPLEMENTOWANE_I_ZINTEGROWANE; bez kalibracji = prawdopodobieństwo w modelu (tak opisane w panelu); walidacja tylko na danych syntetycznych w tym środowisku (werdykt TEST_TECHNICZNY)"},
    {"id": "LAB_MARKOV", "name": "Macierz Markowa 3 stanów (moduł estymowany)", "implementation": "masterquo/lab/market.py markov()", "task": "rozkład stanu następnej świecy",
     "data_source": "bary bota", "tf": "M5", "horizon": "1 świeca", "side": "nie dotyczy", "features": "zwrot close-to-close", "label": "stan DOWN/FLAT/UP",
     "trainer": "estymacja w oknie 500 świec kończącym się na ostatniej zamkniętej (wygładzanie Laplace'a) – bez osobnego treningu",
     "loader": "LabService (na żywo)", "artifact": "—", "instruments": BOTH, "status": "ESTYMOWANY_ONLINE; walidacja: archiwum prognoz punkt-w-czasie (Dane i diagnostyka)"},
    {"id": "LAB_ACD", "name": "ACD(1,1) aktywności ticków (moduł estymowany)", "implementation": "masterquo/lab/ticks.py fit_acd()", "task": "oczekiwany czas do kolejnego ticka",
     "data_source": "ticki copy_ticks_from", "tf": "tick", "horizon": "następne zdarzenie", "side": "nie dotyczy", "features": "czasy między tickami skorygowane dobowo",
     "label": "—", "trainer": "QMLE wykładnicze, ograniczenia a+b<1 z konstrukcji – estymacja online", "loader": "LabService", "artifact": "—", "instruments": BOTH,
     "status": "ESTYMOWANY_ONLINE; minimum 300 zdarzeń, inaczej warming_up"},
    {"id": "INDICATORS_FFT_VMD_EMD", "name": "Wskaźniki, FFT/VMD/EMD, BB/MA, Double Bottom", "implementation": "masterquo/analytics/*, indicators/series.py",
     "task": "obliczenia – nie są sieciami i nie mają przycisku „trenuj”", "data_source": "bary bota", "tf": "różne", "horizon": "—", "side": "—", "features": "—",
     "label": "—", "trainer": "brak", "loader": "AnalyticsService", "artifact": "—", "instruments": BOTH, "status": "OBLICZENIA"},
    {"id": "MARKET_ZONES_MZ1", "name": "Strefy rynkowe M1/M5/M15/M30 (PMW-MZ-1) – S/R, popyt/podaż, FVG, order blocks, EQH/EQL, konfluencja",
     "implementation": "masterquo/zones/market.py, zones/market_service.py (panel Wykresy → Strefy rynkowe)",
     "task": "detekcja stref z jawnymi regułami potwierdzenia, testów i unieważnienia – nie jest modelem do trenowania",
     "data_source": "zamknięte świece M1/M5/M15/M30 dokładnego symbolu przez bridge (XAUUSD-, BTCUSDT-)", "tf": "M1, M5, M15, M30", "horizon": "—",
     "side": "kierunek strefy (wzrostowa / spadkowa / neutralna)", "features": "—", "label": "—", "trainer": "brak (reguły; parametry skalowane ATR i profilem instrumentu)",
     "loader": "MarketZonesService (zadania na przycisk / aktualizacja po zamknięciu świecy)", "artifact": "data/zones/market_zones.sqlite (historia stref i zdarzeń)",
     "instruments": BOTH, "status": "REGUŁY – zaimplementowane i zintegrowane; jakość 0–100 nie jest prawdopodobieństwem; EQH/EQL = płynność wnioskowana z OHLC"},
]
def _trainhub_overlay() -> list[dict]:
    """1.46 (I0666, I0658): one element per trainhub/learn.MODELS entry (was a hand list of 4 - TH_RF and TH_SVM were missing). The trainer
    text tells which call trains the model: without --models / --profile the CLI trains only pipeline.DEFAULTS['models']."""
    from masterquo.trainhub import learn as TL
    from masterquo.trainhub import pipeline as TP
    default = list(TP.DEFAULTS["models"])
    notes = {"TH_XGB": "tylko gdy pakiet xgboost jest zainstalowany",
             "TH_RF": "permutation importance liczone na HOLDOUT (raport), class_weight balanced_subsample",
             "TH_SVM": f"jądro RBF tylko do {TL.RBF_MAX_ROWS} wierszy, powyżej liniowe"}
    out = []
    for mid, m in TL.MODELS.items():
        prof = [k for k, v in TP.PROFILES.items() if mid in v.get("models", ())]
        alt = f" albo `--profile {'|'.join(prof)}`" if prof else ""
        if mid in default:
            how = f"`python -m masterquo trainhub train|full --instrument XAUUSD|BTC` (domyślny zestaw bez --models: {', '.join(default)}){alt}"
        else:
            how = (f"`python -m masterquo trainhub train|full --instrument XAUUSD|BTC --models {mid}`{alt}"
                   f" – NIE w domyślnym zestawie bez --models ({', '.join(default)})")
        out.append({
            "id": mid, "name": f"Centrum treningu – {m.get('name') or mid}: kierunek ruchu po kosztach" + (f" ({notes[mid]})" if mid in notes else ""),
            "implementation": "masterquo/trainhub/learn.py, features.py (wspólne cechy trening/inferencja), dataset.py, registry.py, inference.py",
            "task": "klasa DOWN/FLAT/UP zmiany zamknięcia po H świecach względem progu max(k×ATR14, koszt świecy)",
            "data_source": "magazyn świec data/marketdata/<INST> (eksport MT5 przyrostowy/historyczny, Parquet + CSV + manifest z sumami)",
            "tf": "bazowy M1/M5/M15/M30 + wyższe TF dołączane od zamknięcia świecy",
            "horizon": f"H świec (domyślnie {TP.DEFAULTS['horizon']} × {TP.DEFAULTS['base_tf']})", "side": "oba (klasy)",
            "features": "PMW-TH-FEAT-1 (zwroty, ATR, świeca, zmienność, RSI, EMA, z-score, aktywność ticków, spread, czas, cechy wyższych TF)",
            "label": "PMW-TH-LABEL-1 (koszty: spread ze świecy + prowizja z historii transakcji albo założenie + poślizg-założenie); okna przez lukę sesji odrzucone",
            "trainer": f"Centrum treningu / {how} (purged walk-forward + embargo, nietknięty holdout 20%, kalibracja temperaturą na dev, proces osobny)",
            "loader": "TrainhubInference (tylko AKTYWNA paczka po teście zgodności i predykcji; inaczej stan INCOMPATIBLE/ERROR bez wartości)",
            "artifact": "data/trainhub/models/<INST>/<MODEL>_<TF>_H<h>/<wersja>/ (model.joblib, cechy, config, metryki, manifest danych, zależności, REPRODUCE.md, sha256)",
            "instruments": BOTH,
            "status": "ZAIMPLEMENTOWANE_I_ZINTEGROWANE (OBSERVATION – nie głosuje w strategiach); trening sprawdzony tylko na symulatorze (SYNTHETIC_TEST) – brak oceny na danych rzeczywistych"})
    return out


ELEMENTS += _trainhub_overlay()
ELEMENTS += [
    {"id": "STRATEGIES_S01_S12", "name": "Strategie S01–S12", "implementation": "masterquo/strategies/*", "task": "reguły setupów (strumień dla legacy ML)",
     "data_source": "bary bota / backfill z eksportu z symbolem instrumentu", "tf": "M5–D1", "horizon": "—", "side": "oba", "features": "—", "label": "—",
     "trainer": "brak", "loader": "ActiveEngine", "artifact": "—", "instruments": BOTH, "status": "REGUŁY"},
]


# 1.46 (I0012): overlay id -> canonical id (quant/ids). LAB_<FAM> -> lab:<FAM> and TH_* -> trainhub:TH_* are derived in _canon(); an id that
# resolves to no registry entry stays OUTSIDE the registry (listed, flagged). LEGACY_ML_DT / _XGB are two algorithms of ONE registry entry.
CANON = {"FORECAST_GOLD_CANDLES": "forecast:gold_candles", "DOUBLE_RETEST_V2": "forecast:double_retest_v2", "SCALP_A": "scalp:A_direction",
         "SCALP_B": "scalp:B_setup_quality", "SCALP_C": "scalp:C_policy", "LEGACY_ML_DT": "ml:legacy_s01_s12", "LEGACY_ML_XGB": "ml:legacy_s01_s12",
         "MONTE_CARLO_PATHS": "analysis:montecarlo", "MARKET_ZONES_MZ1": "analysis:market_zones", "INDICATORS_FFT_VMD_EMD": "rule:decomposition",
         "ML_SCALP_NET_R": "ml_scalp:xgb_net_r"}
FIELDS = ("implementation", "task", "data_source", "tf", "horizon", "side", "features", "label", "trainer", "loader", "artifact", "instruments", "status")
SCHEMA = "mq-model-map-2"


def _canon(eid: str) -> str:
    if eid in CANON:
        return CANON[eid]
    if eid.startswith("LAB_"):
        return "lab:" + eid[4:]
    if eid.startswith("TH_"):
        return "trainhub:" + eid
    return eid


def _registry_element(e: dict) -> dict:
    task = " / ".join(str(x) for x in (e.get("task_type"), e.get("task"), e.get("unit")) if x)
    st = f"kod: {e['code_state']}; walidacja: {e['validation']}; rola w Quant Core: {e['quant_role']}"
    why = e.get("not_applicable_reason") or e.get("notes")
    return {"id": e["id"], "name": e["name"], "implementation": ", ".join(e.get("files") or []) or "—", "task": task or "—",
            "data_source": e.get("data_required") or "—", "tf": ", ".join(e.get("timeframes") or []) or "—", "horizon": e.get("horizon") or "—",
            "side": "—", "features": e.get("features") or "—", "label": "—", "trainer": e.get("owner_train") or "—",
            "loader": e.get("owner_infer") or "—", "artifact": e.get("artifact") or "—", "instruments": [],
            "status": st + (f" ({why})" if why else ""), "aliases": list(e.get("aliases") or []), "legacy_ids": [],
            "category": e.get("category"), "registry_source": list(e.get("source_registry") or [])}


def build(inv: dict | None = None) -> dict:
    """The map: one element per non-group entry of quant/inventory.build() (registry order) with the overlay merged in."""
    if inv is None:
        from masterquo.quant import inventory as QI
        inv = QI.build()
    entries = [e for e in inv["entries"] if e.get("category") != "GROUP"]
    ids = {e["id"] for e in entries}
    over: dict[str, list[dict]] = {}
    outside = []
    for o in ELEMENTS:
        cid = _canon(o["id"])
        if cid in ids:
            over.setdefault(cid, []).append(o)
        else:
            outside.append({**o, "category": "POZA_REJESTREM", "registry_source": [],
                            "reason": "brak w rejestrze kanonicznym (quant/ids, quant/inventory) – opis zachowany, nie jest pozycją rejestru"})
    elements = []
    for e in entries:
        el = _registry_element(e)
        mine = over.get(e["id"]) or []
        if mine:
            o = mine[0]
            for k in FIELDS:
                if k in ("tf", "horizon") and el[k] != "—":
                    continue                                   # TF / horizon: the registry wins whenever it has them
                if k == "status":
                    el[k] = f"{el[k]} | opis: {o[k]}" if o.get(k) else el[k]
                elif o.get(k):
                    el[k] = o[k]
            el["name"] = " / ".join(x["name"] for x in mine)
            el["legacy_ids"] = [x["id"] for x in mine]
        elements.append(el)
    return {"schema": SCHEMA, "source": f"quant/inventory.build() ({inv.get('version')}) + opisy tools/model_map.ELEMENTS",
            "elements": elements, "outside_registry": outside}


def to_markdown(m: dict) -> str:
    pl = {"implementation": "Implementacja", "task": "Zadanie", "data_source": "Źródło danych", "tf": "TF", "horizon": "Horyzont", "side": "Strona",
          "features": "Cechy", "label": "Etykieta", "trainer": "Trainer", "loader": "Loader", "artifact": "Artefakt", "instruments": "Instrumenty", "status": "Status"}

    def val(v):
        return (", ".join(v) if isinstance(v, list) else str(v)) or "—"

    out = ["# Mapa modeli i treningu (XAUUSD / BTC)", "",
           ("Wygenerowano przez `tools/model_map.py` (to samo źródło co `MAPA_MODELI_I_TRENINGU.json`) z rejestru kanonicznego "
            "`quant/inventory.build()` – te same identyfikatory i aliasy co `docs/quant/INVENTORY.md` (`backend/masterquo/quant/ids.py`). "
            "TF i horyzont pochodzą z rejestru; teksty opisowe (zadanie, dane, etykieta, trainer) z `tools/model_map.ELEMENTS`."),
           "Status opisuje stan KODU w tej paczce. Nie mówi nic o jakości modelu na Twoich danych – tę pokazuje dopiero raport runu treningu.",
           "Jednostka modelu: instrument × zadanie × TF × horyzont × strona. Każdy instrument ma osobne dane, skalery, kalibratory, modele i rejestry.", ""]
    for e in m["elements"]:
        out += [f"## {e['id']} – {e['name']}", ""]
        if e["aliases"] or e["legacy_ids"]:
            out.append(f"- **Aliasy:** {val(e['aliases'] + [x for x in e['legacy_ids'] if x not in e['aliases']])}")
        out.append(f"- **Kategoria:** {e['category']} (rejestr: {val(e['registry_source'])})")
        out += [f"- **{pl[k]}:** {val(e[k])}" for k in FIELDS]
        out.append("")
    if m["outside_registry"]:
        out += ["# Poza rejestrem kanonicznym", "",
                "Opisy, których identyfikator nie odpowiada żadnej pozycji `quant/inventory` – zachowane jako opis, nie są pozycją rejestru.", ""]
        for e in m["outside_registry"]:
            out += [f"## {e['id']} – {e['name']}", "", f"- **Uwaga:** {e['reason']}"]
            out += [f"- **{pl[k]}:** {val(e.get(k, '—'))}" for k in FIELDS]
            out.append("")
    return "\n".join(out)


def main() -> None:
    os.environ.setdefault("MASTERQUO_DATA_DIR", tempfile.mkdtemp(prefix="pmw_map_"))   # offline: no probe of the user's data folder
    m = build()
    (ROOT / "MAPA_MODELI_I_TRENINGU.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "MAPA_MODELI_I_TRENINGU.md").write_text(to_markdown(m), encoding="utf-8")


if __name__ == "__main__":
    main()
