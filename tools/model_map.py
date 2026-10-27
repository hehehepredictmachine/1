"""Generates MAPA_MODELI_I_TRENINGU.md and MAPA_MODELI_I_TRENINGU.json (one source of truth: ELEMENTS below).

Status values describe the CODE state of this package (implemented / integrated / tested on synthetic data); none of them is a
statement about model quality on real data - that comes only from a training run's report (data/training/runs/<run>/report.html).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    {"id": "SCALP_PROFILE", "name": "Profil scalp Range→Sweep→Retest (automat stanów)", "implementation": "masterquo/scalp/strategy.py + config/scalp_profile_v1.json / scalp_profile_BTC_v1.json",
     "task": "reguła", "data_source": "bary bota", "tf": "H1/M30/M15 kontekst, M5 zakres, M1 wyzwalacz", "horizon": "—", "side": "oba", "features": "—", "label": "—",
     "trainer": "brak", "loader": "ScalpService (profil per aktywne aktywo)", "artifact": "—", "instruments": BOTH, "status": "REGUŁA"},
    {"id": "LEGACY_ML_DT", "name": "Legacy ML – Decision Tree", "implementation": "masterquo/ml/{features,labels,models,trainer,registry,service,router,offline}.py",
     "task": "P(setup S01–S12 osiąga cel netto przed SL) dla potwierdzonej wersji setupu", "data_source": "setupy silnika na żywo (HIGH) + backfill z eksportu (APPROX, tylko gdy zadanie o to prosi)",
     "tf": "TF setupu", "horizon": "do wyjścia setupu", "side": "oba (cecha kierunku)", "features": "MQ-FEAT-1.1.0 (ml/features.py; 1.0.0 + cechy stref PMW-ZONE-FEAT-1)", "label": "MQ-LABEL-1.1.0 (koszty: spread+poślizg+prowizja)",
     "trainer": "ml/trainer.py (bloki fit/tune/calibrate/test, embargo 120 min); offline: training ml-offline", "loader": "ml/registry.py Bundle → MLService.predict (bot, baza aktywnego instrumentu)",
     "artifact": "XAUUSD: data/ml/models + masterquo.sqlite; BTC: data/instruments/BTC/ml/{models,ml.sqlite}", "instruments": BOTH,
     "status": "ZINTEGROWANE per instrument; model z próbek APPROX = RESEARCH_APPROX (nigdy champion automatycznie)"},
    {"id": "LEGACY_ML_XGB", "name": "Legacy ML – XGBoost (CPU)", "implementation": "jak LEGACY_ML_DT", "task": "jak LEGACY_ML_DT", "data_source": "jak LEGACY_ML_DT", "tf": "TF setupu",
     "horizon": "do wyjścia setupu", "side": "oba", "features": "MQ-FEAT-1.1.0", "label": "MQ-LABEL-1.1.0", "trainer": "ml/trainer.py", "loader": "ml/registry.py",
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
    {"id": "INDICATORS_FFT_VMD_EMD", "name": "Wskaźniki, FFT/VMD/EMD, BB/MA, Double Bottom", "implementation": "masterquo/analytics/*, strategies/indicators.py",
     "task": "obliczenia – nie są sieciami i nie mają przycisku „trenuj”", "data_source": "bary bota", "tf": "różne", "horizon": "—", "side": "—", "features": "—",
     "label": "—", "trainer": "brak", "loader": "AnalyticsService", "artifact": "—", "instruments": BOTH, "status": "OBLICZENIA"},
    {"id": "STRATEGIES_S01_S12", "name": "Strategie S01–S12", "implementation": "masterquo/strategies/*", "task": "reguły setupów (strumień dla legacy ML)",
     "data_source": "bary bota / backfill z eksportu z symbolem instrumentu", "tf": "M5–D1", "horizon": "—", "side": "oba", "features": "—", "label": "—",
     "trainer": "brak", "loader": "ActiveEngine", "artifact": "—", "instruments": BOTH, "status": "REGUŁY"},
]


def main() -> None:
    (ROOT / "MAPA_MODELI_I_TRENINGU.json").write_text(json.dumps({"schema": "mq-model-map-1", "elements": ELEMENTS}, indent=1, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
    keys = ("implementation", "task", "data_source", "tf", "horizon", "side", "features", "label", "trainer", "loader", "artifact", "instruments", "status")
    pl = {"implementation": "Implementacja", "task": "Zadanie", "data_source": "Źródło danych", "tf": "TF", "horizon": "Horyzont", "side": "Strona",
          "features": "Cechy", "label": "Etykieta", "trainer": "Trainer", "loader": "Loader", "artifact": "Artefakt", "instruments": "Instrumenty", "status": "Status"}
    out = ["# Mapa modeli i treningu (XAUUSD / BTC)", "",
           "Wygenerowano przez `tools/model_map.py` (to samo źródło co `MAPA_MODELI_I_TRENINGU.json`).",
           "Status opisuje stan KODU w tej paczce. Nie mówi nic o jakości modelu na Twoich danych – tę pokazuje dopiero raport runu treningu.",
           "Jednostka modelu: instrument × zadanie × TF × horyzont × strona. Każdy instrument ma osobne dane, skalery, kalibratory, modele i rejestry.", ""]
    for e in ELEMENTS:
        out += [f"## {e['id']} – {e['name']}", ""]
        out += [f"- **{pl[k]}:** {', '.join(e[k]) if isinstance(e[k], list) else e[k]}" for k in keys]
        out.append("")
    (ROOT / "MAPA_MODELI_I_TRENINGU.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
