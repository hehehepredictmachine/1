"""Datasets, labels and chronological splits (PMW-TH-DATA-1).

Label (task DIRECTION_H): the class of the move of the base-TF close over the next H candles AFTER COSTS -
  UP if close[i+H] - close[i] >  thr_i, DOWN if < -thr_i, FLAT otherwise,  thr_i = max(k_atr x ATR14_i, cost_i),
  cost_i = recorded bar spread x point + round-trip commission (price units) + slippage assumption (price units).
The label of row i is known only at the close of candle i+H (`label_end`). A label window that crosses a session gap (more than
1.5 x H candles of wall time) is dropped - the move over a weekend is not the move the model is asked about.

Splits: rows sorted by time; the FINAL TEST (holdout) is the last `holdout_frac` of rows and is not touched until the final
evaluation; between the development part and the holdout there is an embargo (no development row whose label ends within
`embargo_bars` of the holdout start). Development = purged walk-forward (expanding window): fold k trains only on rows whose label
ended before the test block starts minus the embargo. Preprocessing, hyper-parameters, calibration and decision thresholds are
fitted on development rows only.
"""
from __future__ import annotations

import hashlib
import io
import json
import math

import numpy as np

from . import features as F

LABEL_VERSION = "PMW-TH-LABEL-1"
CLASSES = ("DOWN", "FLAT", "UP")


class InsufficientData(ValueError):
    pass


