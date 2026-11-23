"""Public Hyperliquid Info API adapter (CRYPTO_FOMO_PERPS data provider). FOMO (fomo.family) perps use Hyperliquid and Trade[XYZ]
markets; this adapter reads PUBLIC market data only (POST https://api.hyperliquid.xyz/info) - it is NOT access to a FOMO account,
it signs nothing, sends no orders and moves no funds.

Requests used (official Info endpoint): perpDexs, meta (core / dex="xyz"), metaAndAssetCtxs (mark / oracle / funding / OI),
candleSnapshot (closed candles with real base volume "v"), l2Book (top levels), recentTrades (side "B" = aggressive buy, "A" = sell).
Instrument identity: core coins by name ("BTC"); Trade[XYZ] markets keep their native "xyz:NAME" - never an invented "...USDT".
Capabilities are declared; a failed request is a visible error state, never zeros.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

URL = "https://api.hyperliquid.xyz/info"
TF = {"M1": "1m", "M3": "3m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D1": "1d"}
TF_S = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
CAPABILITIES = {"history": True, "closed_bar": True, "bid_ask": "L2_TOP", "mark_oracle": True, "real_volume": True, "tick_activity": False,
                "trades_aggressor": True, "l2_orderbook": True, "open_interest": True, "funding": True, "payout": False, "expiry": False,
                "account_state": False, "orders": False, "settlement": False}


class HLError(Exception):
    pass


class Hyperliquid:
    def __init__(self, timeout: float = 10.0, min_interval: float = 0.25):
        self.timeout, self.min_interval = timeout, min_interval
        self._lock = threading.Lock()
        self._last = 0.0
        self.errors = 0
        self.last_error: str | None = None
        self._meta: dict = {}
        self._meta_at = 0.0

    def post(self, body: dict):
        with self._lock:                                                     # respect the public rate limit (one request at a time, spaced)
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "PMW-public-data"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            raise HLError(self.last_error) from exc

    # ------------------------------------------------------------------ catalog
    def catalog(self, max_age: float = 3600) -> dict:
        """{native_id: {name, dex, szDecimals, maxLeverage, delisted, namespace}} for core + every perp dex (Trade[XYZ] = 'xyz')."""
        if self._meta and time.time() - self._meta_at < max_age:
            return self._meta
        out = {}
        dexs = [None] + [d["name"] for d in (self.post({"type": "perpDexs"}) or []) if d]
        for dex in dexs:
            body = {"type": "meta"} | ({"dex": dex} if dex else {})
            for u in (self.post(body) or {}).get("universe", []):
                out[u["name"]] = {"native_id": u["name"], "dex": dex or "core", "szDecimals": int(u["szDecimals"]), "maxLeverage": u.get("maxLeverage"),
                                  "delisted": bool(u.get("isDelisted")), "namespace": "Trade[XYZ]" if dex == "xyz" else ("Hyperliquid core" if not dex else dex),
                                  "underlying_asset_class": "CRYPTO" if not dex else "MULTI_ASSET (wg rynku dex)"}
        self._meta, self._meta_at = out, time.time()
        return out

    def contexts(self, dex: str | None = None) -> dict:
        """mark / oracle / mid / funding (hourly rate, as published) / OI (contracts) / prevDayPx / day volume per coin."""
        d = self.post({"type": "metaAndAssetCtxs"} | ({"dex": dex} if dex else {}))
        uni, ctxs = d[0]["universe"], d[1]
        now = time.time()
        out = {}
        for u, c in zip(uni, ctxs):
            f = lambda k: (float(c[k]) if c.get(k) not in (None, "") else None)  # noqa: E731
            out[u["name"]] = {"mark": f("markPx"), "oracle": f("oraclePx"), "mid": f("midPx"), "funding_rate": f("funding"), "funding_period": "1h",
                              "open_interest": f("openInterest"), "oi_unit": "contracts (base units)", "prev_day_px": f("prevDayPx"),
                              "day_notional_volume": f("dayNtlVlm"), "at": now}
        return out

    # ------------------------------------------------------------------ market data
    def candles(self, coin: str, tf: str, n: int = 500) -> list[dict]:
        """CLOSED candles oldest-first {t (open, s), o, h, l, c, v (base volume), trades}; the forming candle is dropped."""
        if tf not in TF:
            raise HLError(f"interwał {tf} nieobsługiwany przez Hyperliquid")
        now_ms = int(time.time() * 1000)
        start = now_ms - (n + 2) * TF_S[tf] * 1000
        raw = self.post({"type": "candleSnapshot", "req": {"coin": coin, "interval": TF[tf], "startTime": start, "endTime": now_ms}}) or []
        out = []
        for c in raw:
            if int(c["T"]) >= now_ms:                                     # close time in the future -> still forming
                continue
            out.append({"t": int(c["t"]) / 1000.0, "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"]), "v": float(c["v"]),
                        "trades": int(c.get("n") or 0)})
        return out[-n:]

    def flow(self, coin: str) -> dict:
        """L2 top-5 imbalance and the aggressive-buy share of the last 30 s of public trades (side 'B' assumed buyer-taker - TASK 004: NOT_VERIFIED, consumers gated)."""
        book = self.post({"type": "l2Book", "coin": coin}) or {}
        lv = book.get("levels") or [[], []]
        bid = sum(float(x["sz"]) for x in lv[0][:5])
        ask = sum(float(x["sz"]) for x in lv[1][:5])
        imb = (bid - ask) / (bid + ask) if bid + ask > 0 else None
        tr = self.post({"type": "recentTrades", "coin": coin}) or []
        t_book = float(book.get("time") or time.time() * 1000) / 1000.0
        recent = [x for x in tr if float(x["time"]) / 1000.0 >= t_book - 30]
        buy = sum(float(x["sz"]) for x in recent if x["side"] == "B")
        tot = sum(float(x["sz"]) for x in recent)
        from ..orderflow.trades import SIDE_SEMANTICS
        return {"t": t_book, "imbalance5": imb, "aggr_buy_share_30s": (buy / tot) if tot > 0 else None, "trades_30s": len(recent), "connected": True,
                "aggressor_semantics": SIDE_SEMANTICS["HYPERLIQUID"]["status"],          # TASK 004: 'B' = buyer taker is NOT_VERIFIED
                "best_bid": float(lv[0][0]["px"]) if lv[0] else None, "best_ask": float(lv[1][0]["px"]) if lv[1] else None}
