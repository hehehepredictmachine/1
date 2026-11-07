"""PAIR_COINT and STATARB - relations of explicitly configured series (never an assumed XAUUSD-BTC pair).

PAIR_COINT: two aligned series (same closed-bar times, no forward fill). Engle-Granger cointegration test (statsmodels coint) on train;
spread s_t = log A_t - alpha - beta log B_t with alpha / beta from train OLS; z = (s - mean_train) / std_train; half-life from AR(1) of
the spread (only when 0 < phi < 1). The relation is rejected (NO_VALID_PAIR) when the test p-value > p_max on train or the validation
residual is unstable (std ratio val/train > 2). A p-value is not a probability of profit or of mean reversion.
Leg conversion: beta is a ratio of LOG prices; the lots of leg B for 1 lot of A are beta x (price_A x contract_A) / (price_B x contract_B),
rounded to the broker volume step - never "beta = number of lots".
STATARB: basket of >= 3 configured series: PCA factors fitted on train returns, residual = return - factor projection, cumulative residual
s-score per asset; weights = -s-score normalised to gross 1 with a net-exposure check. Without the universe -> NOT_CONFIGURED.
Both are analytical: a proposed basket goes through the existing risk / gateway (all legs costed) - nothing is sent from here.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import base as B


def align(a: list[dict], b: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ma = {x["t"]: x["c"] for x in a}
    mb = {x["t"]: x["c"] for x in b}
    ts = np.asarray(sorted(set(ma) & set(mb)))
    return ts, np.asarray([ma[t] for t in ts], dtype=float), np.asarray([mb[t] for t in ts], dtype=float)


def ols(x, y):
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[0]), float(coef[1])


def half_life(s: np.ndarray) -> float | None:
    if len(s) < 30:
        return None
    a, phi = ols(s[:-1], s[1:])
    return float(-math.log(2) / math.log(phi)) if 0 < phi < 1 else None


def legs_volume(beta: float, price_a: float, price_b: float, contract_a: float, contract_b: float, lots_a: float = 1.0, step: float = 0.01) -> float:
    raw = abs(beta) * lots_a * price_a * contract_a / (price_b * contract_b)
    return round(round(raw / step) * step, 8)


class PairCoint(B.Family):
    ID = "PAIR_COINT"
    NAME = "Kointegracja pary + z-score (Engle-Granger)"
    KIND = "TRAINED"
    FIT_LABEL = "estymacja relacji + test założeń"
    TASK_TYPE = "PAIR_RELATION"
    UNIT = "z_score"
    TASK = "PAIR_SPREAD_Z"
    DEPS = ("statsmodels",)
    TF = "H1"
    RECEIVERS = ("PANEL:pair_relation", "AGENT:context", "PORTFOLIO:basket_proposal (via risk/gateway)")
    DATA = {"kind": "MULTI_SERIES", "tf": "H1", "min_bars": 500, "config": "families.pairs = [[symbolA, symbolB]]"}
    P_MAX = 0.05

    def validate_data(self, data):
        if not data.get("pair"):
            return False, "PAIR_NOT_CONFIGURED: brak skonfigurowanej pary (nie zakładam automatycznie XAUUSD–BTC)"
        ts, a, b = align(*data["pair_bars"])
        if len(ts) < self.DATA["min_bars"]:
            return False, f"za mało wspólnych świec: {len(ts)}"
        return True, None

    def fit(self, data, cfg, tmp, budget):
        from statsmodels.tsa.stattools import coint
        ts, a, b = align(*data["pair_bars"])
        la, lb = np.log(a), np.log(b)
        n = len(ts)
        tr, va = int(n * 0.6), int(n * 0.8)
        stat, p, _ = coint(la[:tr], lb[:tr])
        alpha, beta = ols(lb[:tr], la[:tr])
        s = la - alpha - beta * lb
        mu, sd = float(s[:tr].mean()), float(s[:tr].std())
        ratio = float(s[tr:va].std() / sd) if sd > 0 else float("inf")
        hl = half_life(s[:tr])
        corr = float(np.corrcoef(np.diff(la[:tr]), np.diff(lb[:tr]))[0, 1])
        art = {"pair": list(data["pair"]), "alpha": alpha, "beta": beta, "mu": mu, "sd": sd, "half_life_bars": hl, "p_value_train": float(p)}
        (tmp / "pair.json").write_text(json.dumps(art), encoding="utf-8")
        vm = {"p_value_train": float(p), "val_std_ratio": ratio, "sd_train": sd}
        val = self.promotion(vm, {"p_value_train": ("<", self.P_MAX), "val_std_ratio": ("<", 2.0), "sd_train": (">", 1e-9)})
        return {"metrics": {**vm, "eg_stat": float(stat), "return_correlation_train": corr, "half_life_bars": hl,
                            "note": "korelacja ≠ kointegracja; p-value nie jest prawdopodobieństwem zysku"},
                "validation": val, "sample": {"expected": {"z_last": (float(s[-1]) - mu) / sd if sd > 0 else None}, "tolerance": 1e-9}}

    def load(self, d):
        return json.loads((d / "pair.json").read_text(encoding="utf-8"))

    def predict(self, art, live):
        if not live.get("pair_bars"):
            raise B.Unavailable("BLOCKED_DATA", "brak danych jednej z nóg pary")
        ts, a, b = align(*live["pair_bars"])
        if len(ts) < 2:
            raise B.Unavailable("BLOCKED_DATA", "brak wspólnych świec obu nóg")
        if art["sd"] <= 1e-12:
            raise B.Unavailable("BLOCKED_DATA", "zerowa wariancja spreadu")
        s = math.log(a[-1]) - art["alpha"] - art["beta"] * math.log(b[-1])
        return {"z": (s - art["mu"]) / art["sd"], "spread": s, "hedge_ratio_log": art["beta"], "half_life_bars": art["half_life_bars"],
                "p_value_train": art["p_value_train"], "last_common_time": int(ts[-1])}


class StatArb(B.Family):
    ID = "STATARB"
    NAME = "Arbitraż statystyczny – koszyk PCA + reszty (s-score)"
    KIND = "TRAINED"
    FIT_LABEL = "estymacja czynników + walidacja reszt"
    TASK_TYPE = "PAIR_RELATION"
    UNIT = "z_score"
    TASK = "BASKET_RESIDUAL_S"
    DEPS = ("sklearn",)
    TF = "H1"
    RECEIVERS = ("PANEL:basket", "PORTFOLIO:basket_proposal (via risk/gateway)")
    DATA = {"kind": "MULTI_SERIES", "tf": "H1", "min_bars": 500, "min_assets": 3, "config": "families.basket = [s1, s2, s3, ...]"}

    def validate_data(self, data):
        uni = data.get("basket") or []
        if len(uni) < 3:
            return False, f"NOT_CONFIGURED: koszyk wymaga >= 3 skonfigurowanych serii (jest {len(uni)}) – lista instrumentów nie jest rozszerzana automatycznie"
        return True, None

    @staticmethod
    def matrix(series: list[list[dict]]):
        common = set(x["t"] for x in series[0])
        for s in series[1:]:
            common &= set(x["t"] for x in s)
        ts = np.asarray(sorted(common))
        P = np.column_stack([np.asarray([dict((x["t"], x["c"]) for x in s)[t] for t in ts], dtype=float) for s in series])
        return ts, np.diff(np.log(P), axis=0)

    def fit(self, data, cfg, tmp, budget):
        from sklearn.decomposition import PCA
        ts, R = self.matrix(data["basket_bars"])
        n = len(R)
        tr, va = int(n * 0.6), int(n * 0.8)
        mu, sd = R[:tr].mean(0), R[:tr].std(0) + 1e-12
        Z = (R - mu) / sd
        k = max(1, min(2, R.shape[1] - 1))
        pca = PCA(n_components=k).fit(Z[:tr])
        res = Z - pca.inverse_transform(pca.transform(Z))
        cum = np.cumsum(res, axis=0)
        win = 60
        st_tr = np.std(np.diff(cum[:tr], axis=0), axis=0)
        st_va = np.std(np.diff(cum[tr:va], axis=0), axis=0)
        ratio = float(np.max(st_va / np.maximum(st_tr, 1e-12)))
        art = {"basket": list(data["basket"]), "mu": mu.tolist(), "sd": sd.tolist(), "components": pca.components_.tolist(), "mean_": pca.mean_.tolist(),
               "window": win}
        (tmp / "statarb.json").write_text(json.dumps(art), encoding="utf-8")
        vm = {"val_residual_std_ratio": ratio, "explained_var": float(pca.explained_variance_ratio_.sum())}
        return {"metrics": vm, "validation": self.promotion(vm, {"val_residual_std_ratio": ("<", 2.0)}), "sample": {"expected": None, "tolerance": 0.0}}

    def load(self, d):
        return json.loads((d / "statarb.json").read_text(encoding="utf-8"))

    def predict(self, art, live):
        if not live.get("basket_bars") or len(live["basket_bars"]) != len(art["basket"]):
            raise B.Unavailable("BLOCKED_DATA", "brak danych którejś nogi koszyka")
        ts, R = self.matrix(live["basket_bars"])
        if len(R) < art["window"]:
            raise B.Unavailable("BLOCKED_DATA", "za mało wspólnych świec koszyka")
        Z = (R - np.asarray(art["mu"])) / np.asarray(art["sd"])
        C, m = np.asarray(art["components"]), np.asarray(art["mean_"])
        res = Z - ((Z - m) @ C.T @ C + m)
        cum = np.cumsum(res[-art["window"]:], axis=0)
        s = (cum[-1] - cum.mean(0)) / (cum.std(0) + 1e-12)
        w = -s / (np.abs(s).sum() or 1.0)
        return {"s_scores": [float(x) for x in s], "weights": [float(x) for x in w], "gross": float(np.abs(w).sum()), "net": float(w.sum()),
                "assets": art["basket"], "neutrality": "wagi w jednostkach ryzyka (zwroty standaryzowane) – neutralność nominalna wymaga przeliczenia nóg"}
