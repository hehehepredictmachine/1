"""MICROSTRUCTURE - quote / order-book measurements + an optional short-term reaction classifier.

Capability levels (from what the broker actually delivers): QUOTE_ONLY (bid/ask stream), TRADES (time & sales - not provided by MT5 for
OTC XAUUSD), L2_BOOK (market_book_* depth). Measurements come from indicators/ofi.py (best / depth imbalance, OFI, microprice) and
work without any training. Data come from the IndicatorService book archive (book_snapshots); there is no historical DOM from OHLC.
Optional classifier: logistic regression of the sign of the mid change over the next `h_s` seconds on [best_imbalance,
depth_imbalance, ofi_window, microprice deviation / spread], fitted chronologically with a calibration block, ONLY when the archive
has >= MIN_SNAPSHOTS consecutive snapshots; otherwise BLOCKED_DATA with the required count (the collector keeps running).
DOM of the XAUUSD broker is that broker's quote book, not the global gold market.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import base as B

MIN_SNAPSHOTS = 5000


def features_from_books(books: list[dict], horizon_s: float = 10.0, max_gap_s: float = 5.0):
    from ...indicators import ofi as OF
    X, y, ts = [], [], []
    acc = OF.OFIAccumulator(max_gap_s=max_gap_s, window_s=30.0)
    mids = [((b["bids"][0][0] + b["asks"][0][0]) / 2, b["t"]) for b in books]
    j = 0
    for i, b in enumerate(books):
        acc.add(b)
        while j < len(books) and books[j]["t"] < b["t"] + horizon_s:
            j += 1
        if j >= len(books) or books[j]["t"] - b["t"] > horizon_s + max_gap_s:
            continue
        bi = OF.best_imbalance(b)
        di = OF.depth_imbalance(b, 5)
        mp, mid = OF.microprice(b)
        spr = b["asks"][0][0] - b["bids"][0][0]
        if bi is None or mp is None or spr <= 0:
            continue
        v = acc.view()
        X.append([bi, di if di is not None else 0.0, v["ofi_window"] or 0.0, (mp - mid) / spr])
        d = mids[j][0] - mid
        y.append(0 if d < 0 else 2 if d > 0 else 1)
        ts.append(b["t"])
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int), np.asarray(ts)


class Micro(B.Family):
    ID = "MICROSTRUCTURE"
    NAME = "Mikrostruktura – arkusz brokera (imbalance, OFI, microprice) + klasyfikator reakcji"
    KIND = "MEASUREMENT"
    FIT_LABEL = "trening klasyfikatora reakcji (opcjonalny)"
    TASK_TYPE = "MICROSTRUCTURE"
    UNIT = "mixed"
    TASK = "BOOK_STATE_AND_REACTION_10S"
    DEPS = ("sklearn",)
    TF = None
    HORIZONS = ()
    RECEIVERS = ("SH_CONTEXT:entry_quality", "RISK:execution_conditions", "PANEL:microstructure")
    DATA = {"kind": "L2_BOOK", "source": "IndicatorService.book_snapshots (market_book_get)", "min_snapshots": MIN_SNAPSHOTS}

    def validate_data(self, data):
        books = data.get("books") or []
        if len(books) < MIN_SNAPSHOTS:
            return False, f"za mało snapshotów arkusza: {len(books)} < {MIN_SNAPSHOTS} (kolektor działa – trening po zebraniu danych)"
        return True, None

    def fit(self, data, cfg, tmp, budget):
        from sklearn.linear_model import LogisticRegression
        X, y, ts = features_from_books(data["books"])
        if len(y) < 1000:
            raise B.Unavailable("BLOCKED_DATA", f"za mało ciągłych próbek po filtrze luk: {len(y)}")
        n = len(y)
        a, b = int(n * 0.6), int(n * 0.8)
        m = LogisticRegression(max_iter=500).fit(X[:a], y[:a])
        from ...trainhub.learn import Prior, logloss, proba3
        pv = proba3(m, X[a:b])
        base = Prior().fit(X[:a], y[:a]).predict_proba(X[a:b])
        val = {"val_log_loss": logloss(pv, y[a:b]), "val_baseline_log_loss": logloss(base, y[a:b])}
        m = LogisticRegression(max_iter=500).fit(X[:b], y[:b])
        ph = proba3(m, X[b:])
        hold = {"log_loss": logloss(ph, y[b:]), "baseline_log_loss": logloss(Prior().fit(X[:b], y[:b]).predict_proba(X[b:]), y[b:]), "n": int(n - b)}
        art = {"coef": m.coef_.tolist(), "intercept": m.intercept_.tolist(), "classes": m.classes_.tolist(), "horizon_s": 10.0}
        (tmp / "micro.json").write_text(json.dumps(art), encoding="utf-8")
        vm = {"val_skill": 1 - val["val_log_loss"] / val["val_baseline_log_loss"] if val["val_baseline_log_loss"] else None}
        return {"metrics": {**val, "holdout": hold, "features": ["best_imbalance", "depth_imbalance", "ofi_window", "microprice_dev/spread"]},
                "validation": self.promotion(vm, {"val_skill": (">", 0.0)}),
                "sample": {"X": X[-20:].tolist(), "expected": self._proba(art, X[-20:]).tolist(), "tolerance": 1e-9}}

    def load(self, d):
        return json.loads((d / "micro.json").read_text(encoding="utf-8"))

    @staticmethod
    def _proba(art, X):
        z = X @ np.asarray(art["coef"]).T + np.asarray(art["intercept"])
        if z.shape[1] == 1:                                         # binary logistic regression: one logit for classes_[1]
            p1 = 1 / (1 + np.exp(-z[:, 0]))
            p = np.column_stack([1 - p1, p1])
        else:
            z = z - z.max(axis=1, keepdims=True)
            e = np.exp(z)
            p = e / e.sum(axis=1, keepdims=True)
        out = np.full((len(X), 3), 1e-9)
        for j, c in enumerate(art["classes"]):
            out[:, int(c)] = p[:, j]
        return out / out.sum(axis=1, keepdims=True)

    def measure(self, ind_result: dict | None) -> dict:
        """Measurements without a model (always available when the book is)."""
        if not ind_result or ind_result.get("status") != "READY":
            reason = (ind_result or {}).get("reason") or "Brak danych arkusza"
            raise B.Unavailable("BLOCKED_DATA", reason)
        v = ind_result["values"]
        lvl = "L2_BOOK" if (v.get("bid_levels") or 0) > 1 else "QUOTE_ONLY"
        return {"capability": lvl, "best_imbalance": v.get("best_imbalance"), "depth_imbalance": v.get("depth_imbalance"),
                "ofi_window": v.get("ofi_window"), "microprice_dev": v.get("microprice_dev"), "mid": v.get("mid"),
                "ofi_mode": ((ind_result.get("ofi_state") or {}).get("mode"))}

    def predict(self, art, live):
        m = self.measure(live.get("micro"))
        if art is not None:
            v = live["micro"]["values"]
            spr = live.get("spread")
            if not spr or spr <= 0:
                raise B.Unavailable("BLOCKED_DATA", "brak spreadu kwotowania do normalizacji microprice")
            x = np.asarray([[v.get("best_imbalance") or 0.0, v.get("depth_imbalance") or 0.0, v.get("ofi_window") or 0.0,
                             (v.get("microprice_dev") or 0.0) / spr]])
            p = self._proba(art, x)[0]
            m.update(p_down_10s=float(p[0]), p_flat_10s=float(p[1]), p_up_10s=float(p[2]))
        return m
