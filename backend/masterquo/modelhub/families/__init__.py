"""1.33 model families (PMW-FAM-1). The registry is the single source for the catalog, the Training Center, the docs generator and the
runtime - no separate lists."""
from __future__ import annotations

_ORDER = ("TS_ARIMA", "TS_SARIMAX", "VOL_GARCH", "MICROSTRUCTURE", "PAIR_COINT", "STATARB", "KALMAN_LS", "BREAKOUT", "TH_RF", "TH_XGB",
          "TH_SVM", "SEQ_LSTM", "SEQ_GRU", "RL_PPO", "NLP_SENTIMENT")
ADAPTERS = ("SEQ_GRU_EVENT",)


def registry() -> dict:
    from . import arima, breakout, garch, kalman_ls, micro, nlp, pairs, rl, seq, tabular
    objs = [arima.ARIMA(), arima.SARIMAX(), garch.GARCH(), micro.Micro(), pairs.PairCoint(), pairs.StatArb(), kalman_ls.KalmanLS(),
            breakout.Breakout(), tabular.RF(), tabular.XGB(), tabular.SVM(), seq.LSTM(), seq.GRU(), rl.PPO(), nlp.NLP(), seq.EventGRU()]
    return {o.ID: o for o in objs}


def ids() -> tuple[str, ...]:
    return _ORDER
