"""Adapter to the unchanged MasterQUO reference engines in backend/vendor/legacy_core.

Used unchanged (byte-identical, verified against VENDOR_MANIFEST.json by tests):
  M02  vendor/M02/M02_REFERENCE_ENGINE.py      regime, pivots, structural direction (MTF)
  M02I vendor/M02I/M02I_INDICATOR_ENGINE.py    indicator profile per timeframe (Wilder RSI/ATR/ADX, MACD SMA signal)
  M03  vendor/M03/M03_REFERENCE_ENGINE.py      BOS/CHoCH/MSS, sweeps, FVG, OB candidates, premium/discount, 5-CORE early
  M07  M07_M03E_PROFILE_DETECTOR.py            operational profiles MVP/SMC/SCALPING (XAU-S01/S14/S06)
       M07_M03E_PROFILE_RUNTIME.ResearchPlanLock  frozen plan lock (no setup identity churn)

The adapter only *builds the input packet* (snapshot in the legacy M01 format) from MT5 bars that
passed the data-quality gate. It never edits engine outputs except to read them.
"""
from __future__ import annotations

import copy
import json
import sys
import threading
from pathlib import Path

from .. import paths
from ..timeutil import parse_iso

_IMPORT_LOCK = threading.Lock()
_MODS: dict = {}
POLICY = "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS"
GOOD = ("PASS", "PASS_WITH_LIMITATIONS")


def modules() -> dict:
    with _IMPORT_LOCK:
        if _MODS:
            return _MODS
        core = paths.LEGACY_CORE_DIR
        for p in (core, core / "vendor" / "M02", core / "vendor" / "M02I", core / "vendor" / "M03", core / "vendor"):
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)
        import M02_REFERENCE_ENGINE as m02  # noqa: E402
        import M02I_INDICATOR_ENGINE as m02i  # noqa: E402
        import M03_REFERENCE_ENGINE as m03  # noqa: E402
        import M07_M03E_PROFILE_DETECTOR as m07  # noqa: E402
        import M07_M03E_PROFILE_RUNTIME as m07rt  # noqa: E402
        import M03E_M10_PIPELINE as m03e  # noqa: E402  (construct_early, used by M07)
        _MODS.update(m02=m02, m02i=m02i, m03=m03, m07=m07, m07rt=m07rt, m03e=m03e)
        return _MODS


def load_json(rel: str) -> dict:
    return json.loads((paths.LEGACY_CORE_DIR / rel).read_text(encoding="utf-8"))


class Profiles:
    def __init__(self):
        self.m02 = load_json("vendor/M02/M02_PROFILE.example.json")
        self.m02i = load_json("vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json")
        self.m03 = load_json("M03_PROFILE.example.json")
        self.m07 = modules()["m07"].read_config(str(paths.LEGACY_CORE_DIR / "OPERATIONAL_PROFILES_v1.json"))

    def required_closed_bars(self) -> dict[str, int]:
        """History requirement per TF from the actual profiles (not one fixed 90-bar limit)."""
        req = {}
        tp = self.m02i.get("timeframe_profiles", {})
        for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
            r = max(self.m02["min_closed_bars"], self.m03["min_closed_bars"], 30,
                    tp.get(tf, {}).get("min_closed_bars", self.m02i["min_closed_bars"]))
            req[tf] = r
        return req


def build_snapshot(*, snapshot_id: str, analysis_id: str, as_of: str, symbol: str, alias: str,
                   closed_bars: dict[str, list[dict]], analysis_status: str, reason_codes: list[str]) -> dict:
    """Legacy M01 DATA_SNAPSHOT from closed MT5 bars (Bid-based OHLC from the terminal)."""
    by_tf = {}
    for tf, bars in closed_bars.items():
        rows = []
        for b in bars:
            conf = b["close_confirmed_utc"]
            avail = b["available_at"] or conf
            if parse_iso(avail) < parse_iso(conf):
                avail = conf
            rows.append({"instrument_id": alias, "exact_symbol": symbol, "source_id": "MT5_TERMINAL",
                         "timeframe": tf, "bar_state": "CLOSED", "bar_open_utc": b["open_utc"],
                         "close_confirmed_at": conf, "available_at": avail, "price_basis": "BID",
                         "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"],
                         "tick_volume": b["tv"], "real_volume": float(b.get("rv") or 0),
                         "evidence_id": f"MT5:{symbol}:{tf}:{b['t_raw']}", "revision": b.get("revision", 0)})
        by_tf[tf] = rows
    return {"analysis_id": analysis_id, "snapshot_id": snapshot_id, "as_of": as_of,
            "instrument_id": alias, "exact_symbol": symbol, "data_source_policy": POLICY,
            "visual_capture_enabled": False, "candles_by_tf": by_tf, "auxiliary_candles_by_instrument": {},
            "data_gates": [{"gate_id": "MQAI_DATA_QUALITY", "required_for": ["ANALYSIS", "DIRECTION"],
                            "status": analysis_status, "reason_codes": reason_codes},
                           {"gate_id": "MQAI_EXECUTION_GATE", "required_for": ["EXECUTION"], "status": "PENDING",
                            "reason_codes": ["EXECUTION_DECIDED_BY_RISK_AND_MODE_GATE"]}],
            "analysis_gate": {"status": analysis_status, "required_for": ["ANALYSIS", "DIRECTION"]},
            "execution_gate": {"status": "PENDING", "required_for": ["EXECUTION"]},
            "account_profile": "ZERO_SPREAD_DECLARED_UNVERIFIED"}


