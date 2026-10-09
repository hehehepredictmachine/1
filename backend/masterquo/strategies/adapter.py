"""Data adapter: bridge bars (live) or replay bars -> MarketView (+ regime). Same code for both."""
from __future__ import annotations

from . import regime as regime_mod
from .base import MarketView, TFView


def build_view(*, symbol: str, bars_by_tf: dict[str, list[dict]], bid: float | None, ask: float | None, point: float | None,
               as_of: str, synthetic: bool, regime_params: dict | None = None, data_status: str = "OK",
               max_bars: int = 400) -> MarketView:
    tfs = {tf: TFView(tf, bars[-max_bars:]) for tf, bars in bars_by_tf.items() if bars}
    view = MarketView(symbol=symbol, as_of=as_of, tfs=tfs, bid=bid, ask=ask, point=point, synthetic=synthetic)
    view.regime = regime_mod.evaluate(view, regime_params, data_status)
    return view
