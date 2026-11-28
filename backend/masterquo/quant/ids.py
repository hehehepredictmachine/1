"""Canonical model identities of PMW Quant Core (PMW-QUANT-IDS-1).

One computational producer (code + artifact owner) = ONE canonical id `<owner>:<name>`. Every other name under which the same producer
appears in the bot (a family adapter, an SH registry row, an MM artifact id, a panel model_key) is an ALIAS of it. Aliases never add
a second vote, a second training job or a second row in the operational count.

Resolution order for a prediction record (PMW-PRED-1/2): `canonical_id` (already set) -> `family` -> `model_key` -> `model_id` ->
`model_name`. A record that cannot be resolved gets `unresolved:<name>` - never the ambiguous `?`.

Known alias groups found in the 1.33/1.34 code (docs/quant/INVENTORY.md lists all of them):
* families TH_RF / TH_XGB / TH_SVM are adapters of the Training Center models trainhub TH_RF / TH_XGB / TH_SVM (FamilyService.predict
  returns None for them; the trainhub inference produces the prediction) -> canonical `trainhub:TH_*`;
* family SEQ_GRU_EVENT, SH row mm_event_engine and MM artifact event_engine_dir3 are ONE model -> `mm:event_engine_dir3`;
* SH row gold_forecast and the panel keys gold_candles_5m/15m/30m are one model with three horizons -> `forecast:gold_candles`;
* SH row kronos and model_name Kronos-small -> `kronos:Kronos-small` (1.42.8; historical Kronos-base rows 1.37-1.42.7 -> `kronos:Kronos-base`);
* SH rows chronos2 / granite_ttm and model_name Chronos-2 / Granite TTM -> `tsfm:chronos2` / `tsfm:granite_ttm` (1.37, 1.40);
  `tsfm:fincast` stays as a HISTORY id (FinCast retired in 1.40 - old records keep it, it is never given to Granite TTM);
* SH row th_direction is a GROUP (all active trainhub packages), SH rows lab / si_move are GROUPS of several families.

1.46 arch Etap 4: PRODUCERS (end of the module) = every producer id of the bot with the table declaring it. sh/models.REGISTRY,
modelhub/catalog, mm/inventory, quant/inventory and tools/model_map are VIEWS: they describe producers and derive canonical ids here
(sh_row_id, mm_module_id, CATALOG_ROWS) - none of them declares an id of its own.
"""
from __future__ import annotations

import re

VERSION = "PMW-QUANT-IDS-1"

