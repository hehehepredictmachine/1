"""Backfill of ML samples from history (MT5 history, CSV export or the synthetic simulator).

Same logic as live: at every close of `step_tf` only bars whose availability time <= t are visible, the same
scanner / tracker / FeatureEngine create samples at the first CONFIRMED of every setup version, and the same
labeller (MQ-LABEL-1.0.0) labels them from M1 bars that follow. Differences to live, stated in every sample:
* no recorded quotes -> a bar touching SL and TP is AMBIGUOUS (never assumed);
* spread from the bar's spread field (or the cost model), not from the live quote;
therefore quality = 'APPROX' and source = 'BACKFILL_<feed>'. APPROX samples are excluded from training unless
ml.use_backfill_approx is switched on; synthetic and real samples are never mixed.
"""
from __future__ import annotations

import bisect
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import AppConfig
from ..db.database import Database
from ..strategies import adapter, registry
from ..strategies.tracker import SetupTracker
from . import labels as lb
from .dataset import SampleStore

UTC = timezone.utc
TFS = ("M1", "M5", "M15", "H1", "H4", "D1")


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def run(target_db, data: dict, *, feed: str, synthetic: bool, cost: dict, step_tf: str = "M15", warmup_days: int = 30,
        max_steps: int | None = None, progress=None, should_stop=None) -> dict:
    """`data[tf]` = list of closed bars {"open_utc","o","h","l","c","tv","available_at","spread_points"} in time order."""
    store = SampleStore(target_db)
    tmp = Path(tempfile.mkdtemp(prefix="mq_backfill_"))
    work = Database(tmp / "bf.sqlite")                 # tracker state of the replay is private (never mixes with live setups)
    tr = SetupTracker(work)
    cfg = AppConfig().active
    steps = [_p(b["available_at"]) for b in data.get(step_tf) or []]
    steps = [t for t in steps if steps and t >= steps[0] + timedelta(days=warmup_days)]
    if max_steps:
        steps = steps[:max_steps]
    ptr = {tf: 0 for tf in TFS}
    m1 = data.get("M1") or []
    m1_t = [_p(b["open_utc"]) for b in m1]
    created = 0
    t0 = time.time()
    for k, t in enumerate(steps):
        if should_stop and should_stop():
            break
        for tf in TFS:
            rows = data.get(tf) or []
            while ptr[tf] < len(rows) and _p(rows[ptr[tf]]["available_at"]) <= t:
                ptr[tf] += 1
        bars = {tf: data[tf][max(0, ptr[tf] - 400):ptr[tf]] for tf in TFS if ptr[tf] > 0}
        last = bars.get("M1") or bars.get("M5")
        if not last:
            continue
        spread = (last[-1].get("spread_points") or 0) * cost["point"] or cost["spread"]
        view = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last[-1]["c"], ask=last[-1]["c"] + spread, point=cost["point"], as_of=_iso(t),
                                  synthetic=synthetic, regime_params=cfg.regime)
        res = registry.scan(view, enabled={}, overrides={}, thresholds=cfg.thresholds.model_dump(), account_key="backfill")
        events = tr.update(res["candidates"], view=view, symbol="XAUUSD-", account_key="backfill", data_ok=True, new_data=True, now=t, cfg=cfg,
                           scanned=set(registry.STRATEGIES))
        for kind, r in events:
            if kind not in ("NEW_CONFIRMED", "STAGE_CONFIRMED") or not r:
                continue
            sid = f"BF-{feed}-{r['setup_id']}"
            c = dict(cost, spread=spread)
            if store.create(rec=dict(r["record"], symbol="XAUUSD-"), setup_id=sid, version=int(r["version"]), view=view, asof=t,
                            source=f"BACKFILL_{feed}", quality="APPROX", feed_id=f"BACKFILL:{feed}", cost=c, synthetic=synthetic):
                created += 1
        if progress and k % 200 == 0:
            progress({"step": k, "steps": len(steps), "created": created})
    # label everything created by this backfill with the M1 bars that follow (no quotes -> AMBIGUOUS when SL&TP share a bar)
    labeled = {}
    now = (m1_t[-1] + timedelta(minutes=1)) if m1_t else datetime.now(UTC)
    for s in target_db.query("SELECT sample_id, asof_utc, entry_json FROM ml_samples WHERE status='PENDING' AND source=?", (f"BACKFILL_{feed}",)):
        i = bisect.bisect_left(m1_t, _p(s["asof_utc"]))
        st = store.advance(s["sample_id"], s["entry_json"], m1[i:i + 6000], [], now, outcome_source="BACKFILL_M1_OHLC")
        labeled[st] = labeled.get(st, 0) + 1
    work.close()
    return {"feed": feed, "steps": len(steps), "created": created, "labels": labeled, "elapsed_s": round(time.time() - t0, 1),
            "quality": "APPROX", "label_policy_version": lb.LABEL_POLICY_VERSION}


def synthetic_data(days: int, seed: int = 7) -> dict:
    from ..mt5 import fake as F
    from ..strategies.base import TF_SECONDS
    fk = F.FakeMT5(seed=seed)
    off = fk.offset
    raw_now = int(fk._raw_now()) // 3600 * 3600
    codes = {"M1": F.TIMEFRAME_M1, "M5": F.TIMEFRAME_M5, "M15": F.TIMEFRAME_M15, "H1": F.TIMEFRAME_H1, "H4": F.TIMEFRAME_H4, "D1": F.TIMEFRAME_D1}
    start = raw_now - days * 86400
    out = {}
    for tf, code in codes.items():
        rows = []
        for x in fk._rates(code, raw_now):
            t = int(x["time"])
            if t < start:
                continue
            op = datetime.fromtimestamp(t - off, UTC)
            rows.append({"open_utc": _iso(op), "o": float(x["open"]), "h": float(x["high"]), "l": float(x["low"]), "c": float(x["close"]),
                         "tv": int(x["tick_volume"]), "available_at": _iso(op + timedelta(seconds=TF_SECONDS[tf])), "spread_points": 12, "closed": True})
        out[tf] = rows[:-1]
    return out


def bridge_data(bridge, counts: dict | None = None) -> dict:
    """History from the connected terminal (same bars the live app uses), converted to UTC with the verified offset."""
    from ..strategies.base import TF_SECONDS
    counts = counts or {"M1": 60000, "M5": 15000, "M15": 6000, "H1": 2500, "H4": 800, "D1": 400}
    off = bridge.clock.offset
    if off is None:
        raise RuntimeError("SERVER_TIME_OFFSET_UNKNOWN")
    out = {}
    for tf, n in counts.items():
        bars = bridge._fetch(bridge.cfg.symbol, tf, n)
        rows = []
        for b in bars[:-1]:                                  # the last bar may still be forming
            op = datetime.fromtimestamp(b.t_raw - off, UTC)
            rows.append({"open_utc": _iso(op), "o": b.o, "h": b.h, "l": b.l, "c": b.c, "tv": b.tv,
                         "available_at": _iso(op + timedelta(seconds=TF_SECONDS[tf])), "spread_points": b.spread, "closed": True})
        out[tf] = rows
    return out
