"""SymbolRegistry (1.14): the application works on exactly two canonical assets - XAUUSD and BTC.

* canonical_asset (XAUUSD / BTC) is separate from broker_symbol (exact terminal name, e.g. ``XAUUSD-``), instrument_id
  (canonical:venue:broker_symbol), venue (terminal server / company), instrument_type, quote currency, contract size and price unit;
* a broker symbol is accepted for an asset ONLY through its metadata (currency_base / currency_profit / contract) - never by
  prefix matching or stripping characters; XAUT/PAXG are not XAU, WBTC/BTCB are not BTC, a USDT-quoted symbol is not BTCUSD;
* nothing is auto-selected: candidates are PROPOSED and the user confirms one (Ustawienia); a CONFIRMED mapping stores the
  contract fingerprint and a changed contract blocks only that asset's path (CONTRACT_SPEC_CHANGED);
* `check_symbol(sym, path)` is the allowlist used by the data input (bridge), API, training, notifications and execution.
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
        m = self.mapping(asset)
        if m is None or not m.broker_symbol:
            return False, "UNMAPPED"
        if m.status not in ("USER_SPECIFIED", "CONFIRMED"):
            return False, f"MAPPING_{m.status}_NEEDS_CONFIRMATION"
        chk = self._check.get(asset)
        if chk and chk["status"] == "CONFLICT":
            return False, "METADATA_CONFLICT:" + ",".join(chk["reasons"][:3])
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

    def check_symbol(self, symbol: str, path: str) -> str:
        """Allowlist gate. Returns the canonical asset or raises SymbolNotAllowed (logged, counted)."""
        a = self.asset_of(symbol)
        if a is None:
            rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": symbol, "path": path}
            with self._lock:
                self.rejections = (self.rejections + [rec])[-50:]
            raise SymbolNotAllowed(f"SYMBOL_NOT_ALLOWED:{path}:{symbol}")
        return a

    def check_asset(self, asset: str, path: str) -> str:
        if asset not in ALLOWED:
            raise SymbolNotAllowed(f"ASSET_NOT_ALLOWED:{path}:{asset}")
        ok, why = self._usable(asset)
        if not ok:
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
        if res["status"] == "CONFLICT" and self.log is not None:
            self.log.warn("ASSETS", "METADATA_CONFLICT", f"{asset}: symbol {m.broker_symbol if m else '-'} zablokowany – " + ", ".join(res["reasons"][:3]))
        return res

    def verify_main(self, symbol: str, meta: dict) -> None:
        """Called by the bridge after reading symbol_info of the main symbol. Raises when the path must stay blocked."""
        a = self.active()
        m = self.mapping(a)
        if m is None or m.broker_symbol != symbol:
            raise SymbolNotAllowed(f"SYMBOL_NOT_ALLOWED:DATA:{symbol}")
        res = self.verify(a, meta)
        if res["status"] == "CONFLICT":
            raise SymbolNotAllowed(f"ASSET_METADATA_CONFLICT:{a}:{','.join(res['reasons'][:3])}")

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
        for s in b.list_symbols(visible_only=False):
            c = classify(s)
            if c["asset"] == asset or any(x.startswith(asset + "_") for x in c["conflicts"]):
                out.append({"broker_symbol": s.get("name"), "description": s.get("description"), "path": s.get("path"),
                            "currency_base": s.get("currency_base"), "currency_profit": s.get("currency_profit"),
                            "contract_size": s.get("trade_contract_size"), "digits": s.get("digits"),
                            "eligible": c["asset"] == asset, "conflicts": c["conflicts"], "instrument_type": c["instrument_type"]})
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
        c = classify(meta)
        if c["asset"] != asset:
            raise ValueError(f"METADATA_DOES_NOT_MATCH_{asset}:" + ",".join(c["conflicts"] or [f"IS_{c['asset']}"]))
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