# canonical id -> aliases (names used elsewhere in the bot for the SAME producer)
ALIASES: dict[str, tuple[str, ...]] = {
    "trainhub:TH_BASELINE": ("TH_BASELINE",),
    "trainhub:TH_LOGREG": ("TH_LOGREG",),
    "trainhub:TH_HGB": ("TH_HGB",),
    "trainhub:TH_XGB": ("TH_XGB", "family:TH_XGB"),
    "trainhub:TH_RF": ("TH_RF", "family:TH_RF"),
    "trainhub:TH_SVM": ("TH_SVM", "family:TH_SVM"),
    "mm:event_engine_dir3": ("SEQ_GRU_EVENT", "family:SEQ_GRU_EVENT", "mm_event_engine", "event_engine_dir3", "event_engine"),
    "mm:gpr_logret": ("mm_gpr", "gpr", "gpr_logret", "gpr_logret:LIVE"),
    "mm:hdc_dir3": ("mm_hdc", "hdc", "hdc_dir3"),
    "mm:ste_flownet_ret": ("mm_ste_flownet", "ste_flownet", "ste_flownet_ret"),
    "mm:kalman_cross": ("mm_kalman", "kalman"),
    "mm:breakout_zones": ("mm_breakout", "breakout_zones"),
    "mm:align_mean": ("mm_align_mean", "align_mean"),
    "mm:multi_indicator": ("mm_multi_indicator", "multi_indicator"),
    "mm:smc_fvg": ("mm_smc_fvg", "smc_fvg"),
    "forecast:gold_candles": ("gold_forecast", "gold_candles", "gold_candles_5m", "gold_candles_15m", "gold_candles_30m"),
    "kronos:Kronos-small": ("kronos", "Kronos-small", "KRONOS_SMALL"),    # 1.42.8: current checkpoint again (also until 1.36.0)
    "kronos:Kronos-base": ("Kronos-base", "KRONOS_BASE"),            # history only (used 1.37-1.42.7)
    "tsfm:chronos2": ("chronos2", "Chronos-2", "CHRONOS2"),
    "tsfm:granite_ttm": ("granite_ttm", "Granite TTM", "GRANITE_TTM"),
    "tsfm:fincast": ("fincast", "FinCast", "FINCAST"),               # history only (1.37-1.39, retired in 1.40)
    # 1.46 arch: TiRex-2 (1.41) was missing; its records carry model_id 'tsfm:tirex2', which resolve() already returned through the
    # 'tsfm:' prefix - the aliases below therefore change no existing resolution (tests/test_models_check.py pins it)
    "tsfm:tirex2": ("tirex2", "TiRex-2", "TIREX2"),
    "sh:tp_model": ("sh_tp_model",),
    "scalp:A_direction": ("scalp_A",),
    "scalp:B_setup_quality": ("scalp_B",),
    "ml:legacy_s01_s12": ("legacy_ml",),
    "extind:indicator_context": ("indicator_context",),
    "ml_scalp:xgb_net_r": ("ml_scalp",),
    "nss:tcn": ("nss",),
    "flow:reaction_m1": ("flow_reaction",),
    "context_ind:context_move_m5": ("context_move", "CONTEXT_MOVE_M5_V1"),
    "agent:claude": ("agent",),
}
# rows that name a GROUP of producers (never a producer themselves). Written out here (this module stays import-free: the decision path
# imports it) and pinned to the source lists by tests/test_arch146_w2_quant_inventory.py: th_direction = trainhub/learn.MODELS,
# lab = lab/protocol.FAMILIES + EXPERIMENTS (1.46 arch I0270: the experiments are saved in the ALL mode of `training lab-offline`, run by
# LabService and published by quant.adapters.lab like the families), si_move = lab/structure_nets.FAMILIES + lab/si_families.FAMILIES.
# GROUPS is metadata of quant/inventory.py only - resolve() / canonical() / the Quant feature names never read it.
GROUPS: dict[str, tuple[str, ...]] = {
    "th_direction": ("trainhub:TH_BASELINE", "trainhub:TH_LOGREG", "trainhub:TH_HGB", "trainhub:TH_XGB", "trainhub:TH_RF", "trainhub:TH_SVM"),
    "lab": ("lab:DUMMY", "lab:RULE", "lab:LOGREG", "lab:TREE", "lab:MINIROCKET", "lab:XGB", "lab:RESNET1D", "lab:SEW_SNN",
            "lab:LOGREG_PCA", "lab:LOGREG_GMM_AUG", "lab:LOGREG_NEUTRALIZED"),
    "si_move": ("si:MQ_RESNEXT1D_V2", "si:MQ_SEW_RESNET1D_V2", "si:MQ_SEW_RESNEXT_EB_V1", "si:MQ_MINIROCKET_RIDGE_V2", "si:MQ_SPIKE_BRAIN_FINANCE_V1"),
}
FAMILY_OWNED = ("TS_ARIMA", "TS_SARIMAX", "VOL_GARCH", "MICROSTRUCTURE", "PAIR_COINT", "STATARB", "KALMAN_LS", "BREAKOUT", "SEQ_LSTM", "SEQ_GRU",
                "RL_PPO", "NLP_SENTIMENT")
RULES = ("data_quality", "risk_engine", "news", "regime_v2", "structure_v2", "smc_pullback", "vamd", "fractal", "atr_vol", "candles_patterns",
         "liquidity", "flow_sr", "decomposition")