def positive(x) -> float | None:
    """A finite number > 0, else None (missing is never replaced by a default)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def epoch(x, name: str = "data") -> float | None:
    """1.46: range bounds (--from / --to, job params) arrive as ISO text; Store.read compares them with int epoch seconds (1.45.0: TypeError
    'int >= str' -> traceback / FAILED job). Same conversion as the export (export._ts); a bad format is a readable ValueError."""
    from ..marketdata.export import _ts
    try:
        return _ts(x)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name}: nieprawidłowa data {x!r} – oczekiwany format ISO, np. 2026-01-31 albo 2026-01-31T00:00:00Z") from exc


def symbol_point(man: dict | None, cfg: dict | None = None) -> float | None:
    """Price point of the symbol: measured (store manifest: costs.spread / symbol_spec) or given explicitly (cfg['point']); None if unknown."""
    man = man or {}
    return (positive(((man.get("costs") or {}).get("spread") or {}).get("point")) or positive((man.get("symbol_spec") or {}).get("point"))
            or positive((cfg or {}).get("point")))


def labels(cols: dict, tf: str, horizon: int, k_atr: float, point: float, commission_price: float, slippage_price: float):
    t = np.asarray(cols["time"], dtype=np.int64)
    c = np.asarray(cols["close"], dtype=float)
    h, lo = np.asarray(cols["high"], dtype=float), np.asarray(cols["low"], dtype=float)
    sp = np.asarray(cols.get("spread") or [0] * len(c), dtype=float)
    n = len(c)
    y = np.full(n, -1, dtype=np.int64)
    end = np.full(n, -1, dtype=np.int64)
    fwd = np.full(n, np.nan)
    cost = sp * point + commission_price + slippage_price
    atr = F._atr(h, lo, c)
    step = F.TF_S[tf]
    for i in range(n - horizon):
        if t[i + horizon] - t[i] > 1.5 * horizon * step or np.isnan(atr[i]):
            continue
        d = c[i + horizon] - c[i]
        thr = max(k_atr * atr[i], cost[i])
        y[i] = 2 if d > thr else 0 if d < -thr else 1
        end[i] = t[i + horizon] + step
        fwd[i] = d
    return y, end, fwd, cost, atr


def build(store, inst: str, cfg: dict, start=None, end=None) -> dict:
    """Feature matrix + labels for one instrument / base TF from the candle store (closed candles only)."""
    tf = cfg["base_tf"]
    need = (tf,) + F.HTF_OF[tf]
    start, end = epoch(start, "początek zakresu (--from / start)"), epoch(end, "koniec zakresu (--to / end)")   # 1.46: ISO -> epoch s
    cols = {x: store.read(inst, x, start, end) for x in need}
    man = store.manifest(inst)
    # 1.46: an unknown point (manifest written after a failed symbol_info) was silently 0.01 - the spread cost of the labels and the
    # spread_atr feature in the wrong scale (10x for a 3-digit XAUUSD) and different from inference (real point). Never guessed now.
    point = symbol_point(man, cfg)
    if not cols[tf]["time"]:
        raise InsufficientData(f"brak świec {inst} {tf} w magazynie – najpierw „Eksportuj dane”")
    if point is None:
        raise InsufficientData(f"brak specyfikacji symbolu {inst} (point) w manifeście magazynu – ponów „Eksportuj dane” przy połączonym MT5 "
                               "(albo podaj point jawnie); bez niej koszt spreadu i cecha spread_atr byłyby w nieznanej skali")
    t, X, names = F.build(cols, tf, point)
    y, lend, fwd, cost, atr = labels(cols[tf], tf, int(cfg["horizon"]), float(cfg["k_atr"]), point, float(cfg.get("commission_price") or 0.0),
                                     float(cfg.get("slippage_price") or 0.0))
    fin = np.all(np.isfinite(X), axis=1)
    # 1.46: rows whose higher-TF candle is frozen (HTF history ends / has a hole while the base TF traded on) are not usable - 1.45.0
    # trained on finite but weeks-old M15/M30 values (features.htf_stale; a weekend / session break is not stale)
    stale = F.htf_stale(cols, tf)
    ok = (y >= 0) & fin & ~stale
    files = {k: v for k, v in (man.get("files") or {}).items() if k.split("/")[0] in need}
    ds = {"t": t[ok], "X": X[ok], "y": y[ok], "label_end": lend[ok], "fwd": fwd[ok], "cost": cost[ok], "atr": atr[ok], "names": names,
          "point": point, "rows_total": int(len(t)), "rows_usable": int(ok.sum()),
          "dropped": {"warmup_or_missing_htf": int(((y >= 0) & ~fin).sum()), "no_label": int((y < 0).sum()),
                      "stale_htf": int(((y >= 0) & fin & stale).sum())},
          "source_files": files, "data_kind": man.get("data_kind"), "symbol": man.get("symbol"), "time_model": man.get("time_model")}
    ds["hash"] = hashlib.sha256(json.dumps(sorted((k, v.get("sha256")) for k, v in files.items())).encode()
                                + ds["t"].tobytes() + ds["y"].tobytes()).hexdigest()[:16]
    return ds


def save(ds: dict, path) -> dict:
    """Dataset file (npz) + JSON description - the 'Przygotuj dataset' result, also exportable."""
    from ..marketdata.store import atomic_bytes, atomic_json, iso, sha256_file
    buf = io.BytesIO()
    np.savez_compressed(buf, t=ds["t"], X=ds["X"], y=ds["y"], label_end=ds["label_end"], fwd=ds["fwd"], cost=ds["cost"], atr=ds["atr"])
    atomic_bytes(path / "dataset.npz", buf.getvalue())
    desc = {k: ds[k] for k in ("names", "point", "rows_total", "rows_usable", "dropped", "source_files", "data_kind", "symbol", "time_model", "hash")}
    desc.update(feature_schema=F.FEATURE_SCHEMA, label_version=LABEL_VERSION, classes=CLASSES,
                range_utc=[iso(int(ds["t"][0])) if len(ds["t"]) else None, iso(int(ds["t"][-1])) if len(ds["t"]) else None],
                class_counts={c: int((ds["y"] == i).sum()) for i, c in enumerate(CLASSES)}, sha256=sha256_file(path / "dataset.npz"))
    atomic_json(path / "dataset.json", desc)
    return desc


def splits(ds: dict, *, holdout_frac: float, n_folds: int, embargo_bars: int, step: int, min_samples: int, min_train: int) -> dict:
    n = len(ds["y"])
    if n < min_samples:
        raise InsufficientData(f"za mało danych: {n} próbek z etykietą < wymagane {min_samples} – wyeksportuj dłuższą historię "
                               f"(≈ {int(min_samples * step / 86400 * 1.4) + 1} dni kalendarzowych dla tego interwału)")
    t, lend = ds["t"], ds["label_end"]
    # 1.46: holdout_frac outside (0, 1) gave h0 = n (IndexError in t[h0]) or a negative index (absurd split); checked before indexing
    if not 0.0 < float(holdout_frac) < 1.0 or int(n_folds) < 1:
        raise ValueError(f"holdout_frac {holdout_frac} (0..1) / n_folds {n_folds} (>= 1) poza zakresem")
    h0 = int(n * (1 - holdout_frac))
    hold = np.arange(h0, n)
    if len(hold) < 200:
        raise InsufficientData(f"zbiór końcowy ma {len(hold)} próbek (< 200) – za krótka historia")
    hold_start = t[h0]
    emb = embargo_bars * step
    dev = np.where(lend <= hold_start - emb)[0]
    blocks = np.array_split(dev, n_folds + 1)
    folds = []
    for k in range(1, n_folds + 1):
        test = blocks[k]
        if not len(test):
            continue
        ts0 = t[test[0]]
        tr = dev[(lend[dev] <= ts0 - emb) & (t[dev] < ts0)]          # purge: label must end before the test block (minus embargo)
        if len(tr) < min_train:
            continue
        folds.append({"train": tr, "test": test})
    if len(folds) < 2:
        raise InsufficientData(f"za mało danych na walidację walk-forward ({len(folds)} foldów z >= {min_train} próbek treningowych)")
    return {"dev": dev, "holdout": hold, "folds": folds, "holdout_start": int(hold_start), "embargo_s": emb}