def _tf_direction(market: dict, tf: str) -> str:
    per = (market.get("timeframes") or {}).get(tf) or {}
    return per.get("direction", "UNKNOWN") if per.get("status") in ("PASS", "PASS_WITH_LIMITATIONS") else "UNKNOWN"


def resolve_structure(market: dict, trading_style: str, policy: str) -> dict:
    """Apply the configured structure policy on top of the unchanged M02 output.

    M02 resolves a structural direction only when both structural timeframes agree (H4+H1 for
    SCALP). Relaxed policies let the lower structural TF (H1) lead; the result is passed to
    M03/M07 instead of M02's own value and the original is kept in `structural_direction_m02`.
    """
    orig = market.get("structural_direction")
    out = dict(market)
    out["structural_direction_m02"] = orig
    out["structure_policy"] = policy
    out["structure_notes"] = []
    if policy == "STRICT_H4_H1" or orig in ("BULLISH", "BEARISH"):
        return out
    higher, lead = ("H4", "H1") if trading_style == "SCALP" else ("D1", "H4")
    d_lead, d_high = _tf_direction(market, lead), _tf_direction(market, higher)
    if d_lead not in ("BULLISH", "BEARISH"):
        return out
    opposite = {"BULLISH": "BEARISH", "BEARISH": "BULLISH"}[d_lead]
    if d_high == opposite:
        if policy != "H1_LEAD":
            return out
        out["structure_notes"].append(f"STRUCTURE_COUNTER_{higher}")
    else:
        out["structure_notes"].append(f"STRUCTURE_{lead}_LEADS_{higher}_{d_high}")
    out["structural_direction"] = d_lead
    return out


class LegacyEngines:
    def __init__(self, lock_db: Path):
        self.mods = modules()
        self.profiles = Profiles()
        self.lock = self.mods["m07rt"].ResearchPlanLock(str(lock_db), self.profiles.m07)
        self.regime_memory = self.mods["m02"].RegimeMemory(self.profiles.m02["regime_confirmation_bars"])

    def reset_memory(self) -> None:
        self.regime_memory = self.mods["m02"].RegimeMemory(self.profiles.m02["regime_confirmation_bars"])

    def run(self, snapshot: dict, mode: str, structure_policy: str = "STRICT_H4_H1") -> dict:
        m = self.mods
        out: dict = {"errors": []}
        try:
            market = m["m02"].analyze(snapshot, self.profiles.m02,
                                      runtime_health={"status": "UNKNOWN", "execution_data_gate": "PENDING"},
                                      memory=self.regime_memory)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            out["errors"].append(f"M02:{type(exc).__name__}:{exc}")
            return out
        market = resolve_structure(market, self.profiles.m02.get("trading_style", "SCALP"), structure_policy)
        out["m02"] = market
        try:
            out["m02i"] = m["m02i"].analyze({"data_snapshot": snapshot, "market_state": market}, self.profiles.m02i)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            out["errors"].append(f"M02I:{type(exc).__name__}:{exc}")
        try:
            m03 = m["m03"].analyze(snapshot, market, self.profiles.m03)
            out["m03"] = m03
        except (ValueError, KeyError, TypeError, ZeroDivisionError, IndexError) as exc:
            out["errors"].append(f"M03:{type(exc).__name__}:{exc}")
            return out
        try:
            plan, discovery = self.lock.choose(snapshot, market, m03, mode)
            out["m07_plan"] = copy.deepcopy(plan)
            out["m07"] = discovery
        except Exception as exc:  # sqlite / unexpected; never fabricate a plan
            out["errors"].append(f"M07:{type(exc).__name__}:{exc}")
        return out