# 1.46 arch (I0274): what a Structure Intelligence family really does live (the rows said "raport SI na żądanie panelu" - wrong)
SI_LIVE = ("prognoza SHADOW STRUCTURE_MOVE_M1_V1 liczona na żywo przy każdej zamkniętej M1 (scalp.service -> scalp.dashboard (MTF) -> "
           "lab.si_service.forecast) tylko dla rodziny wskazanej w rejestrze SI shadow[STRUCTURE_MOVE_M1_V1]; archiwum si_forecasts / "
           "si_outcomes, migawka MTF i agent (get_structure_intelligence); bez adaptera Quant (PMW-PRED-2)")

# 1.46 arch: producers present in the code but absent from every model registry until 1.46 (found by the model inventory of the
# architecture task). Metadata only: they get a row in quant/inventory.py and in `models check`; resolve() / canonical() / dedup()
# DO NOT see them (adding them there could rename Quant feature columns - quant/features.py names columns after the canonical id). The
# prefix rule of resolve() returns an already prefixed name unchanged (lab: / si: / flow: / quant: ...) - no record that reaches the Quant
# features carries such a name in a field canonical() reads instead of its explicit canonical_id (1.46 arch I0529: 'quant' added).
# cid -> (name, category, env, files, quant role, adapter or None, reason when there is no adapter / note)
# 1.46 w2 (I0206): tsfm:tirex2 left this list - it is a row of sh/models.REGISTRY now (one inventory row, metadata in quant/inventory._OVR)
EXTRA_PRODUCERS: dict[str, tuple] = {
    "quant:tabicl_v2": ("TabICLv2 (estymator confidence kandydata, in-context)", "MODEL_PRETRAINED", ".venv_tabicl",
                        ["backend/masterquo/quant/tabicl.py", "backend/tabicl_runtime/"], "SETUP_EVENT", None,
                        "wynik per kandydat w pamięci QuantService (nieutrwalany) – brak samodzielnej predykcji"),
    "flow:markov3": ("Markov3 / Markov-diff flow (MQ_MARKOV3_FLOW_V1)", "MODEL_TRAINED", ".venv", ["backend/masterquo/lab/flow_context/markov.py"],
                     "CONTEXT_FEATURE", None, "liczony w komórkach Structure Intelligence (panel) – bez adaptera Quant"),
    "si:LOGREG": ("Structure Intelligence LOGREG (FAMILIES_ALL)", "MODEL_TRAINED", ".venv", ["backend/masterquo/lab/structure_task.py"],
                  "BASE_FORECAST", None, "rodzina bazowa SI – " + SI_LIVE),
    "si:XGB": ("Structure Intelligence XGB (FAMILIES_ALL)", "MODEL_TRAINED", ".venv", ["backend/masterquo/lab/structure_task.py"],
               "BASE_FORECAST", None, "rodzina bazowa SI – " + SI_LIVE),
    "quotes:MQ_NEWTONIAN_QUOTES_V2": ("QuoteEngine (kinematyka notowań)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/lab/quotes.py"],
                                      "CONTEXT_FEATURE", None, "wątek si-quotes – stan panelu SI, bez adaptera Quant"),
    "lab:M29_fourier": ("Lab M29 Fourier (prognoza archiwizowana)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/lab/service.py"],
                        "TOOL", None, "archiwum lab_forecasts i ocena – obserwacja, nie głos"),
    "lab:M31_tick_kinematics": ("Lab M31 kinematyka ticków (legacy obok QuoteEngine)", "RULE_OR_MEASUREMENT", ".venv",
                                ["backend/masterquo/lab/service.py"], "TOOL", None, "stan panelu lab – obserwacja"),
    # Etap 4 krok B: handler lab_tradepad jest w api/routes/trading.py; plik zostaje jak w bazie (część widoku porównywanego w
    # test_arch146_e4_producers.TestViewsIdenticalToBase) – aktualizacja w Etapie 5 razem z migawką widoków.
    "lab:M42_trade_pad": ("Lab M42 trade pad (kalkulator)", "TOOL", ".venv", ["backend/masterquo/api/app.py"], "TOOL", None,
                          "kalkulator API na żądanie – nie model"),
    "lab:M39_M41_edge": ("Lab M39–M41 RepaintInspector / edge drift / bootstrap", "TOOL", ".venv", ["backend/masterquo/lab/service.py"], "TOOL",
                         None, "narzędzia diagnostyczne – nie głos"),
    "research:graph50": ("Research Graph50 (SCORE per cel)", "RESEARCH", ".venv", ["backend/masterquo/research/"], "BASE_FORECAST",
                         "modelhub.adapters.all_predictions", "rekordy z jawnym canonical_id research:graph50:<cel>"),
    "research:g7_smc_radar": ("Research G7 SMC radar", "RESEARCH", ".venv", ["backend/masterquo/research/"], "CONTEXT_FEATURE",
                              "modelhub.adapters.all_predictions", None),
    "research:sdformerflow": ("Research SDformerFlow (TH_SDFORMERFLOW)", "RESEARCH", ".venv_tirex2 (torch)", ["backend/masterquo/research/"],
                              "BASE_FORECAST", "modelhub.adapters.all_predictions", "wymaga środowiska z torch 2.14.1"),
    "mm:kalman_params": ("Parametry Kalmana (kalibracja BUZOA)", "TRAINABLE", ".venv", ["backend/masterquo/mm/orchestrator.py"], "TOOL", None,
                         "kandydat parametrów – serwis używa domyślnej konfiguracji (brak ścieżki na żywo)"),
    "mm:robust_vol": ("Robust volatility (część breakout_zones)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/mm/"], "CONTEXT_FEATURE",
                      None, "pole rekordu MM live – cechą Quant nie jest"),
    "mm:drift": ("Drift (PMW-MM)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/mm/drift.py"], "TOOL", None, "pole rekordu MM live"),
    "mm:bat_encoder": ("BAT encoder (losowe wagi, SHADOW_UNTRAINED)", "RESEARCH", ".venv", ["backend/masterquo/mm/", "backend/masterquo/api/wf32_routes.py"],
                       "NOT_A_VOTE", None, "tylko API /api/v1/models/bat/shadow; wagi niewytrenowane"),
    "extind:sar_context": ("Kontekst SAR (kalibracja siatki)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/extind/"], "CONTEXT_FEATURE", None,
                           "kontekst snapshotu ACTIVE / agenta – bez adaptera Quant"),
    "extind:knowledge": ("Reguły wiedzy IND-K01..K12", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/extind/knowledge.py"], "NOT_A_VOTE", None,
                         "opis dla agenta – nie głos"),
    "extind:IQ_GOLD_GANN": ("IQ Gold Gann (wskaźnik MT5, eksport kopert)", "NATIVE_MQL5", "MQL5 (MT5)", ["mql5/PMW_ExtIndicatorExporter.mq5"],
                            "CONTEXT_FEATURE", None, "natywny wskaźnik licencjonowany – działa tylko w terminalu MT5"),
    "extind:IQ_STAR_LINES": ("IQ Star Lines (wskaźnik MT5, eksport kopert)", "NATIVE_MQL5", "MQL5 (MT5)", ["mql5/PMW_ExtIndicatorExporter.mq5"],
                             "CONTEXT_FEATURE", None, "natywny wskaźnik licencjonowany – działa tylko w terminalu MT5"),
    "extind:PAL02M": ("PAL02M (tożsamość nieustalona)", "NO_SPEC", "-", ["config/extind_manifests_v1.json"], "NONE", None,
                      "NO_SPEC: tożsamość narzędzia niepotwierdzona – algorytm nie jest odtwarzany z nazwy"),
    "strategies:regime": ("MarketRegimeEngine MQ-REGIME-1.0.0 (wybór strategii ACTIVE)", "RULE_OR_MEASUREMENT", ".venv",
                          ["backend/masterquo/strategies/regime.py"], "GATE_EXISTING", None, "bramka ścieżki A – Quant jej nie dubluje"),
    "analysis:signals": ("Poziomy / range M5 / MITP / neutralizacja", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/analysis/"],
                         "GATE_EXISTING", None, "warunki setupów ścieżki A (S12) – Quant ich nie dubluje"),
    "analytics:session_engine": ("Silnik sesji (boxy sesyjne)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/analytics/"], "CONTEXT_FEATURE",
                                 None, "wejście rule:liquidity (OBSERVE)"),
    "engine:volzones": ("Strefy zmienności (panel)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/engine/service.py"], "NOT_A_VOTE", None,
                        "tylko API / kontekst agenta"),
    "apollo:market_trap": ("Market trap (SHADOW, ostrzeżenia)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/apollo/"], "NOT_A_VOTE", None,
                           "tylko GET /api/v1/market-trap"),
    "baskets:sfb": ("Strategy Filter Bucket koszyków FX", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/baskets/sfb.py"], "GATE_EXISTING", None,
                    "filtr koszyków (domyślnie OFF) – Quant go nie dubluje"),
    "ml:decision_tree_ranker": ("Decision tree ranker (WF3.2)", "MODEL_TRAINED", ".venv", ["backend/masterquo/api/wf32_routes.py"], "TOOL", None,
                                "nigdy nie trenowany w aplikacji – API zwraca FALLBACK_BASELINE"),
    "ml:association_rules": ("Reguły asocjacyjne (WF3.2)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/api/wf32_routes.py"], "NOT_A_VOTE",
                             None, "tylko API (OBSERVE)"),
    "ml:pt_directional_skill": ("Test Pesarana–Timmermanna (WF3.2)", "TOOL", ".venv", ["backend/masterquo/api/wf32_routes.py"], "TOOL", None,
                                "miara trafności na danych wywołującego – nie model"),
    "ml:change_point_engine": ("Change points PELT (WF3.2)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/api/wf32_routes.py"], "NOT_A_VOTE",
                               None, "tylko API"),
    "forecast:long_horizon": ("Rozkład 24–72 h (WF3.2)", "RULE_OR_MEASUREMENT", ".venv", ["backend/masterquo/api/wf32_routes.py"], "NOT_A_VOTE", None,
                              "tylko API i eksport"),
    "forecast:double_retest_v2": ("Double Retest v2 (flagi świec prognozy)", "RULE_OR_MEASUREMENT", ".venv_candles", ["backend/masterquo/forecast/"],
                                  "CONTEXT_FEATURE", None, "flagi w rekordzie prognozy – bez adaptera Quant"),
    "scalp:C_policy": ("Scalp C – ocena polityki hedge vs REDUCE w replay", "TOOL", ".venv_candles", ["backend/masterquo/training/runner.py"], "TOOL",
                       None, "wynik replayu w rejestrze scalp – nie predykcja"),
}

