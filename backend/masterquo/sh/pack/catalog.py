"""Catalog of the 20 SH variants (PMW-SH-PACK-2): ONE owner of names, families, clusters, setup groups, time frames, policies and
parameters for the backend, the API, the panels and the training list (the frontend never keeps its own list of 20 names).

Definitions (this file) + parameters (config/sh_strategy_pack_v2.json, user override data/sh/pack_override.json) -> effective variant
with its own hash. The hash changes with any parameter, the pack version, the family rules or the pip definition; an open plan keeps the
frozen variant it was created with. `strategy` stays the compatible FAMILY name (SCALPING / HEDGING) used by the old execution and tables;
`strategy_id` is the variant identity (PMW_SC01..SC10, PMW_HG01..HG10). Old records without strategy_id are LEGACY_SCALPING /
LEGACY_HEDGING and never inherit a new variant's results or validation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path

from ... import paths

PACK_FILE = paths.ROOT_DIR / "config" / "sh_strategy_pack_v2.json"
TFS = ("M1", "M3", "M5", "M15", "H1")
LEGACY = {"SCALPING": "LEGACY_SCALPING", "HEDGING": "LEGACY_HEDGING"}

# id: (name, family, cluster, setup_group, detector, implemented TFs, context TFs, management policy, short description, sources, reuse)
_DEF = {
    "PMW_HG01": ("MTF EMA Pullback / Correction Hedge", "HEDGING", "TREND_PULLBACK", "TREND_PULLBACK_EMA", "trend_pullback_ema", ("M5", "M15"),
                 ("M15", "H1"), "HEDGE_CORRECTION_EMA20",
                 "Korekta do EMA20±b w trendzie M15/H1, zamknięcie nad EMA20+b i nad high[t-1]; hedge 0,50 po dwóch zamknięciach M5 pod EMA20−b.",
                 ("B02", "B06"), "wspólny detektor pullbacku EMA (S01/S11 – ta sama zasada, czyste funkcje)"),
    "PMW_HG02": ("Breakout–Retest / Level Failure Hedge", "HEDGING", "STRUCTURE_BREAKOUT", "BREAKOUT_RETEST", "breakout_retest", ("M5", "M15"),
                 ("H1",), "HEDGE_LEVEL_FAILURE",
                 "Wybicie potwierdzonego oporu L zamrożonego przed wybiciem, retest w 3 świecach; hedge 0,50 po utracie L−b i potwierdzeniu pod L.",
                 ("B02", "B06"), "S06 (wybicie–retest) – poziom z potwierdzonych pivotów"),
    "PMW_HG03": ("Donchian Trend / Midchannel Hedge", "HEDGING", "CHANNEL_TREND", "CHANNEL_BREAKOUT", "donchian_retest", ("M15",),
                 ("H1",), "HEDGE_MIDCHANNEL",
                 "Zamknięcie M15 nad maksimum 20 poprzednich świec przy ADX≥25 i trendzie H1, wejście po retescie; hedge 0,25 po dwóch M5 pod środkiem kanału.",
                 ("B09", "B11", "B02"), "S03 (kanał Donchiana bez bieżącej świecy)"),
    "PMW_HG04": ("Session Opening Range / Range Return Hedge", "HEDGING", "SESSION_BREAKOUT", "OPENING_RANGE", "opening_range", ("M5",),
                 ("M15", "H1"), "HEDGE_RANGE_RETURN",
                 "OR 15 min (Londyn 08:00, Nowy Jork 08:20, IANA/DST), wybicie i retest granicy; hedge 0,50 po powrocie pod OR_high−b i pod środek OR.",
                 ("B10", "B06", "B02"), "S05 (sesje z DST)"),
    "PMW_HG05": ("Anchored VWAP Trend / AVWAP Loss Hedge", "HEDGING", "VWAP_TREND", "VWAP", "avwap_pullback", ("M5", "M15"),
                 ("H1",), "HEDGE_AVWAP_LOSS",
                 "AVWAP od początku doby handlowej (tick volume = aktywność feedu), korekta do AVWAP±b i powrót nad; hedge 0,50 po dwóch M5 pod AVWAP−b.",
                 ("B07", "B02"), "PMW-IND-1 AVWAP (ta sama definicja ważenia tick volume)"),
    "PMW_HG06": ("Volatility Squeeze / Impulse Exhaustion Hedge", "HEDGING", "VOLATILITY_BREAKOUT", "SQUEEZE_BREAKOUT", "squeeze_retest", ("M5",),
                 ("M15", "H1"), "HEDGE_IMPULSE_EXHAUSTION",
                 "BandWidth BB(20,2) < 20. percentyl ze 120, wybicie nad pasmo i maksimum 10 świec, retest; hedge 0,50 po dwóch M5 pod poziomem wybicia z korpusem > 0,8 ATR.",
                 ("B12", "B13", "B02"), "S04 (kompresja zmienności)"),
    "PMW_HG07": ("Failed Breakout Reclaim / Reclaim Loss Hedge", "HEDGING", "FAILED_BREAKOUT", "SWEEP_RECLAIM", "sweep_reclaim_hg", ("M5", "M15"),
                 ("H1",), "HEDGE_RECLAIM_LOSS",
                 "Zejście pod wsparcie L o b i powrót nad L+b, potwierdzone przebiciem high świecy reclaim; hedge 0,25 po ponownej utracie L.",
                 ("B06", "B02"), "S07/S12 (geometria ceny – bez deklarowania stopów uczestników)"),
    "PMW_HG08": ("Value Area Rotation / Acceptance Hedge", "HEDGING", "VALUE_REVERSION", "VALUE_AREA", "value_area_rejection", ("M5",),
                 ("M15", "H1"), "HEDGE_VALUE_ACCEPTANCE",
                 "Profil zakończonej poprzedniej sesji (PMW-SVP-1, tick activity), odrzucenie VAL, cele POC/VAH; hedge 0,25 po dwóch M5 pod VAL−b.",
                 ("B08", "B02"), "PMW-SVP-1 (te same funkcje histogramu i value area)"),
    "PMW_HG09": ("Adaptive Trend / Volatility Budget Hedge", "HEDGING", "VOLATILITY_CONTROL", "TREND_PULLBACK_EMA", "adaptive_trend", ("M5", "M15"),
                 ("H1",), "HEDGE_VOLATILITY_BUDGET",
                 "EMA20>EMA50, korekta 2–5 świec, wybicie maksimum dwóch świec; hedge jednorazowo ratio=clip(1−σ_wejście/σ_teraz; 0,25–0,50) przy σ×1,5.",
                 ("B11", "B13", "B02"), "S02 (trend adaptacyjny); wariant GARCH – osobny, nie jest podmieniany"),
    "PMW_HG10": ("Trend Continuation / Profit Giveback Hedge", "HEDGING", "PROFIT_PROTECTION", "TREND_PULLBACK_EMA", "trend_pullback_ema", ("M5", "M15"),
                 ("M15", "H1"), "HEDGE_PROFIT_GIVEBACK",
                 "Wejście jak HG01 (ten sam detektor – nie drugi głos); hedge 0,50 po MFE ≥ 1,5r i oddaniu ≥ 0,5r z zamknięciem M5 pod EMA9.",
                 ("B02", "B06"), "detektor HG01, osobna polityka zarządzania"),
    "PMW_SC01": ("EMA20 Trend Pullback", "SCALPING", "TREND_PULLBACK", "TREND_PULLBACK_EMA", "trend_pullback_ema", ("M1", "M3"),
                 ("M5", "M15"), "SCALP_TWO_TP",
                 "Korekta do EMA20±b przy trendzie M5 i M15, zamknięcie nad EMA20+b i high[t-1]; SL pod minimum korekty.",
                 ("B06", "B14"), "wspólny detektor pullbacku EMA (S01/S11)"),
    "PMW_SC02": ("Session VWAP Reclaim–Retest", "SCALPING", "VWAP_RECLAIM", "VWAP", "vwap_reclaim", ("M1", "M3"),
                 ("M15",), "SCALP_TWO_TP",
                 "Dwa zamknięcia pod VWAP sesji, przebicie VWAP+b i retest VWAP±b zakończony wzrostowo; > 4 przecięcia w 10 świecach odrzuca setup.",
                 ("B07", "B14"), "AVWAP sesji PMW-IND-1"),
    "PMW_SC03": ("Opening Range Breakout–Retest", "SCALPING", "SESSION_BREAKOUT", "OPENING_RANGE", "opening_range", ("M1", "M3", "M5"),
                 ("M15",), "SCALP_TWO_TP",
                 "Zamrożony OR 15 min, zamknięcie nad OR_high+b, retest w 3 świecach; jedno wejście na kierunek i sesję, do 60 min po OR.",
                 ("B10",), "S05 (sesje z DST)"),
    "PMW_SC04": ("Donchian20 Micro Breakout", "SCALPING", "CHANNEL_BREAKOUT", "CHANNEL_BREAKOUT", "donchian_retest", ("M3", "M5"),
                 ("M15",), "SCALP_TWO_TP",
                 "Zamknięcie nad maksimum 20 poprzednich świec+b przy ADX≥25 i rosnącym ATR, retest wybitego poziomu.",
                 ("B09", "B11"), "S03 (kanał bez bieżącej świecy)"),
    "PMW_SC05": ("Bollinger Squeeze Breakout", "SCALPING", "VOLATILITY_BREAKOUT", "SQUEEZE_BREAKOUT", "squeeze_break", ("M1", "M3", "M5"),
                 ("M5", "M15"), "SCALP_TWO_TP",
                 "BandWidth < 20. percentyl przez ≥3 z 5 świec, zamknięcie nad górnym pasmem t-1 i maksimum 10 świec+b, rosnący ATR.",
                 ("B12", "B13"), "S04 (kompresja)"),
    "PMW_SC06": ("Sweep / Failed Breakout Reclaim", "SCALPING", "FAILED_BREAKOUT", "SWEEP_RECLAIM", "sweep_reclaim_sc", ("M1", "M3"),
                 ("M5", "M15"), "SCALP_TWO_TP",
                 "Low pod swing low M5 − b, zamknięcie nad L+b, kolejna świeca zamyka się nad high świecy reclaim (maks. 2 świece).",
                 ("B06",), "S07/S12 (geometria ceny)"),
    "PMW_SC07": ("Bollinger Range Reversion + RSI", "SCALPING", "RANGE_REVERSION", "RANGE_REVERSION", "bb_rsi_reversion", ("M1", "M3"),
                 ("M5", "M15"), "SCALP_TWO_TP",
                 "Zakres M15 (ADX<20), ADX M5<20; low t-1 pod dolnym pasmem, t wraca do pasm nad high[t-1], RSI z ≤30 na >30; cele środek i górne pasmo.",
                 ("B12", "B14"), "S08/S09 (RSI, BB)"),
    "PMW_SC08": ("Stochastic Trend Pullback", "SCALPING", "TREND_PULLBACK", "TREND_PULLBACK_EMA", "stoch_pullback", ("M1", "M3"),
                 ("M5", "M15"), "SCALP_TWO_TP",
                 "Trend M5/M15, %K<20 w korekcie, przecięcie %K nad %D z zamknięciem nad high[t-1] i nad EMA50 (ta sama grupa co SC01 – nie niezależny głos).",
                 ("B15", "B14"), "wspólny detektor pullbacku, osobny trigger"),
    "PMW_SC09": ("MACD Momentum Reset", "SCALPING", "MOMENTUM_CONTINUATION", "TREND_PULLBACK_EMA", "macd_reset", ("M3", "M5"),
                 ("M15",), "SCALP_TWO_TP",
                 "Linia MACD > 0 przez 3 świece, histogram ≤ 0 w korekcie i przejście > 0 na t, zamknięcie nad high[t-1] i EMA20.",
                 ("B17",), "istniejący MACD (powiązany z EMA/Stochastic – nie trzy niezależne modele)"),
    "PMW_SC10": ("Session Value Area Rejection", "SCALPING", "VALUE_REVERSION", "VALUE_AREA", "value_area_rejection", ("M1", "M5"),
                 ("M15",), "SCALP_TWO_TP",
                 "Profil zakończonej poprzedniej sesji, low pod VAL−b i powrót nad VAL+b, następna świeca nad high; cele POC i VAH.",
                 ("B08",), "PMW-SVP-1"),
}
IDS = tuple(sorted(_DEF))
SC_IDS = tuple(i for i in IDS if i.startswith("PMW_SC"))
HG_IDS = tuple(i for i in IDS if i.startswith("PMW_HG"))
# deterministic family priority used when no validated ranker exists (documented, not a probability): structure > trend > reversion
CLUSTER_PRIORITY = ("STRUCTURE_BREAKOUT", "CHANNEL_TREND", "TREND_PULLBACK", "VWAP_TREND", "SESSION_BREAKOUT", "VOLATILITY_BREAKOUT",
                    "CHANNEL_BREAKOUT", "MOMENTUM_CONTINUATION", "VWAP_RECLAIM", "FAILED_BREAKOUT", "VOLATILITY_CONTROL", "PROFIT_PROTECTION",
                    "VALUE_REVERSION", "RANGE_REVERSION")


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def _override_path() -> Path:
    d = paths.data_dir() / "sh"
    d.mkdir(parents=True, exist_ok=True)
    return d / "pack_override.json"


def _vhash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def validation_status(vid: str) -> dict:
    """Real validation state of a variant: only a report written by the pack replay on REAL_USER_DATA can change NOT_VALIDATED."""
    p = paths.data_dir() / "sh" / "pack_validation" / f"{vid}.json"
    if not p.exists():
        return {"status": "NOT_VALIDATED", "reason": "brak raportu walidacji na danych MT5 użytkownika (replay pakietu)"}
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "NOT_VALIDATED", "reason": f"raport nieczytelny ({type(exc).__name__})"}
    return {"status": r.get("verdict") or "INSUFFICIENT_EVIDENCE", "reason": r.get("verdict_reason"), "report_id": r.get("report_id"),
            "data_kind": r.get("data_kind"), "created_at": r.get("created_at")}


def load(override: dict | None = None) -> dict:
    """Effective pack: definitions + json + user override. Every variant carries its config_hash (variant + family + common + pip)."""
    base = json.loads(PACK_FILE.read_text(encoding="utf-8"))
    ov = override
    if ov is None:
        p = _override_path()
        ov = (json.loads(p.read_text(encoding="utf-8")).get("override") if p.exists() else None) or {}
    cfg = _merge(base, ov)
    out = {"pack_version": cfg["pack_version"], "common": cfg["common"], "families": cfg["families"], "instruments": cfg["instruments"],
           "variants": {}, "errors": []}
    for vid in IDS:
        name, fam, cluster, group, det, tfs, ctx, pol, desc, src, reuse = _DEF[vid]
        vc = (cfg.get("variants") or {}).get(vid) or {}
        sig = [t for t in (vc.get("signal_tfs") or tfs) if t in tfs]
        bad = [t for t in (vc.get("signal_tfs") or []) if t not in tfs]
        if bad:
            out["errors"].append(f"{vid}: TF {bad} nie jest zaimplementowany (dozwolone {list(tfs)})")
        fam_c = cfg["families"][fam]
        hedge = dict(vc.get("hedge") or {}) if fam == "HEDGING" else None
        if hedge is not None:
            for k in ("ratio", "ratio_max"):
                if k in hedge and not 0 < float(hedge[k]) <= float(fam_c.get("max_ratio", 0.5)):
                    out["errors"].append(f"{vid}: {k}={hedge[k]} poza (0, {fam_c.get('max_ratio', 0.5)}] – bez martingale")
        v = {"strategy_id": vid, "name": name, "family": fam, "strategy": fam, "cluster": cluster, "setup_group_id": group, "detector": det,
             "implemented_tfs": list(tfs), "signal_tfs": sig, "context_tfs": list(ctx), "management_policy_id": pol, "description": desc,
             "sources": list(src), "reuse": reuse, "enabled": bool(vc.get("enabled", True)), "params": dict(vc.get("params") or {}),
             "position_max_minutes": float(vc.get("position_max_minutes") or 30), "hedge": hedge, "rules": fam_c}
        v["strategy_version"] = f"{cfg['pack_version']}/{vid}"
        v["config_hash"] = _vhash({"v": {k: v[k] for k in ("strategy_id", "signal_tfs", "params", "position_max_minutes", "hedge", "detector",
                                                          "management_policy_id")},
                                   "rules": fam_c, "common": cfg["common"], "pip": cfg["instruments"], "pack": cfg["pack_version"]})
        out["variants"][vid] = v
    out["hash"] = _vhash([out["variants"][k]["config_hash"] for k in IDS])
    return out


def variant(cfg: dict, vid: str) -> dict:
    if vid not in cfg["variants"]:
        raise KeyError(f"NIEZNANY_WARIANT:{vid}")
    return cfg["variants"][vid]


def public(cfg: dict | None = None) -> dict:
    """Catalog for the API / panels / training list (names, TFs, parameters, readiness and validation from the backend)."""
    cfg = cfg or load()
    items = []
    for vid in IDS:
        v = cfg["variants"][vid]
        items.append({**{k: v[k] for k in ("strategy_id", "name", "family", "cluster", "setup_group_id", "implemented_tfs", "signal_tfs", "context_tfs",
                                           "management_policy_id", "description", "sources", "reuse", "enabled", "params", "position_max_minutes",
                                           "hedge", "strategy_version", "config_hash")},
                      "implementation": "IMPLEMENTED", "validation": validation_status(vid),
                      "targets": {"tp1_min_pips": v["rules"]["tp1_min_pips"], "rr_min": v["rules"]["rr_min"], "shares": v["rules"]["shares"]}})
    return {"pack_version": cfg["pack_version"], "hash": cfg["hash"], "count": len(items), "families": {"SCALPING": len(SC_IDS), "HEDGING": len(HG_IDS)},
            "pip": cfg["instruments"], "common": cfg["common"], "family_rules": cfg["families"], "items": items, "errors": cfg["errors"],
            "legacy": LEGACY, "note": "numeracja jest identyfikatorem, nie rankingiem wyników; parametry to punkty startowe badania PMW"}


ALLOWED_OVERRIDE = {"variants", "common", "families"}


def save_override(patch: dict, who: str = "panel") -> dict:
    bad = [k for k in patch if k not in ALLOWED_OVERRIDE]
    if bad:
        raise ValueError("NIEDOZWOLONE_POLA:" + ",".join(bad))
    p = _override_path()
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"version": 0, "override": {}, "history": []}
    new_ov = _merge(cur.get("override") or {}, patch)
    eff = load(new_ov)
    if eff["errors"]:
        raise ValueError("; ".join(eff["errors"]))
    for vid, v in eff["variants"].items():
        r = v["rules"]
        if r["rr_min"] < (2.0 if v["family"] == "SCALPING" else 3.0) or r["tp1_min_pips"] < (25 if v["family"] == "SCALPING" else 40):
            raise ValueError(f"{vid}: minimum pakietu (TP1 {r['tp1_min_pips']} pips, RR {r['rr_min']}) poniżej specyfikacji")
        if abs(sum(r["shares"]) - 1.0) > 1e-9 or len(r["shares"]) != 2:
            raise ValueError(f"{vid}: dokładnie dwa TP, udziały sumują się do 100 %")
    cur["history"] = (cur.get("history") or [])[-50:] + [{"version": cur.get("version", 0), "override": cur.get("override"), "at": time.time()}]
    cur.update(version=cur.get("version", 0) + 1, override=new_ov, saved_at=time.time(), saved_by=who)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return load()
