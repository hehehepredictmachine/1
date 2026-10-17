"""SymbolRegistry (1.14): the application works on exactly two canonical assets - XAUUSD and BTC.

* canonical_asset (XAUUSD / BTC) is separate from broker_symbol (exact terminal name, e.g. ``XAUUSD-``), instrument_id
  (canonical:venue:broker_symbol), venue (terminal server / company), instrument_type, quote currency, contract size and price unit;
* a broker symbol is accepted for an asset ONLY through its metadata (currency_base / currency_profit / contract) - never by
  prefix matching or stripping characters; XAUT/PAXG are not XAU, WBTC/BTCB are not BTC, a USDT-quoted symbol is not BTCUSD;
* nothing is auto-selected: candidates are PROPOSED and the user confirms one (Ustawienia); a CONFIRMED mapping stores the
  contract fingerprint and a changed contract blocks only that asset's path (CONTRACT_SPEC_CHANGED);
* 1.14.1 (user decision): NO symbol blocking. The bot works on the symbols enabled on the broker account; when the configured
  symbol is missing it adopts the matching symbol from the terminal (Market Watch first). Metadata checks are informational
  (warnings), never a reason to stop data, analysis or the API. `check_symbol` only labels a symbol with its asset.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

ALLOWED = ("XAUUSD", "BTC")

SPECS: dict[str, dict] = {
    "XAUUSD": {"base": {"XAU"}, "profit": {"USD"}, "forbidden_base": {"XAUT", "XAUT0", "PAXG", "XAUUSDT"},
               "asset_class": "METAL", "price_unit": "USD za uncję trojańską × contract_size (z terminala)",
               "sessions": "przerwy wg sesji brokera (symbol_info_session_* / brak notowań w weekend)"},
    "BTC": {"base": {"BTC", "XBT"}, "profit": {"USD"}, "forbidden_base": {"WBTC", "BTCB", "TBTC", "RENBTC"},
            "asset_class": "CRYPTO", "price_unit": "USD za 1 BTC × contract_size (z terminala)",
            "sessions": "dostępność CFD/venue sprawdzana z notowań (także weekend) - nie zakładana"},
}
STABLE_QUOTES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD"}
FINGERPRINT_KEYS = ("currency_base", "currency_profit", "trade_contract_size", "digits", "point")
CALC_MODE = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFD_INDEX", 4: "CFD_LEVERAGE", 5: "FOREX_NO_LEVERAGE",
             32: "EXCH_STOCKS", 33: "EXCH_FUTURES", 34: "EXCH_FUTURES_FORTS", 35: "EXCH_BONDS"}


class SymbolNotAllowed(PermissionError):
    pass


def _up(v) -> str:
    return str(v or "").strip().upper()


def classify(meta: dict | None) -> dict:
    """Which canonical asset (if any) a terminal symbol is, from its metadata only. Returns matches + conflicts."""
    if not meta:
        return {"asset": None, "conflicts": ["NO_METADATA"], "notes": []}
    base, profit = _up(meta.get("currency_base")), _up(meta.get("currency_profit"))
    out: dict = {"asset": None, "conflicts": [], "notes": [], "base": base, "profit": profit}
    hits = []
    for asset, sp in SPECS.items():
        if base in sp["forbidden_base"]:
            out["conflicts"].append(f"{asset}_LOOKALIKE_BASE:{base}")
            continue
        if base in sp["base"]:
            if profit in sp["profit"]:
                hits.append(asset)
            elif profit in STABLE_QUOTES:
                out["conflicts"].append(f"{asset}_QUOTED_IN_{profit}_NOT_USD")
            else:
                out["conflicts"].append(f"{asset}_PROFIT_CURRENCY_{profit or 'UNKNOWN'}")
    cm = meta.get("trade_calc_mode")
    itype = CALC_MODE.get(cm) if cm is not None else None
    if itype in ("FUTURES", "EXCH_FUTURES", "EXCH_FUTURES_FORTS"):
        out["notes"].append("FUTURES_CONTRACT_EXPIRY_AND_BASIS_APPLY")
    if len(hits) == 1 and not out["conflicts"]:
        out["asset"] = hits[0]
    out["instrument_type"] = itype or "UNKNOWN_CALC_MODE"
    return out


def fingerprint(meta: dict) -> dict:
    return {k: meta.get(k) for k in FINGERPRINT_KEYS}


class AssetRegistry:
    def __init__(self, cfg_store, bridge=None, applog=None):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.log = applog
        self._lock = threading.Lock()
        self._meta: dict[str, dict] = {}            # asset -> last metadata read from the terminal
        self._check: dict[str, dict] = {}           # asset -> {"status": OK/CONFLICT/UNVERIFIED, "reasons": [...], "at": iso}
        self.rejections: list[dict] = []            # last allowlist rejections (diagnostics)

    # ------------------------------------------------------------------ queries
    def mapping(self, asset: str):
        return self.cfg_store.get().assets.mappings.get(asset)

    def active(self) -> str:
        return self.cfg_store.get().assets.active

    def _usable(self, asset: str) -> tuple[bool, str | None]:
        """An asset is usable whenever it has a broker symbol (no confirmation / metadata gate)."""
        m = self.mapping(asset)
        if m is None or not m.broker_symbol:
            return False, "BRAK_SYMBOLU_W_TERMINALU"
        return True, None

    def allowed_symbols(self) -> dict[str, str]:
        """broker_symbol -> canonical asset, only for usable mappings."""
        out = {}
        for a in ALLOWED:
            ok, _ = self._usable(a)
            if ok:
                out[self.mapping(a).broker_symbol] = a
        return out

    def asset_of(self, symbol: str) -> str | None:
        return self.allowed_symbols().get(symbol)

    def check_symbol(self, symbol: str, path: str) -> str | None:
        """Labels a symbol with its asset (XAUUSD / BTC) or None for any other enabled symbol. Never blocks."""
        return self.asset_of(symbol)

    def check_asset(self, asset: str, path: str) -> str:
        if asset not in ALLOWED:
            raise SymbolNotAllowed(f"ASSET_NOT_ALLOWED:{path}:{asset}")
        ok, why = self._usable(asset)
        if not ok:
            got = self.autodetect(asset)                 # try the account's enabled symbols before giving up
            if not got:
                raise SymbolNotAllowed(f"ASSET_NOT_USABLE:{path}:{asset}:{why}")
        return self.mapping(asset).broker_symbol

    # ------------------------------------------------------------------ metadata check
    def verify(self, asset: str, meta: dict | None) -> dict:
        """Check the terminal metadata of the mapped symbol. CONFLICT blocks only this asset."""
        m = self.mapping(asset)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if meta is None:
            res = {"status": "UNVERIFIED", "reasons": ["SYMBOL_NOT_IN_TERMINAL"], "at": now}
        else:
            c = classify(meta)
            reasons = list(c["conflicts"])
            if c["asset"] != asset:
                reasons.append(f"METADATA_IS_{c['asset'] or 'NOT_' + asset}")
            if m is not None and m.status == "CONFIRMED" and m.fingerprint:
                fp = fingerprint(meta)
                changed = [k for k in FINGERPRINT_KEYS if m.fingerprint.get(k) != fp.get(k)]
                if changed:
                    reasons.append("CONTRACT_SPEC_CHANGED:" + "/".join(changed))
            res = {"status": "CONFLICT" if reasons else "OK", "reasons": reasons, "at": now, "classification": c}
        with self._lock:
            self._meta[asset] = meta or {}
            self._check[asset] = res
        if res["status"] == "CONFLICT":
            res["status"] = "WARNING"                     # informational only - nothing is blocked
            if self.log is not None:
                self.log.info("ASSETS", "METADATA_NOTE", f"{asset}: symbol {m.broker_symbol if m else '-'} – metadane: " + ", ".join(res["reasons"][:3])
                              + " (tylko informacja, symbol działa)")
        return res

    def verify_main(self, symbol: str, meta: dict) -> None:
        """Called by the bridge after reading symbol_info of the main symbol: records metadata, never raises. Afterwards the
        other asset gets its symbol from the account if it has none yet."""
        a = self.active()
        self.verify(a, meta)
        for other in ALLOWED:
            m = self.mapping(other)
            if other != a and (m is None or not m.broker_symbol):
                try:
                    self.autodetect(other)
                except Exception:  # detection is best effort; the main symbol keeps working
                    pass

    # ------------------------------------------------------------------ symbol from the account
    NAME_HINTS = {"XAUUSD": ("XAUUSD", "GOLD", "XAU"), "BTC": ("BTCUSD", "BITCOIN", "BTC")}

    def find_on_account(self, asset: str) -> str | None:
        """Symbol of `asset` enabled on the account: Market Watch first, then all symbols; metadata match first, then name.
        Look-alikes (XAUT, PAXG, WBTC, ...) are skipped."""
        b = self.bridge
        if b is None:
            return None
        try:
            raw = b._call(lambda mm: mm.symbols_get())
        except Exception:
            return None
        rows = []
        for r in raw or ():
            d = r._asdict() if hasattr(r, "_asdict") else dict(r)
            rows.append(d)
        bad = SPECS[asset]["forbidden_base"]

        def score(d):
            name = str(d.get("name") or "").upper()
            if any(x in name for x in bad) or _up(d.get("currency_base")) in bad:
                return None
            c = classify(d)
            s = 0
            if c["asset"] == asset:
                s += 10
            elif not any(h in name for h in self.NAME_HINTS[asset]):
                return None
            if name.startswith(self.NAME_HINTS[asset][0]):
                s += 3
            if d.get("visible"):
                s += 5
            if d.get("trade_mode", 4) != 0:
                s += 1
            return s
        best = sorted(((score(d), str(d.get("name"))) for d in rows if score(d) is not None), key=lambda x: (-x[0], len(x[1]), x[1]))
        return best[0][1] if best else None

    def autodetect(self, asset: str) -> str | None:
        sym = self.find_on_account(asset)
        if not sym:
            return None
        others = [a for a in ALLOWED if a != asset and self.mapping(a) and self.mapping(a).broker_symbol == sym]
        if others:
            return None
        patch = {"assets": {"mappings": {asset: {"broker_symbol": sym, "status": "AUTO_DETECTED"}}}}
        if self.active() == asset:
            patch["mt5"] = {"symbol": sym}
        self.cfg_store.update(patch)
        if self.log is not None:
            self.log.info("ASSETS", "AUTO_DETECTED", f"{asset}: używam symbolu z rachunku – {sym}")
        return sym

    def refresh(self) -> None:
        """Re-read metadata of both mapped symbols (no side effects in the terminal)."""
        b = self.bridge
        if b is None or b.state != "CONNECTED":
            return
        for a in ALLOWED:
            m = self.mapping(a)
            if m and m.broker_symbol:
                try:
                    self.verify(a, b.symbol_meta(m.broker_symbol, guard=False))
                except Exception as exc:  # terminal hiccup: keep the previous result, record it
                    with self._lock:
                        self._check.setdefault(a, {"status": "UNVERIFIED", "reasons": [], "at": None})["reasons"] = [f"READ_FAILED:{type(exc).__name__}"]

    def candidates(self, asset: str) -> list[dict]:
        """Terminal symbols whose metadata classify as `asset` (no prefix guessing). Shown to the user, never auto-applied."""
        if asset not in ALLOWED:
            raise SymbolNotAllowed(f"ASSET_NOT_ALLOWED:CANDIDATES:{asset}")
        b = self.bridge
        if b is None or b.state != "CONNECTED":
            return []
        out = []
        hints = self.NAME_HINTS[asset]
        for s in b.list_symbols(visible_only=False):
            c = classify(s)
            if c["asset"] == asset or any(x.startswith(asset + "_") for x in c["conflicts"]) or any(h in str(s.get("name", "")).upper() for h in hints):
                out.append({"broker_symbol": s.get("name"), "description": s.get("description"), "path": s.get("path"),
                            "currency_base": s.get("currency_base"), "currency_profit": s.get("currency_profit"),
                            "contract_size": s.get("trade_contract_size"), "digits": s.get("digits"),
                            "eligible": True, "metadata_match": c["asset"] == asset, "conflicts": c["conflicts"],
                            "instrument_type": c["instrument_type"], "visible": s.get("visible")})
        return out

    # ------------------------------------------------------------------ changes (user actions)
    def confirm(self, asset: str, broker_symbol: str) -> dict:
        if asset not in ALLOWED:
            raise SymbolNotAllowed(f"ASSET_NOT_ALLOWED:CONFIRM:{asset}")
        b = self.bridge
        if b is None or b.state != "CONNECTED":
            raise ValueError("TERMINAL_NOT_CONNECTED_CANNOT_VERIFY")
        meta = b.symbol_meta(broker_symbol, guard=False)
        if meta is None:
            raise ValueError(f"SYMBOL_NOT_IN_TERMINAL:{broker_symbol}")
        c = classify(meta)                                # informational: the user's choice is respected
        other = [a for a in ALLOWED if a != asset and (self.mapping(a) and self.mapping(a).broker_symbol == broker_symbol)]
        if other:
            raise ValueError("SYMBOL_ALREADY_MAPPED_TO_" + other[0])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        patch = {"assets": {"mappings": {asset: {"broker_symbol": broker_symbol, "status": "CONFIRMED", "confirmed_at": now,
                                                  "fingerprint": fingerprint(meta)}}}}
        if self.active() == asset:
            patch["mt5"] = {"symbol": broker_symbol}
        self.cfg_store.update(patch)
        self.verify(asset, meta)
        if self.log is not None:
            self.log.info("ASSETS", "MAPPING_CONFIRMED", f"{asset} → {broker_symbol} potwierdzone przez użytkownika (metadane: {c['base']}/{c['profit']}).")
        return self.state()

    def switch(self, asset: str) -> dict:
        broker_symbol = self.check_asset(asset, "SWITCH")
        self.cfg_store.update({"assets": {"active": asset}, "mt5": {"symbol": broker_symbol, "analytical_alias": asset}})
        if self.log is not None:
            self.log.info("ASSETS", "ACTIVE_ASSET", f"Aktywne aktywo: {asset} ({broker_symbol}). Feed, cechy, modele, checklista i statystyki przełączone.")
        return self.state()

    # ------------------------------------------------------------------ public state
    def instrument(self, asset: str) -> dict:
        m = self.mapping(asset)
        meta = self._meta.get(asset) or {}
        venue = None
        acct = getattr(self.bridge, "account", None) if self.bridge is not None else None
        if acct:
            venue = acct.get("server") or acct.get("company")
        bs = m.broker_symbol if m else None
        return {"canonical_asset": asset, "broker_symbol": bs, "instrument_id": f"{asset}:{venue or 'UNKNOWN_VENUE'}:{bs}" if bs else None,
                "venue": venue, "instrument_type": classify(meta)["instrument_type"] if meta else None,
                "quote_currency": meta.get("currency_profit"), "contract_size": meta.get("trade_contract_size"),
                "digits": meta.get("digits"), "point": meta.get("point"), "price_unit": SPECS[asset]["price_unit"],
                "asset_class": SPECS[asset]["asset_class"], "sessions_policy": SPECS[asset]["sessions"]}

    def state(self) -> dict:
        cfg = self.cfg_store.get()
        items = {}
        for a in ALLOWED:
            m = cfg.assets.mappings[a]
            ok, why = self._usable(a)
            items[a] = {"canonical_asset": a, "mapping_status": m.status, "broker_symbol": m.broker_symbol,
                        "confirmed_at": m.confirmed_at, "metadata_check": self._check.get(a) or {"status": "UNVERIFIED", "reasons": []},
                        "usable": ok, "blocked_reason": why, "instrument": self.instrument(a)}
        return {"allowed": list(ALLOWED), "active": cfg.assets.active, "assets": items,
                "max_joint_exposure_pct": cfg.assets.max_joint_exposure_pct, "rejections": self.rejections[-10:]}