_ALIAS_TO: dict[str, str] = {}
for _c, _al in ALIASES.items():
    _ALIAS_TO[_c] = _c
    for _a in _al:
        _ALIAS_TO[_a] = _c
for _f in FAMILY_OWNED:
    _ALIAS_TO[_f] = _ALIAS_TO[f"family:{_f}"] = f"family:{_f}"
for _r in RULES:
    _ALIAS_TO[_r] = _ALIAS_TO[f"rule:{_r}"] = f"rule:{_r}"
_TH_KEY = re.compile(r"^(TH_[A-Z]+)_(M\d+|H\d+|D1)_H\d+$")        # trainhub model_key  TH_LOGREG_M5_H6
# owners whose 'owner:name' ids resolve to themselves (1.46 arch I0529: + 'quant' - quant:metamodel / quant:tabicl_v2 were 'unresolved:';
# no prediction record of all_predictions / quant.adapters is named 'quant:*', the MetaModel entry of the coordinator is read by family)
PREFIXES = ("trainhub", "mm", "family", "rule", "lab", "si", "flow", "forecast", "kronos", "tsfm", "scalp", "sh", "ml", "quant")

# 1.46 arch (I0009): alias knowledge read from ALIASES instead of literals copied into the services (modelhub/families/service.py,
# studio/registry.py, sh/models.py). Same values as the literals they replace (tests pin them).
TRAINHUB_FAMILY_ALIASES: tuple[str, ...] = tuple(a.split(":", 1)[1] for _c, _al in ALIASES.items() if _c.startswith("trainhub:")
                                                 for a in _al if a.startswith("family:"))      # TH_XGB / TH_RF / TH_SVM: no own vote, no own training
