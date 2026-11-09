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
* SH row kronos and model_name Kronos-base -> `kronos:Kronos-base` (1.37; historical Kronos-small rows -> `kronos:Kronos-small`);
* SH rows chronos2 / fincast and model_name Chronos-2 / FinCast -> `tsfm:chronos2` / `tsfm:fincast` (1.37);
* SH row th_direction is a GROUP (all active trainhub packages), SH rows lab / si_move are GROUPS of several families.
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
    "kronos:Kronos-base": ("kronos", "Kronos-base", "KRONOS_BASE"),
    "kronos:Kronos-small": ("Kronos-small", "KRONOS_SMALL"),          # history only (used until 1.36.0)
    "tsfm:chronos2": ("chronos2", "Chronos-2", "CHRONOS2"),
    "tsfm:fincast": ("fincast", "FinCast", "FINCAST"),
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
# rows that name a GROUP of producers (never a producer themselves)
GROUPS: dict[str, tuple[str, ...]] = {
    "th_direction": ("trainhub:TH_BASELINE", "trainhub:TH_LOGREG", "trainhub:TH_HGB", "trainhub:TH_XGB", "trainhub:TH_RF", "trainhub:TH_SVM"),
    "lab": ("lab:DUMMY", "lab:RULE", "lab:LOGREG", "lab:TREE", "lab:MINIROCKET", "lab:XGB", "lab:RESNET1D", "lab:SEW_SNN"),
    "si_move": ("si:MQ_RESNEXT1D_V2", "si:MQ_SEW_RESNET1D_V2", "si:MQ_SEW_RESNEXT_EB_V1", "si:MQ_MINIROCKET_RIDGE_V2", "si:MQ_SPIKE_BRAIN_FINANCE_V1"),
}
FAMILY_OWNED = ("TS_ARIMA", "TS_SARIMAX", "VOL_GARCH", "MICROSTRUCTURE", "PAIR_COINT", "STATARB", "KALMAN_LS", "BREAKOUT", "SEQ_LSTM", "SEQ_GRU",
                "RL_PPO", "NLP_SENTIMENT")
RULES = ("data_quality", "risk_engine", "news", "regime_v2", "structure_v2", "smc_pullback", "vamd", "fractal", "atr_vol", "candles_patterns",
         "liquidity", "flow_sr", "decomposition")

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
    if ":" in n and n.split(":")[0] in ("trainhub", "mm", "family", "rule", "lab", "si", "flow", "forecast", "kronos", "tsfm", "scalp", "sh", "ml"):
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