EVENT_GRU_FAMILY: str = next(a.split(":", 1)[1] for a in ALIASES["mm:event_engine_dir3"] if a.startswith("family:"))   # SEQ_GRU_EVENT


def mm_artifact_of(sh_row_id: str) -> str | None:
    """MM artifact id (mm/artifacts pointer key) of an SH registry row: mm_gpr -> gpr_logret, mm_hdc -> hdc_dir3, mm_event_engine ->
    event_engine_dir3, mm_ste_flownet -> ste_flownet_ret (the canonical 'mm:<artifact>' id). None for a row that is not an MM producer."""
    if not str(sh_row_id or "").startswith("mm_"):
        return None
    c = _ALIAS_TO.get(str(sh_row_id))
    return c.split(":", 1)[1] if c and c.startswith("mm:") else None


def resolve(name: str | None) -> str | None:
    if not name:
        return None
    n = str(name)
    if n in _ALIAS_TO:
        return _ALIAS_TO[n]
    m = _TH_KEY.match(n)
    if m and m.group(1) in [c.split(":")[1] for c in ALIASES if c.startswith("trainhub:")]:
        return f"trainhub:{m.group(1)}"
    if n.startswith("gold_candles_"):
        return "forecast:gold_candles"
    if ":" in n and n.split(":")[0] in PREFIXES:
        return n
    return None


def canonical(p: dict) -> str:
    """Canonical id of a prediction record; `unresolved:<name>` when nothing matches (never '?')."""
    if p.get("canonical_id"):
        return str(p["canonical_id"])
    for k in ("family", "model_key", "model_id", "model_name"):
        c = resolve(p.get(k))
        if c:
            return c
    raw = p.get("model_key") or p.get("family") or p.get("model_id") or p.get("model_name") or "bez_nazwy"
    return f"unresolved:{raw}"


def identity(p: dict) -> tuple:
    """Dedup key: one producer + one artifact version + one task/TF/horizon = one record (not equality of numbers)."""
    h = p.get("horizon") or {}
    return (canonical(p), p.get("model_version") or p.get("run_id"), p.get("task"), p.get("timeframe"), h.get("bars"), h.get("seconds"))


def dedup(preds: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (kept records with canonical_id set, dropped alias duplicates with the kept record they duplicate)."""
    kept, dropped, seen = [], [], {}
    for p in preds or []:
        q = dict(p)
        q["canonical_id"] = canonical(q)
        k = identity(q)
        if k in seen:
            dropped.append({"canonical_id": q["canonical_id"], "alias": p.get("family") or p.get("model_key") or p.get("model_name"),
                            "duplicate_of": seen[k], "reason": "ten sam producent, wersja, zadanie i horyzont – alias, bez drugiego głosu"})
            continue
        seen[k] = q.get("family") or q.get("model_key") or q.get("model_name")
        kept.append(q)
    return kept, dropped


def aliases_of(cid: str) -> list[str]:
    return sorted({a for a, c in _ALIAS_TO.items() if c == cid and a != cid})


# ---------------------------------------------------------------------------------------------------------------- decision.required_models
# 1.46 arch (I0000): the ids decision.required_models can name = EXACTLY the strings decision/coordinator.role_of matches (family /
# model_id / _mid = family or model_id or canonical) for a producer whose record can reach the coordinator - static, every producer, also
# one that is not running now:
#   without Quant ASSIST  FamilyService.predictions (family = the family id WITHOUT 'family:'; the Event GRU record: family SEQ_GRU_EVENT)
#                         + the TSFM rows (family tsfm:<model>); Kronos rows are no_required (never REQUIRED);
#   Quant ASSIST          the eligible Quant records (model_id = family or canonical_id - quant/service.coordinator_predictions): trainhub,
#                         Kronos / TSFM, gold_candles, research (family), quant.adapters.extended, lab families + the MetaModel entry.
# Used ONLY to refuse a NEWLY added unknown id at save (config.ConfigStore.update) and to report a saved one (coordinator status);
# role_of / evaluate_models never read it and never map an alias (a saved unknown id keeps blocking exactly as before).
HISTORY_IDS = ("kronos:Kronos-base", "tsfm:fincast")               # old records only - never produced by the running bot
REQUIRED_EXTENDED = ("rule:regime_v2", "rule:structure_v2", "rule:atr_vol", "rule:data_quality", "rule:news", "analysis:indicators",
                     "analysis:dxy_correlation", "analysis:zones", "analysis:montecarlo", "mm:kalman_cross", "mm:breakout_zones",
                     "mm:multi_indicator", "mm:smc_fvg", "mm:align_mean", "mm:gpr_logret", "scalp:A_direction")   # quant/adapters.extended
REQUIRED_RESEARCH = {"research:graph50": "research:graph50", "research:g7_smc_radar": "research:g7",
                     "research:sdformerflow": "research:sdformerflow"}                    # canonical_id -> family (research/service.py)
QUANT_METAMODEL = "quant:metamodel"


def required_ids() -> tuple[str, ...]:
    out = list(FAMILY_OWNED) + [EVENT_GRU_FAMILY]
    out += [c for c in ALIASES if c.startswith(("trainhub:", "tsfm:", "kronos:", "forecast:")) and c not in HISTORY_IDS]
    out += list(REQUIRED_EXTENDED) + list(GROUPS["lab"])            # lab:<family> incl. DUMMY (artifact on an explicit artifact_family=DUMMY)
    out += list(dict.fromkeys(REQUIRED_RESEARCH.values())) + [QUANT_METAMODEL]
    return tuple(dict.fromkeys(out))


def required_hint(name: str) -> str | None:
    """The valid REQUIRED id an unknown one most likely means - for the error message only, never applied automatically."""
    n = str(name or "").split("@", 1)[0]                              # Kronos coordinator rows: kronos:Kronos-small@M5
    valid = set(required_ids())
    if n in valid:
        return n
    for cid, fam in REQUIRED_RESEARCH.items():
        if n == cid or n.startswith(cid + ":"):
            return fam
    c = resolve(n)
    if c is None:
        return None
    if c.startswith("family:") and c.split(":", 1)[1] in FAMILY_OWNED:
        return c.split(":", 1)[1]
    if c == "mm:event_engine_dir3":
        return EVENT_GRU_FAMILY
    return c if c in valid else None


def unknown_required(names) -> list[tuple[str, str | None]]:
    """[(id, hint)] for every id that no producer's record can carry - such an id stays MISSING (MODEL_REQUIRED_UNAVAILABLE) for ever."""
    valid = set(required_ids())
    return [(str(n), required_hint(n)) for n in names or [] if str(n) not in valid]


# ---------------------------------------------------------------------------------------------------------------- PRODUCERS (Etap 4)
# 1.46 arch Etap 4 (ETAP2 §3/§4 "tożsamość modelu"): this module is the ONLY source of producer ids. The views - sh/models.REGISTRY (SH
# rows = aliases / GROUPS keys), modelhub/catalog (rows + canonical_id), mm/inventory.MODULES (module ids = aliases or MM_MODULES),
# quant/inventory (one entry per PRODUCERS id + the GROUPS rows) and tools/model_map (overlay keyed by canonical ids) - carry descriptions
# only and derive every canonical id with the functions below (tests/test_arch146_architecture.py::TestNoSecondIdSource).
# Metadata only, like EXTRA_PRODUCERS: resolve() / canonical() / identity() / dedup() and the Quant feature names never read the tables of
# this section (a new name in _ALIAS_TO could rename a trained MetaModel's input column). Values were literals of the views (same values).

# analysis services wired in runtime.py (+ the Quant MetaModel) -> inventory category; one inventory row each (source_registry runtime.py,
# descriptions in quant/inventory._ANALYSIS). Was a literal list of quant/inventory._analysis_rows (order kept: the inventory row order).
SERVICES: dict[str, str] = {"analysis:montecarlo": "SIMULATION", "analysis:zones": "ANALYSIS", "analysis:market_zones": "ANALYSIS",
                            "analysis:indicators": "ANALYSIS", "analysis:svp": "ANALYSIS", "analysis:dxy_correlation": "ANALYSIS",
                            "analysis:walls": "ANALYSIS", "analysis:evaluation": "ANALYSIS", QUANT_METAMODEL: "META_MODEL"}
# producers only named in documentation / traceability (no code): an inventory row with code_state NOT_IMPLEMENTED, never an adapter
NOT_IMPLEMENTED: tuple[str, ...] = ("ext:catboost",)
# PMW-MM modules of mm/inventory.MODULES that are no producer of their own (no alias in ALIASES) -> quant role of their inventory row
# (tool / infrastructure / spec missing). Was quant/inventory._MM_TOOL. The other modules are aliases of an mm:* producer (mm_module_id).
MM_MODULES: dict[str, str] = {"buzoa": "TOOL", "sdom": "TOOL", "stfs": "TOOL", "quant_momentum": "NONE", "renko": "NONE", "head_shoulders": "NONE",
                              "data_grabber": "TOOL", "tsvp": "TOOL", "mathbench": "TOOL", "chart_sync": "TOOL", "fusion_board": "TOOL"}
# modelhub/catalog rows of an analysis service: catalog row id -> canonical id. NOT aliases (resolve() never sees them: 'zone_map' is no
# record name). Was modelhub/catalog._FIXED_CANON (declared twice there).
CATALOG_ROWS: dict[str, str] = {"market_zones": "analysis:market_zones", "zone_map": "analysis:zones", "monte_carlo": "analysis:montecarlo"}
# TSFM model ids (SH rows, tsfm/settings.MODEL_IDS, TsfmService workers) = the running tsfm:* producers in ALIASES order; FinCast is history.
# Was the literal ("chronos2", "granite_ttm", "tirex2") of sh/models.probe (tests pin it to tsfm/settings.MODEL_IDS).
TSFM_MODELS: tuple[str, ...] = tuple(c.split(":", 1)[1] for c in ALIASES if c.startswith("tsfm:") and c not in HISTORY_IDS)


def sh_row_id(sid: str) -> str:
    """Canonical id of a sh/models.REGISTRY row: 'group:<id>' for a GROUPS row (th_direction / lab / si_move), else the producer it is an
    alias of, else 'sh:<id>' (a row unknown here - the architecture test keeps that fallback unused). Was copied in quant/inventory._sh_rows
    and modelhub/catalog.canonical_row_id."""
    s = str(sid)
    return f"group:{s}" if s in GROUPS else (resolve(s) or f"sh:{s}")


def mm_module_id(mid: str) -> str:
    """Canonical id of a mm/inventory.MODULES module: the mm:* producer it is an alias of (kalman -> mm:kalman_cross), else 'mm:<module>'
    (a MM_MODULES entry). Was copied in quant/inventory._mm_rows and modelhub/catalog (canonical_row_id, _canonical_of, the SH join)."""
    return resolve(mid) or f"mm:{mid}"


def _producers() -> dict[str, str]:
    out: dict[str, str] = {}
    for c in ALIASES:
        if c not in HISTORY_IDS:
            out[c] = "ALIASES"
    for f in FAMILY_OWNED:
        out[f"family:{f}"] = "FAMILY_OWNED"
    for r in RULES:
        out[f"rule:{r}"] = "RULES"
    for g, members in GROUPS.items():
        for m in members:
            out.setdefault(m, f"GROUPS[{g}]")
    for c in EXTRA_PRODUCERS:
        out[c] = "EXTRA_PRODUCERS"
    for c in SERVICES:
        out[c] = "SERVICES"
    for c in NOT_IMPLEMENTED:
        out[c] = "NOT_IMPLEMENTED"
    for m in MM_MODULES:
        out[f"mm:{m}"] = "MM_MODULES"
    return out


# PRODUCERS: every canonical producer id of the bot -> the table of this module that declares it. quant/inventory.build() lists exactly
# these ids (+ one 'group:<id>' row per GROUPS key) - no view may add an id that is not here (TestNoSecondIdSource). History ids
# (HISTORY_IDS) are aliases of old records only, no producer.
PRODUCERS: dict[str, str] = _producers()
