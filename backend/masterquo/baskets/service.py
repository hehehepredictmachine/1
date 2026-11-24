"""BasketService (1.41) - registry, selector, conflict resolver, risk allocator, hedge planner host, ledger and scheduler of the
6 baskets / 60 strategies across the two market profiles (1.46 docstring: OTC retired in TASK 020 - history only, never scanned).
One instance in Runtime, own thread, autostart (DIRECT_USER_REQUEST).

Flow per market context (profile + venue + environment + account/public + product + native instrument):
  closed bars (MT5 bridge | Hyperliquid public API, core perps only) -> shared detectors (one Feat per instrument / TF / bar)
  -> regime -> selector (OFF / AUTO / MANUAL_SELECT, separate from the execution mode) -> rule families -> plans
  -> event dedupe (one primary plan per event id; other strategies = justifications) -> direction conflict (WAIT) -> risk allocation
  (quantity / stake null without the profile's capital config) -> ledger -> API / UI; hedge planners on existing exposure.
Execution (1.42, DIRECT_USER_REQUEST "zlecenia FOREX"): PositionPlans of the FOREX_MT5 baskets (FX_SMC / FX_SCALP / FX_HEDGE) on the
bridge symbol are handed to the EXISTING SH path (sh/service.py: coordinator -> shared risk engine with the user's limits -> intent /
atomic risk reservation -> SH executor), one primary plan per event, each signal at most once (table `executions`). The baskets never
send an order themselves and never change the account mode, STOP, risk limits, leverage or the gold strategies. CRYPTO: manual.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from . import catalog as CAT
from . import detectors as D
from . import hedge as HG
from . import rules as RL
from .hyperliquid import Hyperliquid, HLError, TF_S as HL_TF_S

log = logging.getLogger("masterquo.baskets")
TF_S = {"S5": 5, "S15": 15, "S30": 30, "M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
REGIME_GROUPS = {"TREND": {"TREND_PULLBACK", "MOMENTUM", "FVG", "BOS_OB", "OTE", "BREAKOUT", "NESTED", "XASSET", "IFVG", "BREAKER", "VWAP", "ORDERFLOW"},
                 "RANGE": {"SWEEP_RECLAIM", "MEAN_REVERSION", "SUPPORT_REJECTION", "DOUBLE_BOTTOM", "IFVG", "BREAKER", "VWAP"},
                 "COMPRESSION": {"COMPRESSION", "BREAKOUT", "ORDERFLOW", "SWEEP_RECLAIM"}}
DEFAULT_SETTINGS = {
    "activation_policy": "DIRECT_USER_REQUEST",
    "active_profile": "FOREX_MT5",
    "profiles": {
        "FOREX_MT5": {"enabled": True, "selection": "AUTO", "instruments": [], "capital": {"risk_money": None}, "fx_pairs": [], "pair_map": {},
                      "execution": "AUTO_SH"},      # 1.42: AUTO_SH = plans go to the SH execution path | SIGNALS_ONLY = 1.41 behaviour
        "CRYPTO_FOMO_PERPS": {"enabled": True, "selection": "AUTO", "instruments": ["BTC", "ETH", "SOL", "HYPE"], "flow_instrument": "BTC",
                              "capital": {"risk_money": None, "currency": "USDC"}, "fees": {"taker": None, "maker": None}, "pair_map": {}, "same_underlying": {}},
    },
    # 1.46 (audit note): risk_weight / max_open_groups / conflict_policy / selection_policy are informational only - _resolve reads
    # enabled, max_pending_intents and cooldown_bars; the keys stay (stable config keys, old settings.json files keep loading)
    "baskets": {b: {"enabled": True, "risk_weight": 1 / 3, "max_open_groups": 2, "max_pending_intents": 3, "cooldown_bars": 3,
                    "conflict_policy": "WAIT_ON_OPPOSITE", "selection_policy": "REGIME_ROUTED"} for b in CAT.BASKETS},
    "strategies": {},            # id -> {"enabled": bool, "params": {...}} (overrides of the catalog parameters)
    "manual_select": {},         # profile -> [strategy ids] for MANUAL_SELECT
    "cycle_s": 5.0,
}


def bdir() -> Path:
    p = paths.data_dir() / "baskets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _merge(a, b):
    out = json.loads(json.dumps(a))
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _research_only(name) -> bool:
    """1.46: a Hyperliquid HIP-3 market ("xyz:NVDA", "xyz:SP500" - Trade[XYZ] INDICES / FOMO_STOCK_PERPS) is RESEARCH_ONLY (workflow v3.2:
    read-only data, execution DISABLED) - never an instrument, flow source, pair / same-underlying leg or hedge leg of CRYPTO_FOMO_PERPS."""
    return isinstance(name, str) and ":" in name


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _like(default, v) -> bool:
    """1.46: a parameter override has the type of the catalog default (None default = scalar of an open type)."""
    if default is None:
        return v is None or isinstance(v, str) or _num(v)
    if isinstance(default, bool):
        return isinstance(v, bool)
    if isinstance(default, (int, float)):
        return _num(v)
    if isinstance(default, str):
        return isinstance(v, str)
    if isinstance(default, (list, tuple)):
        return isinstance(v, list) and (not default or all(_like(default[0], x) for x in v))
    if isinstance(default, dict):
        return isinstance(v, dict)
    return True


def _need(ok: bool, where: str, what: str) -> None:
    if not ok:
        raise ValueError(f"SETTINGS_TYPE:{where}: {what}")


def _names(v, where: str) -> None:
    _need(isinstance(v, list) and all(isinstance(x, str) and x for x in v), where, "lista nazw (tekst)")


def _check_shape(patch) -> None:
    """1.46: PUT /api/v1/baskets/settings - the structure is checked BEFORE anything else reads it (a string / null / number entry was
    stored and then broke status / basket_view / the cycle, or raised TypeError = HTTP 500). Raises ValueError (HTTP 400)."""
    _need(isinstance(patch, dict), "body", "obiekt")
    for sec in ("profiles", "baskets", "strategies", "manual_select"):
        # an explicit null section is refused too: the settings merge stores it as given (as in 1.45) and the cycle would stop on it
        _need(sec not in patch or isinstance(patch[sec], dict), sec, "obiekt")
    for sec in ("profiles", "baskets", "strategies"):
        for k, v in (patch.get(sec) or {}).items():
            _need(isinstance(v, dict), f"{sec}.{k}", "obiekt")
    for p, ids in (patch.get("manual_select") or {}).items():
        if ids is not None:
            _names(ids, f"manual_select.{p}")
    _need(patch.get("active_profile") is None or isinstance(patch["active_profile"], str), "active_profile", "tekst")


def _check_fields(patch: dict) -> None:
    """1.46: known fields of profiles / baskets / strategies (ids already validated) have the right type and range. Unknown keys inside
    an entry stay allowed (forward compatibility)."""
    for p, v in (patch.get("profiles") or {}).items():
        w = f"profiles.{p}"
        _need("enabled" not in v or isinstance(v["enabled"], bool), f"{w}.enabled", "true / false")
        for k in ("instruments", "fx_pairs"):
            if k in v:
                _names(v[k], f"{w}.{k}")
        for k in ("pair_map", "same_underlying"):
            m = v.get(k)
            _need(m is None or (isinstance(m, dict) and all(x is None or isinstance(x, str) for x in m.values())), f"{w}.{k}", "obiekt nazwa -> nazwa")
        _need(v.get("flow_instrument") is None or isinstance(v["flow_instrument"], str), f"{w}.flow_instrument", "tekst")
        for k in ("capital", "fees"):
            _need(v.get(k) is None or isinstance(v[k], dict), f"{w}.{k}", "obiekt")
        cap = v.get("capital") or {}
        _need(cap.get("risk_money") is None or (_num(cap["risk_money"]) and cap["risk_money"] >= 0), f"{w}.capital.risk_money", "null lub liczba >= 0")
        _need(cap.get("currency") is None or isinstance(cap["currency"], str), f"{w}.capital.currency", "tekst")
        for k, x in (v.get("fees") or {}).items():
            _need(x is None or _num(x), f"{w}.fees.{k}", "null lub liczba")
    for b, v in (patch.get("baskets") or {}).items():
        w = f"baskets.{b}"
        _need("enabled" not in v or isinstance(v["enabled"], bool), f"{w}.enabled", "true / false")
        for k in ("max_pending_intents", "cooldown_bars", "max_open_groups"):
            _need(k not in v or (isinstance(v[k], int) and not isinstance(v[k], bool) and v[k] >= 0), f"{w}.{k}", "liczba całkowita >= 0")
        _need("risk_weight" not in v or (_num(v["risk_weight"]) and v["risk_weight"] >= 0), f"{w}.risk_weight", "liczba >= 0")
        for k in ("conflict_policy", "selection_policy"):
            _need(k not in v or isinstance(v[k], str), f"{w}.{k}", "tekst")
    for sid, v in (patch.get("strategies") or {}).items():
        w = f"strategies.{sid}"
        _need("enabled" not in v or isinstance(v["enabled"], bool), f"{w}.enabled", "true / false")
        _need(v.get("params") is None or isinstance(v["params"], dict), f"{w}.params", "obiekt")
        schema = CAT.BY_ID[sid]["parameter_schema"]
        for k, x in (v.get("params") or {}).items():
            if k in schema:
                _need(_like(schema[k], x), f"{w}.params.{k}", f"typ jak domyślnie ({json.dumps(schema[k], default=str)})")


def _check_research_only(patch: dict) -> None:
    """1.46 (rule: INDICES / FOMO_STOCK_PERPS stay RESEARCH_ONLY): CRYPTO_FOMO_PERPS settings never name a Trade[XYZ] market."""
    pr = (patch.get("profiles") or {}).get("CRYPTO_FOMO_PERPS") or {}
    names = list(pr.get("instruments") or []) + [pr.get("flow_instrument")]
    for k in ("pair_map", "same_underlying"):
        names += [n for kv in (pr.get(k) or {}).items() for n in kv]
    for sid, v in (patch.get("strategies") or {}).items():
        if CAT.BY_ID[sid]["profile_id"] == "CRYPTO_FOMO_PERPS":
            prm = v.get("params") or {}
            pairs = prm.get("pairs") if isinstance(prm.get("pairs"), dict) else {}
            names += [prm.get("factor"), prm.get("partner")] + [n for kv in pairs.items() for n in kv]
    bad = sorted({n for n in names if _research_only(n)})
    if bad:
        raise ValueError(f"RESEARCH_ONLY_MARKET:{bad} – rynki Trade[XYZ] (INDICES / FOMO_STOCK_PERPS) są tylko do badań, bez sygnałów i ticketów")


def _iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).isoformat(timespec="seconds") if t else None


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


class Ledger:
    """Basket decisions and SIGNAL_SIMULATION outcomes (idempotent by event id + strategy). Account PnL is NOT recorded here: real
    fills / fees / funding live in the account's own history - so nothing is ever counted twice."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        with self._c() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS signals(signal_id TEXT PRIMARY KEY, event_id TEXT, strategy_id TEXT, basket_id TEXT, profile_id TEXT,
              context_key TEXT, instrument TEXT, tf TEXT, side TEXT, created_at REAL, bar_t REAL, status TEXT, role TEXT, plan TEXT, setup TEXT,
              scores TEXT, outcome TEXT, outcome_at REAL, outcome_kind TEXT);
            CREATE INDEX IF NOT EXISTS ix_sig_basket ON signals(basket_id, created_at);
            CREATE TABLE IF NOT EXISTS hedge_plans(plan_id TEXT PRIMARY KEY, strategy_id TEXT, basket_id TEXT, profile_id TEXT, created_at REAL, state TEXT,
              reason TEXT, plan TEXT);
            CREATE TABLE IF NOT EXISTS declared(id TEXT PRIMARY KEY, profile_id TEXT, kind TEXT, data TEXT, created_at REAL, status TEXT);
            CREATE TABLE IF NOT EXISTS executions(signal_id TEXT PRIMARY KEY, plan_id TEXT, status TEXT, reason TEXT, at REAL);
            """)

    def mark_exec(self, sid: str, plan_id: str | None, status: str, reason: str | None = None) -> None:
        """1.42: a basket signal handed to the SH path is consumed once (idempotent; the first outcome stays)."""
        with self._lock, self._c() as c:
            c.execute("INSERT OR IGNORE INTO executions VALUES(?,?,?,?,?)", (sid, plan_id, status, reason, time.time()))

    def executed(self) -> dict:
        with self._c() as c:
            return {r["signal_id"]: dict(r) for r in c.execute("SELECT * FROM executions ORDER BY at DESC LIMIT 500")}

    @contextlib.contextmanager
    def _c(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add_signal(self, row: dict) -> bool:
        with self._lock, self._c() as c:
            cur = c.execute("INSERT OR IGNORE INTO signals VALUES(:signal_id,:event_id,:strategy_id,:basket_id,:profile_id,:context_key,:instrument,:tf,:side,"
                            ":created_at,:bar_t,:status,:role,:plan,:setup,:scores,NULL,NULL,NULL)",
                            {**row, "plan": json.dumps(row["plan"], default=str), "setup": json.dumps(row["setup"], default=str),
                             "scores": json.dumps(row["scores"], default=str)})
            return cur.rowcount > 0

    def update(self, sid: str, **kw) -> None:
        sets = ",".join(f"{k}=?" for k in kw)
        with self._lock, self._c() as c:
            c.execute(f"UPDATE signals SET {sets} WHERE signal_id=?", [json.dumps(v) if isinstance(v, dict) else v for v in kw.values()] + [sid])

    def open_signals(self, profile: str | None = None) -> list[dict]:
        q = "SELECT * FROM signals WHERE status='ACTIVE'" + (" AND profile_id=?" if profile else "")
        with self._c() as c:
            rows = [self._row(r) for r in c.execute(q, [profile] if profile else [])]
        return [d for d in rows if d["status"] == "ACTIVE"]          # 1.46: retired-profile rows are never open (see _row)

    def recent(self, basket: str | None = None, limit: int = 100) -> list[dict]:
        q = "SELECT * FROM signals" + (" WHERE basket_id=?" if basket else "") + " ORDER BY created_at DESC LIMIT ?"
        with self._c() as c:
            return [self._row(r) for r in c.execute(q, ([basket] if basket else []) + [limit])]

    def stats(self) -> dict:
        with self._c() as c:
            rows = c.execute("SELECT basket_id, status, outcome_kind, count(*) n FROM signals GROUP BY basket_id, status, outcome_kind").fetchall()
        out = {}
        for r in rows:
            b = out.setdefault(r["basket_id"], {})
            k = r["outcome_kind"] or r["status"]
            b[k] = b.get(k, 0) + r["n"]
        return out

    def _row(self, r) -> dict:
        d = dict(r)
        for k in ("plan", "setup", "scores", "outcome"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        why = CAT.retired_reason(profile_id=d.get("profile_id")) if d.get("status") == "ACTIVE" else None
        if why:
            # 1.46: an ACTIVE signal of the retired OTC profile (written by <= 1.44) is never tracked again - it hung as ACTIVE in
            # GET /api/v1/baskets/signals. View only: the stored row keeps its original status (history / rollback untouched).
            d.update(status="RETIRED", stored_status="ACTIVE", retired_reason=why)
        return d

    def add_hedge(self, row: dict) -> None:
        with self._lock, self._c() as c:
            c.execute("INSERT OR REPLACE INTO hedge_plans VALUES(?,?,?,?,?,?,?,?)", (row["plan_id"], row["strategy_id"], row["basket_id"], row["profile_id"],
                                                                                   row["created_at"], row["state"], row.get("reason"), json.dumps(row.get("plan"), default=str)))

    def declared(self, profile: str) -> list[dict]:
        with self._c() as c:
            return [{**json.loads(r["data"]), "id": r["id"], "status": r["status"]} for r in      # 1.46: the row id wins over an "id" in the payload
                    c.execute("SELECT * FROM declared WHERE profile_id=? AND status='OPEN'", (profile,))]

    def declare(self, profile: str, kind: str, data: dict) -> str:
        did = data.get("id") or ("DCL-" + hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12])
        with self._lock, self._c() as c:
            # 1.46: the id comes from the client - an id of another profile (e.g. retired OTC history) was REPLACED by this row; such an
            # id is ignored and the row gets its own content id (the other record stays as it was)
            cur = c.execute("SELECT profile_id FROM declared WHERE id=?", (did,)).fetchone()
            if cur is not None and cur["profile_id"] != profile:
                data = {k: v for k, v in data.items() if k != "id"}
                did = "DCL-" + hashlib.sha256(json.dumps([profile, data], sort_keys=True, default=str).encode()).hexdigest()[:12]
            c.execute("INSERT OR REPLACE INTO declared VALUES(?,?,?,?,?,?)", (did, profile, kind, json.dumps({**data, "source": "MANUAL_DECLARED"}), time.time(), "OPEN"))
        return did

    def close_declared(self, did: str) -> None:
        with self._lock, self._c() as c:
            # 1.46: the history of a retired profile (OTC) is read-only - DELETE /baskets/declared/{id} closed OTC records
            c.execute("UPDATE declared SET status='CLOSED' WHERE id=? AND profile_id NOT IN (%s)" % ",".join("?" * len(CAT.RETIRED_PROFILE_IDS)),  # noqa: S608 - placeholders only
                      (did, *sorted(CAT.RETIRED_PROFILE_IDS)))


class Ctx:
    def __init__(self, profile: str, instrument: str, key: str):
        self.profile, self.instrument, self.key = profile, instrument, key
        self.last_bar: dict[str, float] = {}
        self.feats: dict[str, D.Feat] = {}
        self.state: dict[str, dict] = {}                   # strategy id -> runtime state
        self.regime: dict | None = None
        self.data_state = "WAITING_FOR_DATA"
        self.reason: str | None = None
        self.oi: list[tuple[float, float]] = []
        self.flow: list[dict] = []
        self.cache: dict[str, tuple[float, list]] = {}
        self.sfb: dict | None = None                       # TASK 018: last SFB snapshot meta for this scope (diagnostic)


class BasketService:
    def __init__(self, rt, *, data_dir: Path | None = None, hl: Hyperliquid | None = None):
        self.rt = rt
        self.base = Path(data_dir) if data_dir else bdir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.base / "ledger.sqlite")
        self.hl = hl or Hyperliquid()
        # TASK 020: OTC retired. 1.46 (I0112): the unreachable OTC feed reader (baskets/otc.py) was removed - nothing read it but tests;
        # the stored history in <data>/otc is left on disk untouched (never read, written or created here)
        self.ctx: dict[str, Ctx] = {}
        self.hedge_state: dict[str, dict] = {}
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self.loop = {"cycles": 0, "errors": 0, "last_error": None, "profile_errors": {}}
        self.hl_ctx: dict = {}
        self.hl_ctx_at = 0.0
        from .sfb import StrategyFilterBucket            # TASK 018: OFF by default -> exact parity with the previous route
        # 1.46: an sfb.json that 1.45 rejected (not an object, unknown key, apply_to_execution, bad mode, pooling) made BasketService fail to
        # construct - no scan, no signal, no plan to SH. The service now stays up for the views / the repair PUT, but stays FAIL-CLOSED as in
        # 1.45 (cycle() scans nothing, sh_candidates() = []) until a valid config is saved; the file is left as it is.
        self.sfb_blocked: str | None = None
        try:
            cfg, requested = self._sfb_effective(self._sfb_cfg())
        except (TypeError, ValueError) as exc:         # ConfigError is a ValueError
            cfg, requested = {}, f"INVALID_CONFIG: {exc}"[:200]
            self.sfb_blocked = requested
        self.sfb = StrategyFilterBucket(cfg)
        self.sfb.mode_requested = requested

    # ------------------------------------------------------------------ settings
    def _read(self):
        try:
            return json.loads((self.base / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sfb_cfg(self) -> dict:
        try:
            return json.loads((self.base / "sfb.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _sfb_effective(raw) -> tuple[dict, str | None]:
        """The stored sfb.json as 1.45 ran it (rule 1: the filter gates which basket strategies reach execution). Raises ConfigError for
        a file 1.45 rejected. 1.46 adds only a notice (status mode_requested); the file is not rewritten."""
        from .sfb import DEFAULT_CONFIG, ConfigError, validate_config
        cfg = raw or {}                                   # 1.45: an empty file / null / [] = defaults (OFF)
        if not isinstance(cfg, dict):
            raise ConfigError(f"CONFIG_NOT_OBJECT ({type(cfg).__name__})")
        # the 1.45 acceptance rules = validate_config without the 1.46 type / range checks of the evidence thresholds
        base = validate_config({k: v for k, v in cfg.items() if k not in DEFAULT_CONFIG or k in ("mode", "allow_cross_profile_pooling")})
        try:
            clean, notice = validate_config(cfg), None
        except ConfigError as exc:
            # accepted by 1.45, only the 1.46 threshold checks fail: the stored mode runs as in 1.45; the thresholds are never evaluated
            # without an evidence source (ELIGIBLE unreachable), so the defaults stand in for them
            clean, notice = base, f"THRESHOLDS_IGNORED: {exc} – tryb zachowany jak w 1.45, progi domyślne (brak źródła dowodów)"[:200]
        if clean["mode"] == "ASSIST":
            # an ASSIST stored by 1.45 keeps narrowing exactly as in 1.45 (only ELIGIBLE + HEDGING; never adds) - it cannot be set again
            notice = ("ASSIST (zapisany przez 1.45 – działa jak w 1.45: tylko zawęża, nigdy nie dodaje; nie można go ustawić ponownie – "
                      "przełącz na OFF / SHADOW, aby wznowić wejścia koszyków)" + (f"; {notice}" if notice else ""))[:300]
        return clean, notice

    def set_sfb(self, cfg: dict) -> dict:
        from .sfb import ConfigError, StrategyFilterBucket, validate_config
        clean = validate_config(cfg)
        if clean["mode"] == "ASSIST":
            raise ConfigError("ASSIST_DISABLED: moduły workflow v3.2 są tylko do odczytu – dozwolone OFF / OBSERVE / SHADOW / MANUAL_RESEARCH")
        tmp = self.base / "sfb.json.tmp"
        tmp.write_text(json.dumps({k: v for k, v in clean.items()}, indent=1), encoding="utf-8")
        tmp.replace(self.base / "sfb.json")
        self.sfb = StrategyFilterBucket(clean, self.sfb.outcomes_fn)
        self.sfb.mode_requested = None
        self.sfb_blocked = None                           # a valid config was saved - the fail-closed state of a rejected file ends
        return self.sfb.status()

    def settings(self) -> dict:
        """Active settings view. TASK 020: entries of the retired OTC profile / baskets / strategies stored by older versions are NOT
        deleted from settings.json (rollback) - they are moved out of the active view into `retired` with a machine-readable reason."""
        st = _merge(DEFAULT_SETTINGS, self._read())
        retired = {"profiles": {}, "baskets": {}, "strategies": {}, "manual_select": {}}
        for p in list(st.get("profiles") or {}):
            if p not in CAT.PROFILES:
                retired["profiles"][p] = {**st["profiles"].pop(p), "enabled": False, "reason": CAT.retired_reason(profile_id=p) or "UNKNOWN_PROFILE"}
        for b in list(st.get("baskets") or {}):
            if b not in CAT.BASKETS:
                retired["baskets"][b] = {**st["baskets"].pop(b), "enabled": False, "reason": CAT.retired_reason(basket_id=b) or "UNKNOWN_BASKET"}
        for sid in list(st.get("strategies") or {}):
            if sid not in CAT.BY_ID:
                retired["strategies"][sid] = {**(st["strategies"].pop(sid) or {}), "enabled": False,
                                              "reason": CAT.retired_reason(sid) or "UNKNOWN_STRATEGY"}
        for p in list(st.get("manual_select") or {}):
            ids = st["manual_select"][p] or []
            keep = CAT.active_only(ids)
            if p not in CAT.PROFILES or keep != list(ids):
                retired["manual_select"][p] = [i for i in ids if i not in keep]
                if p in CAT.PROFILES:
                    st["manual_select"][p] = keep
                else:
                    st["manual_select"].pop(p)
        if st.get("active_profile") not in CAT.PROFILES:
            retired["active_profile"] = st.get("active_profile")
            st["active_profile"] = "FOREX_MT5"               # the default profile, never a "replacement" market for OTC
        if any(retired[k] for k in retired):
            st["retired"] = {**retired, "notice": "Zestaw strategii OTC został wycofany (Apollo23, TASK 020) – wpisy OTC są wyłączone, "
                                                  "historia zostaje tylko do odczytu."}
        return st

    def update_settings(self, patch: dict) -> dict:
        _check_shape(patch)                               # 1.46: structure first (string / null / number entries were stored or gave 500)
        bad = [k for k in patch if k not in ("active_profile", "profiles", "baskets", "strategies", "manual_select")]
        if bad:
            raise ValueError(f"SETTINGS_KEYS_NOT_ALLOWED:{bad}")
        for sid in (patch.get("strategies") or {}):
            if CAT.retired_reason(sid):
                raise ValueError(f"RETIRED_STRATEGY_ID:{sid}")
            if sid not in CAT.BY_ID:
                raise ValueError(f"UNKNOWN_STRATEGY:{sid}")
        for b in (patch.get("baskets") or {}):
            if CAT.retired_reason(basket_id=b):
                raise ValueError(f"RETIRED_STRATEGY_ID:{b}")
            if b not in CAT.BASKETS:
                raise ValueError(f"UNKNOWN_BASKET:{b}")
        for p, v in (patch.get("profiles") or {}).items():
            if CAT.retired_reason(profile_id=p):
                raise ValueError(f"RETIRED_PROFILE:{p}")
            if p not in CAT.PROFILES:
                raise ValueError(f"UNKNOWN_PROFILE:{p}")
            if "selection" in v and v["selection"] not in ("OFF", "AUTO", "MANUAL_SELECT"):
                raise ValueError("selection: OFF | AUTO | MANUAL_SELECT")
            if "execution" in v and (p != "FOREX_MT5" or v["execution"] not in ("AUTO_SH", "SIGNALS_ONLY")):
                raise ValueError("execution: AUTO_SH | SIGNALS_ONLY (tylko FOREX_MT5; CRYPTO / OTC = ręcznie)")
        for p, ids in (patch.get("manual_select") or {}).items():
            bad_ids = [i for i in (ids or []) if CAT.retired_reason(i) or i not in CAT.BY_ID]
            if CAT.retired_reason(profile_id=p) or bad_ids:
                raise ValueError(f"RETIRED_STRATEGY_ID:{bad_ids or p}")
            if p not in CAT.PROFILES:                     # 1.46: was stored silently
                raise ValueError(f"UNKNOWN_PROFILE:{p}")
        if patch.get("active_profile") and CAT.retired_reason(profile_id=patch["active_profile"]):
            raise ValueError("RETIRED_PROFILE")
        if patch.get("active_profile") and patch["active_profile"] not in CAT.PROFILES:
            raise ValueError("UNKNOWN_PROFILE")
        _check_fields(patch)                              # 1.46: types / ranges of the known fields (text in numeric fields broke the cycle)
        _check_research_only(patch)                       # 1.46: Trade[XYZ] markets (INDICES / FOMO_STOCK_PERPS) stay RESEARCH_ONLY
        new = _merge(self._read(), patch)                 # retired entries already stored stay in the file (rollback) - never active
        tmp = self.base / "settings.json.tmp"
        tmp.write_text(json.dumps(new, indent=1), encoding="utf-8")
        tmp.replace(self.base / "settings.json")
        return self.settings()

    def strat_enabled(self, s: dict, st: dict) -> bool:
        b = st["baskets"][s["basket_id"]]
        o = st["strategies"].get(s["strategy_id"]) or {}
        return bool(b.get("enabled", True)) and bool(o.get("enabled", True))

    def params(self, s: dict, st: dict) -> dict:
        return {**s["parameter_schema"], **((st["strategies"].get(s["strategy_id"]) or {}).get("params") or {})}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="baskets", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception as exc:  # noqa: BLE001
                self.loop["errors"] += 1
                self.loop["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                log.exception("basket cycle failed")
            self._stop.wait(self._cycle_wait())

    def _cycle_wait(self) -> float:
        """1.46: computed inside a guard - cycle_s = "abc" (or an unreadable settings.json) killed the 'baskets' thread for good, a negative
        value made a loop without a pause. Invalid -> 5 s, at least 1 s."""
        try:
            w = float(self.settings().get("cycle_s") or 5.0)
        except Exception:  # noqa: BLE001
            return 5.0
        return max(1.0, w) if math.isfinite(w) else 5.0

    def cycle(self) -> dict:
        if self.sfb_blocked:
            # sfb.json rejected (1.45: BasketService not constructed at all) - nothing is scanned, tracked or published
            self.loop["blocked"] = self.sfb_blocked
            return {"state": "BLOCKED", "reason": self.sfb_blocked}
        self.loop.pop("blocked", None)
        st = self.settings()
        out = {}
        for prof, fn in (("FOREX_MT5", self._forex), ("CRYPTO_FOMO_PERPS", self._crypto)):     # TASK 020: OTC retired - never scanned
            if not st["profiles"][prof].get("enabled", True):
                continue
            try:                                               # one profile without data never stops the others
                out[prof] = fn(st)
                self.loop["profile_errors"].pop(prof, None)
            except Exception as exc:  # noqa: BLE001
                self.loop["profile_errors"][prof] = f"{type(exc).__name__}: {exc}"[:300]
                log.exception("basket profile %s failed", prof)
        self.loop["cycles"] += 1
        self.loop["last_cycle_at"] = time.time()
        return out

    # ------------------------------------------------------------------ data per profile
    def _context(self, profile: str, inst: str, venue: str, env: str, account: str, product: str) -> Ctx:
        key = f"{profile}|{venue}|{env}|{account}|{product}|{inst}"
        with self._lock:
            if key not in self.ctx:
                self.ctx[key] = Ctx(profile, inst, key)
            return self.ctx[key]

    def _forex(self, st: dict) -> dict:
        br = getattr(self.rt, "bridge", None)
        if br is None:
            return {"state": "WAITING_FOR_DATA", "reason": "brak bridge MT5"}
        sym = br.cfg.symbol
        acc = br.account_status() or {}
        if not acc.get("login"):
            return {"state": "WAITING_FOR_DATA", "reason": "konto MT5 jeszcze nie odczytane"}
        c = self._context("FOREX_MT5", sym, "MT5", "SYNTHETIC" if getattr(self.rt, "demo", False) else "LIVE", str(acc.get("login") or "?"),
                          "CFD")
        info = getattr(br, "symbol_info", None) or {}
        q = float(info.get("trade_tick_size") or info.get("point") or 0.01)

        def bars(tf, n=1500):
            try:
                raw = br.bars(tf, include_forming=False)[-n:]
            except Exception:  # noqa: BLE001
                return []
            out = []
            for b in raw:
                t = _ts(b.get("open_utc"))
                if t is not None:
                    out.append({"t": t, "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "tv": float(b.get("tv") or 0),
                                "v": (float(b["rv"]) if b.get("rv") else None)})
            return out
        exposure = []
        try:
            from ..evaluation.exposure import positions
            exposure = positions(self.rt.db)
            for e in exposure:
                e["price"] = None
        except Exception:  # noqa: BLE001
            exposure = []
        spec = {sym: {**info, "spread_price": None}}
        quote = (br.quote_status() or {}) if hasattr(br, "quote_status") else {}
        if quote.get("bid") and quote.get("ask"):
            spec[sym]["spread_price"] = float(quote["ask"]) - float(quote["bid"])
        extra = {"account": {"margin_mode": acc.get("margin_mode"), "currency": acc.get("currency")}, "spec": spec, "exposure": exposure,
                 "fx_pairs": st["profiles"]["FOREX_MT5"].get("fx_pairs") or [], "pair_map": st["profiles"]["FOREX_MT5"].get("pair_map") or {},
                 "symbol": sym, "events": self._calendar()}
        return self._run_ctx(c, st, bars, q, extra)

    def _calendar(self):
        nw = getattr(self.rt, "news", None)
        try:
            evs = nw.upcoming() if nw is not None and hasattr(nw, "upcoming") else None
        except Exception:  # noqa: BLE001
            evs = None
        if evs is None:
            return None
        out = []
        for e in evs:
            t = _ts(e.get("time_utc") or e.get("time"))
            if t:
                out.append({"t": t, "currency": e.get("currency"), "title": e.get("title") or e.get("event")})
        return out

    def _hl_bars(self, c: Ctx, coin: str, tf: str, n: int = 500) -> list[dict]:
        key = f"{coin}|{tf}"
        sec = HL_TF_S[tf]
        now = time.time()
        got = c.cache.get(key)
        if got and now < (got[1][-1]["t"] + 2 * sec + 5 if got[1] else got[0] + 30):
            return got[1]
        try:
            b = self.hl.candles(coin, tf, n)
        except HLError:
            return got[1] if got else []
        c.cache[key] = (now, b)
        return b

    def _crypto(self, st: dict) -> dict:
        pr = st["profiles"]["CRYPTO_FOMO_PERPS"]
        if os.environ.get("MQ_BASKETS_OFFLINE"):
            return {"state": "WAITING_FOR_DATA", "reason": "tryb offline (MQ_BASKETS_OFFLINE) – bez połączeń z Hyperliquid"}
        try:
            cat = self.hl.catalog()
        except HLError as exc:
            return {"state": "WAITING_FOR_DATA", "reason": f"Hyperliquid Info API: {exc}"}
        if time.time() - self.hl_ctx_at > 60:
            try:
                self.hl_ctx, self.hl_ctx_at = self.hl.contexts(), time.time()
            except HLError:
                pass
        out = {}
        bench = {}

        def core(name) -> bool:                       # 1.46: Hyperliquid core perps only - Trade[XYZ] (any non-core dex) is RESEARCH_ONLY
            return not _research_only(name) and (cat.get(name) or {}).get("dex", "core") == "core"
        # 1.46: settings stored before the validation existed may still name xyz markets - kept in the file, never used as a leg
        pair_map = {k: v for k, v in (pr.get("pair_map") or {}).items() if core(k) and (v is None or core(v))}
        same_underlying = {k: v for k, v in (pr.get("same_underlying") or {}).items() if core(k) and (v is None or core(v))}
        for coin in pr.get("instruments") or []:
            if not core(coin):                        # 1.46: was scanned by the 30 CP_* strategies and published as ACTIVE signals / tickets
                out[coin] = {"state": "RESEARCH_ONLY", "reason": "RESEARCH_ONLY_MARKET: rynek Trade[XYZ] (INDICES / FOMO_STOCK_PERPS) – tylko dane "
                                                                  "badawcze, bez sygnałów i ticketów (ustawienie zachowane w pliku)"}
                continue
            if coin not in cat or cat[coin]["delisted"]:
                out[coin] = {"state": "UNSUPPORTED", "reason": "kontrakt nieobecny w aktualnym katalogu"}
                continue
            c = self._context("CRYPTO_FOMO_PERPS", coin, f"HYPERLIQUID:{cat[coin]['dex']}", "MAINNET", "PUBLIC_DATA", "PERPETUAL")
            hc = self.hl_ctx.get(coin) or {}
            if hc.get("open_interest") is not None and (not c.oi or c.oi[-1][0] < hc["at"]):
                c.oi.append((hc["at"], hc["open_interest"]))
                c.oi = c.oi[-500:]
            if coin == pr.get("flow_instrument"):
                try:
                    c.flow.append(self.hl.flow(coin))
                    c.flow = c.flow[-30:]
                except HLError:
                    c.flow.append({"t": time.time(), "connected": False})
            szd = cat[coin]["szDecimals"]
            q = 10 ** -(max(0, 6 - szd - 1)) if szd is not None else 0.0          # price quantum ~ 5 significant figures rule (approximation for b)
            px = (self.hl_ctx.get(coin) or {}).get("mark")
            if px:
                q = 10 ** (math.floor(math.log10(px)) - 4)
            spec = {k: {"szDecimals": v["szDecimals"]} for k, v in cat.items() if k in (pr.get("instruments") or []) + ["BTC", "ETH"]}
            exposure = [{**d, "instrument": d.get("instrument"), "kind": d.get("kind", "PERP")} for d in self.ledger.declared("CRYPTO_FOMO_PERPS")]
            hb = {}
            for sym in {coin, "BTC", "ETH"} | {d["instrument"] for d in exposure if d.get("instrument")}:
                if sym in cat:
                    hb[sym] = {"M15": self._hl_bars(c, sym, "M15", 300)}
            feats = {}
            if coin != "BTC":
                bb = self._hl_bars(c, "BTC", "M5", 300)
                if bb:
                    bench["M5"] = D.build(bb, q)
                    feats[("BTC", "M5")] = bench["M5"]
            b1 = self._hl_bars(c, "BTC", "M1", 400)
            if b1:
                feats[("BTC", "M1")] = D.build(b1, 10 ** (math.floor(math.log10(b1[-1]["c"])) - 4))
            e5 = self._hl_bars(c, "ETH", "M5", 300)
            if e5:
                feats[("ETH", "M5")] = D.build(e5, 10 ** (math.floor(math.log10(e5[-1]["c"])) - 4))
            extra = {"exposure": exposure, "spec": spec, "bars": hb, "feats": feats, "bench": bench.get("M5"),
                     "funding": {k: (self.hl_ctx.get(k) or {}).get("funding_rate") for k in ("BTC", "ETH")}, "fees": pr.get("fees") or {},
                     "pair_map": pair_map, "same_underlying": same_underlying, "symbol": coin,
                     "market": {"mark": hc.get("mark"), "oracle": hc.get("oracle"), "funding_rate_1h": hc.get("funding_rate"), "open_interest": hc.get("open_interest")}}
            out[coin] = self._run_ctx(c, st, lambda tf, n=500, c=c, coin=coin: self._hl_bars(c, coin, tf, min(n, 500)), q, extra)
        return out

    # 1.46: the dead `_otc` scanner and the OTC feed reader (retired in TASK 020, never called by cycle()) were removed

    # ------------------------------------------------------------------ evaluation
    def _regime(self, F: D.Feat) -> dict:
        i = F.i
        adx = F.ADX(i)
        bb = F.bb(i)
        bws = [(F.bb(k) or {}).get("bw") for k in range(max(20, i - 120), i)]
        bws = sorted(x for x in bws if x is not None)
        comp = bb is not None and bb.get("bw") is not None and bws and bb["bw"] <= bws[int(0.2 * (len(bws) - 1))]
        tr, how = F.trend(i)
        if comp:
            r = "COMPRESSION"
        elif adx is not None and adx >= 25 and tr != 0:
            r = "TREND"
        elif adx is not None and adx < 20:
            r = "RANGE"
        else:
            r = "TREND" if tr != 0 else "RANGE"
        return {"regime": r, "adx": adx, "trend": tr, "trend_basis": how, "bandwidth": (bb or {}).get("bw")}

    def _run_ctx(self, c: Ctx, st: dict, bars_fn, quantum: float, extra: dict) -> dict:
        prof = c.profile
        pst = st["profiles"][prof]
        strats = [s for s in CAT.CATALOG if s["profile_id"] == prof]
        scope = {"profile": prof, "venue": CAT.PROFILES[prof]["venue"], "environment": "LIVE_DATA", "product": CAT.PROFILES[prof]["products"][0],
                 "instrument": c.instrument}
        strats, snap = self.sfb.filter(strats, scope)       # TASK 018: OFF = unchanged; ASSIST = only ELIGIBLE (never adds anything)
        c.sfb = ({**{k: snap.get(k) for k in ("snapshot_id", "bucket_key", "mode", "bucket_status")},
                  "items": {k: v["eligibility_status"] for k, v in snap["items"].items()}} if snap else None)
        if not strats:
            c.data_state, c.reason = "NO_TRADE_BUCKET", "SFB ASSIST: brak strategii ELIGIBLE w tym zakresie"
            return {"state": "NO_TRADE_BUCKET"}
        tfs = sorted({s["signal_timeframe"] for s in strats} | {t for s in strats for t in s["context_timeframes"]}, key=lambda t: TF_S[t])
        bars = {tf: bars_fn(tf, 600) for tf in tfs}
        new_tfs = []
        for tf, b in bars.items():
            if b and c.last_bar.get(tf) != b[-1]["t"]:
                c.last_bar[tf] = b[-1]["t"]
                if len(b) >= 30:
                    c.feats[tf] = D.build(b, quantum)
                new_tfs.append(tf)
        main = next((tf for tf in ("M5", "S15", "M1") if tf in c.feats), None)
        if main is None:
            c.data_state, c.reason = "WAITING_FOR_DATA", "brak zamkniętych świec"
            return {"state": "WAITING_FOR_DATA"}
        c.data_state, c.reason = "READY", None
        c.regime = self._regime(c.feats[main])
        self._track(c, bars)
        sel = pst.get("selection", "AUTO")
        manual = set((st.get("manual_select") or {}).get(prof) or [])
        found = []
        for s in strats:
            sid, tf = s["strategy_id"], s["signal_timeframe"]
            if not self.strat_enabled(s, st):
                c.state[sid] = {"state": "DISABLED"}
                continue
            if s["kind"] == "HEDGING":
                if tf in new_tfs or sid not in self.hedge_state:
                    self._hedge(c, s, st, extra)
                continue
            if sel == "OFF" or (sel == "MANUAL_SELECT" and sid not in manual):
                c.state[sid] = {"state": "NOT_SELECTED", "reason": f"wybór strategii: {sel}"}
                continue
            F = c.feats.get(tf)
            if F is None:
                c.state[sid] = {"state": "WAITING_FOR_DATA", "reason": f"brak zamkniętych świec {tf} z właściwego źródła"}
                continue
            if F.n < s["min_history"]:
                c.state[sid] = {"state": "WARMUP", "reason": f"{F.n}/{s['min_history']} świec {tf}"}
                continue
            if tf not in new_tfs:
                continue
            if sel == "AUTO" and s["correlation_group"] not in REGIME_GROUPS[c.regime["regime"]]:
                c.state[sid] = {"state": "NO_SETUP", "reason": f"reżim {c.regime['regime']} – reguła poza routingiem AUTO"}
                continue
            x = {"htf": c.feats.get(s["context_timeframes"][0]) if s["context_timeframes"] else None,
                 "htf2": c.feats.get(s["context_timeframes"][1]) if len(s["context_timeframes"]) > 1 else None,
                 "bench": extra.get("bench"), "oi": c.oi, "flow": c.flow, "now": time.time()}
            p = self.params(s, st)
            fam = RL.FAMILIES[s["family_id"]]
            hit = None
            try:
                for side in (1, -1):
                    r = fam(F, side, p, x)
                    if r:
                        hit = (side, r)
                        break
            except RL.Unavailable as exc:
                c.state[sid] = {"state": "WAITING_FOR_DATA", "reason": str(exc), "missing": True}
                continue
            except Exception as exc:  # noqa: BLE001 - one broken rule = ERROR of that strategy only
                c.state[sid] = {"state": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
                continue
            if not hit:
                c.state[sid] = {"state": "NO_SETUP", "bar_t": F.t[F.i]}
                continue
            found.append((s, F, hit[0], hit[1], p))
        published = self._resolve(c, found, st, extra)
        return {"state": "READY", "regime": c.regime, "setups": len(found), "published": published}

    # ------------------------------------------------------------------ plans, dedupe, conflicts
    def _event_id(self, c: Ctx, tf: str, side: int, ev: dict, F: D.Feat) -> str:
        b = F.b() or 1.0
        lvl = None if ev.get("level") is None else round(ev["level"] / b)
        raw = f"{c.key}|{tf}|{ev['type']}|{lvl}|{int(ev['t'])}|{side}"
        return "EV-" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _plan(self, c: Ctx, s: dict, F: D.Feat, side: int, r: dict, p: dict, st: dict, extra: dict) -> dict:
        prof = s["profile_id"]
        cap = st["profiles"][prof].get("capital") or {}
        # 1.46: the FixedExpiryPlan (OTC) branch was removed - OTC retired (TASK 020), no active strategy has that plan type
        entry, sl = r["entry"], r["sl"]
        R = abs(entry - sl)
        tp_r = p.get("tp_r", [2.0, 3.0])
        tg = [entry + side * k * R for k in tp_r]
        if r.get("target") is not None and (r["target"] - entry) * side > 0:
            tg = [r["target"]] + ([r["target2"]] if r.get("target2") is not None and (r["target2"] - r["target"]) * side > 0 else [])
        qty, unit = None, None
        rm = cap.get("risk_money")
        if rm:
            if prof == "CRYPTO_FOMO_PERPS":
                szd = ((extra.get("spec") or {}).get(c.instrument) or {}).get("szDecimals")
                if szd is not None and R > 0:
                    qty, unit = math.floor(float(rm) / R * 10 ** szd) / 10 ** szd, c.instrument
            else:
                br = getattr(self.rt, "bridge", None)
                try:
                    pl = br.calc_profit("BUY" if side > 0 else "SELL", 1.0, entry, sl) if br else None
                except Exception:  # noqa: BLE001
                    pl = None
                info = getattr(br, "symbol_info", None) or {}
                stp = float(info.get("volume_step") or 0.01)
                if pl:
                    qty, unit = math.floor(float(rm) / abs(pl) / stp) * stp or None, "lots"
        plan = {"plan_type": s["plan_type"], "version": 1, "side": "LONG" if side > 0 else "SHORT", "entry_ref": entry, "entry_basis": "close potwierdzającej świecy; wykonanie po bieżącej cenie",
                "sl": sl, "targets": [{"price": t, "weight": 0.5 if len(tg) > 1 else 1.0} for t in tg], "partials": "50% / 50%" if len(tg) > 1 else "jedno wyjście",
                "timeout_bars": int(r.get("timeout_bars") or p.get("timeout_bars", 8)), "timeframe": s["signal_timeframe"], "quantity": qty, "unit": unit,
                "quantity_reason": None if qty else "brak skonfigurowanego kapitału / ryzyka profilu – ilość nie jest zgadywana",
                "risk_per_unit": R, "be_trailing": "tylko wg jawnej konfiguracji"}
        if prof == "CRYPTO_FOMO_PERPS":
            mk = extra.get("market") or {}
            plan.update(trigger_price_basis="MARK", mark=mk.get("mark"), oracle=mk.get("oracle"), funding_rate_1h=mk.get("funding_rate_1h"),
                        collateral="USDC", leverage=None, margin_mode=None, liquidation="wg FOMO po ustawieniu dźwigni (nie zmieniana przez bota)",
                        fees_note="prowizje FOMO + protokołu po obu stronach; funding osobno (bez podwójnego liczenia)")
        return plan

    def _scores(self, c: Ctx, s: dict, F: D.Feat, side: int, r: dict, plan: dict) -> dict:
        """setup_score (explicit, 0-100): 25 HTF alignment + 25 room to target (>= 2R full) + 25 confirmation on the closed bar +
        25 data completeness (all required inputs real). model_agreement / p_event_raw separate; never raised by duplicate detectors."""
        comp = {}
        h = None
        if s["context_timeframes"]:
            h = c.feats.get(s["context_timeframes"][0])
        comp["htf_alignment"] = 25 if h is not None and h.trend()[0] == side else 0
        if plan.get("targets"):
            rr = abs(plan["targets"][0]["price"] - plan["entry_ref"]) / max(plan["risk_per_unit"], 1e-12)
            comp["room"] = round(min(25.0, 12.5 * rr), 1)
        else:
            comp["room"] = None
        comp["confirmation"] = 25
        comp["data"] = 25
        score = sum(v for v in comp.values() if v is not None)
        scale = sum(25 for v in comp.values() if v is not None)
        out = {"setup_score": round(100 * score / scale, 1) if scale else None, "setup_components": comp, "model_agreement": None, "p_event_raw": None,
               "p_event_calibrated": None, "calibration_status": "UNCALIBRATED"}
        out.update(self._score_info(s, h, comp))
        if s["profile_id"] == "FOREX_MT5" and s["plan_type"] == "PositionPlan":
            out.update(self._quant(c, s, side, plan))
        return out

    @staticmethod
    def _score_info(s: dict, h, comp: dict) -> dict:
        """1.46 (I0718, informational only): setup_score above is computed exactly as in 1.46.0 - a declared but missing HTF context
        counts 0 and 'confirmation' / 'data' are constants of 25 - because it ranks the plans of one event, is the SH score and the Quant
        feature ctx:heuristic_score. Changing it would change which plan reaches SH / which Quant hold applies, so the honest reading is
        shown NEXT to it: the basis of every component, a DATA_INCOMPLETE flag and a score of the measured components only."""
        declared = bool(s["context_timeframes"])
        htf = ("NOT_DECLARED" if not declared else "MISSING_CONTEXT" if h is None else "ALIGNED" if comp["htf_alignment"] else "NOT_ALIGNED")
        measured = {"room": comp["room"]} if comp["room"] is not None else {}
        if htf in ("ALIGNED", "NOT_ALIGNED"):
            measured["htf_alignment"] = comp["htf_alignment"]
        return {"setup_flags": ["DATA_INCOMPLETE"] if htf == "MISSING_CONTEXT" else [],
                "setup_components_basis": {"htf_alignment": htf, "room": "MEASURED" if comp["room"] is not None else "NO_TARGET",
                                           "confirmation": "CONSTANT_25 (brak definicji – stała, nie pomiar)",
                                           "data": "CONSTANT_25 (brak definicji – stała, nie pomiar)"},
                "setup_score_measured": round(100 * sum(measured.values()) / (25 * len(measured)), 1) if measured else None,
                "setup_score_note": "setup_score (ranking zdarzenia, wynik w SH, cecha Quant) liczony jak w 1.46.0: brak kontekstu HTF = 0, "
                                    "confirmation / data = stałe 25; setup_score_measured = tylko zmierzone składniki – informacyjnie, "
                                    "nie wpływa na ranking ani na wejścia"}

    def _quant(self, c: Ctx, s: dict, side: int, plan: dict) -> dict:
        q = getattr(self.rt, "quant", None)
        if q is None:
            return {}
        try:
            cd = {"engine": f"BASKET_{s['basket_id']}", "strategy_id": s["strategy_id"], "instrument": q.instrument(), "direction": plan["side"],
                  "entry_price": plan["entry_ref"], "stop_loss": plan["sl"], "targets": plan["targets"], "horizon_s": plan["timeout_bars"] * TF_S[plan["timeframe"]],
                  "decision_ts": time.time(), "candidate_key": f"{s['strategy_id']}|{plan['entry_ref']}"}
            a = q.assess(cd, log_row=False)
            conf = a.get("confidence") or {}
            ev_id = (a.get("event") or {}).get("event_id")
            # 1.46 (I0539): the Quant event id (text, e.g. TP1_BEFORE_STOP) is 'quant_event_id' - NOT 'event_id' (that is the basket event of
            # the signal) and not a probability. 'p_event' = the same value, a deprecated alias kept for one version (ledger rows / readers)
            return {"p_event_raw": conf.get("p_event_raw"), "confidence_state": conf.get("state"), "confidence_source": "TabICLv2 (Quant)",
                    "quant_event_id": ev_id, "p_event": ev_id}
        except Exception as exc:  # noqa: BLE001
            return {"confidence_state": "ERROR", "confidence_reason": f"{type(exc).__name__}: {exc}"[:120]}

    def _resolve(self, c: Ctx, found: list, st: dict, extra: dict) -> int:
        """One primary plan per event id (ranked by setup_score), the rest = justifications; opposite directions on the same context /
        bar -> CONFLICT (WAIT), nothing published; basket limits (open groups / pending) and cooldown respected."""
        if not found:
            return 0
        sides = {h[2] for h in found}
        now = time.time()
        if len(sides) > 1:
            for s, F, side, r, p in found:
                c.state[s["strategy_id"]] = {"state": "CONFLICT", "reason": "przeciwne kierunki SMC/SCALP w tym samym kontekście – WAIT", "bar_t": F.t[F.i]}
            return 0
        groups: dict[str, list] = {}
        for s, F, side, r, p in found:
            groups.setdefault(self._event_id(c, s["signal_timeframe"], side, r["event"], F), []).append((s, F, side, r, p))
        n = 0
        open_ = self.ledger.open_signals(c.profile)
        for eid, items in groups.items():
            ranked = []
            for s, F, side, r, p in items:
                plan = self._plan(c, s, F, side, r, p, st, extra)
                sc = self._scores(c, s, F, side, r, plan)
                ranked.append((sc.get("setup_score") or 0, s, F, side, r, p, plan, sc))
            ranked.sort(key=lambda x: -x[0])
            _, s, F, side, r, p, plan, sc = ranked[0]
            b = st["baskets"][s["basket_id"]]
            mine = [o for o in open_ if o["basket_id"] == s["basket_id"]]
            if len(mine) >= int(b.get("max_pending_intents", 3)):
                c.state[s["strategy_id"]] = {"state": "LIMIT", "reason": f"limit aktywnych planów koszyka ({len(mine)})"}
                continue
            if any(o["strategy_id"] == s["strategy_id"] and F.t[F.i] - float(o["bar_t"]) < int(b.get("cooldown_bars", 3)) * TF_S[s["signal_timeframe"]] for o in mine):
                c.state[s["strategy_id"]] = {"state": "COOLDOWN"}
                continue
            sig = {"signal_id": f"{eid}|{s['strategy_id']}", "event_id": eid, "strategy_id": s["strategy_id"], "basket_id": s["basket_id"], "profile_id": c.profile,
                   "context_key": c.key, "instrument": c.instrument, "tf": s["signal_timeframe"], "side": plan.get("side") or plan.get("direction"),
                   "created_at": now, "bar_t": F.t[F.i], "status": "ACTIVE", "role": "PRIMARY",
                   "plan": {**plan, "execution": CAT.PROFILES[c.profile]["execution_capability"], "execution_status": self._exec_status(c, plan, st)},
                   "setup": {**r, "justifications": [x[1]["strategy_id"] for x in ranked[1:]], "regime": c.regime,
                             # CHARTS K3: was the rule inside the AUTO regime routing at signal time (MANUAL_SELECT may publish outside it)
                             "routed_auto": s["correlation_group"] in REGIME_GROUPS.get(c.regime.get("regime"), set())}, "scores": sc,
                   **({"sfb": {**{k: v for k, v in c.sfb.items() if k != "items"}, "eligibility_status": c.sfb["items"].get(s["strategy_id"])}}
                      if c.sfb else {})}
            if self.ledger.add_signal(sig):
                n += 1
                self._publish(sig)
            c.state[s["strategy_id"]] = {"state": "SIGNAL", "event_id": eid, "side": sig["side"], "bar_t": F.t[F.i]}
            for x in ranked[1:]:
                c.state[x[1]["strategy_id"]] = {"state": "DUPLICATE_EVENT", "primary": s["strategy_id"], "event_id": eid}
        return n

    @staticmethod
    def _exec_status(c: Ctx, plan: dict, st: dict) -> str:
        if c.profile == "FOREX_MT5" and plan.get("plan_type") == "PositionPlan" and \
                (st["profiles"]["FOREX_MT5"].get("execution") or "AUTO_SH") == "AUTO_SH":
            return "PRZEKAZANY DO ŚCIEŻKI SH (zlecenie wg trybu wykonania, ryzyka i STOP)"
        return "SIGNAL (bez zlecenia)"

    # ------------------------------------------------------------------ 1.42: hand-off to the SH execution path
    def sh_candidates(self, symbol: str, now: float | None = None) -> list[dict]:
        """ACTIVE FOREX_MT5 PositionPlans on `symbol` that were not handed over yet and are still fresh (<= 3 signal bars, max 30 min).
        Conflicts / duplicates were already resolved in _resolve (one primary plan per event)."""
        if self.sfb_blocked:                              # rejected sfb.json: 1.45 had no BasketService -> no basket plan reached SH
            return []
        st = self.settings()
        if (st["profiles"]["FOREX_MT5"].get("execution") or "AUTO_SH") != "AUTO_SH" or not st["profiles"]["FOREX_MT5"].get("enabled", True):
            return []
        now = time.time() if now is None else now
        done = self.ledger.executed()
        out = []
        for sg in self.ledger.open_signals("FOREX_MT5"):
            pl = sg.get("plan") or {}
            if sg["signal_id"] in done or sg.get("instrument") != symbol or pl.get("plan_type") != "PositionPlan" or sg.get("role") != "PRIMARY":
                continue
            ttl = min(3 * TF_S.get(sg["tf"], 300), 1800)
            if now - float(sg["created_at"]) > ttl:
                continue
            out.append({**sg, "valid_until": float(sg["created_at"]) + ttl})
        return out

    def _publish(self, sig: dict) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is not None:
            try:
                bus.publish("basket_signal", {k: sig[k] for k in ("signal_id", "strategy_id", "basket_id", "profile_id", "instrument", "tf", "side", "created_at")})
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ SIGNAL_SIMULATION tracking
    def _track(self, c: Ctx, bars: dict) -> None:
        for sg in self.ledger.open_signals(c.profile):
            if sg["context_key"] != c.key:
                continue
            pl = sg["plan"] or {}
            if pl.get("plan_type") == "FixedExpiryPlan":
                continue                                  # 1.46: retired OTC plan type - dead branch removed (FOREX / CRYPTO contexts only)
            series = bars.get(sg["tf"]) or []
            if series and series[0]["t"] > float(sg["bar_t"]) + TF_S[sg["tf"]]:
                # 1.46: the loaded window starts after the bar that follows the signal (downtime longer than the window): the bars right
                # after the signal are unknown, a SL / TP / TIMEOUT from a later bar would be a guess -> UNKNOWN (missing data is never guessed)
                self.ledger.update(sg["signal_id"], status="CLOSED", outcome_kind="UNKNOWN", outcome_at=time.time(),
                                   outcome={"kind": "SIGNAL_SIMULATION", "reason": "luka w danych: brak świec bezpośrednio po sygnale w oknie danych – "
                                                                                     "wynik nieznany (nie zgaduję SL / TP / TIMEOUT)"})
                continue
            b = [x for x in series if x["t"] > float(sg["bar_t"])]
            side = 1 if pl.get("side") == "LONG" else -1
            sl, tg = float(pl["sl"]), [float(t["price"]) for t in pl.get("targets") or []]
            res = None
            for k, x in enumerate(b):
                hit_sl = (x["l"] <= sl) if side > 0 else (x["h"] >= sl)
                hit_tp = bool(tg) and ((x["h"] >= tg[0]) if side > 0 else (x["l"] <= tg[0]))
                if hit_sl:
                    res = ("SL", x["t"])                                           # SL first when both in one bar (conservative)
                    break
                if hit_tp:
                    res = ("TP1", x["t"])
                    break
                if k + 1 >= int(pl.get("timeout_bars") or 8):
                    res = ("TIMEOUT", x["t"])
                    break
            if res:
                self.ledger.update(sg["signal_id"], status="CLOSED", outcome_kind=res[0], outcome_at=res[1],
                                   outcome={"kind": "SIGNAL_SIMULATION", "note": "przebieg sygnału na zamkniętych świecach (nie fill, nie PnL konta)"})

    # ------------------------------------------------------------------ hedge
    def _hedge(self, c: Ctx, s: dict, st: dict, extra: dict) -> None:
        F = c.feats.get(s["signal_timeframe"])
        sid = s["strategy_id"]
        if F is None:
            c.state[sid] = {"state": "WAITING_FOR_DATA", "reason": f"brak świec {s['signal_timeframe']}"}
            return
        ctx = {"strategy": s, "p": self.params(s, st), "F": F, "htf": c.feats.get(s["context_timeframes"][0]) if s["context_timeframes"] else None,
               "now": time.time(), **extra}
        try:
            r = HG.PLANNERS[s["family_id"]](ctx)
        except RL.Unavailable as exc:
            why = self._unsupplied_input(s, ctx)
            r = {"state": "UNSUPPORTED_INPUT", "reason": why, "detail": str(exc)} if why else {"state": "WAITING_FOR_DATA", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001
            r = {"state": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}
        legs = [lg.get("instrument") for lg in ((r.get("plan") or {}).get("legs") or []) if isinstance(lg, dict)]
        if s["profile_id"] == "CRYPTO_FOMO_PERPS" and r.get("state") == "HEDGE_PLAN" and any(_research_only(x) for x in legs):
            # 1.46: a Trade[XYZ] market (INDICES / FOMO_STOCK_PERPS) is RESEARCH_ONLY - never a hedge leg / manual ticket
            r = {"state": "NO_HEDGE", "reason": f"RESEARCH_ONLY_MARKET: noga {[x for x in legs if _research_only(x)]} na rynku tylko do badań"}
        r["evaluated_at"] = time.time()
        self.hedge_state[sid] = r
        c.state[sid] = {"state": r["state"], "reason": r.get("reason")}
        if r["state"] == "HEDGE_PLAN":
            pid = "HP-" + hashlib.sha256(f"{sid}|{json.dumps(r.get('plan'), sort_keys=True, default=str)}".encode()).hexdigest()[:14]
            self.ledger.add_hedge({"plan_id": pid, "strategy_id": sid, "basket_id": s["basket_id"], "profile_id": s["profile_id"], "created_at": time.time(),
                                   "state": "PROPOSED", "reason": r.get("reason"), "plan": r.get("plan")})

    @staticmethod
    def _unsupplied_input(s: dict, ctx: dict) -> str | None:
        """1.46: inputs the FOREX context never supplies -> the planner can never plan. FX_HEDGE_08/09/10 read ctx['bars'] (M15 of other
        symbols - the service reads only the bot's symbol from MT5), FX_HEDGE_04 reads spec['spread_median_price'] (never computed). They
        were WAITING_FOR_DATA with a false reason ("XAGUSD niedostępny w terminalu", "brak bieżącego ... spreadu")."""
        fam = s["family_id"]
        if fam in ("beta_pair", "pair_relative", "min_variance") and "bars" not in ctx:
            return "UNSUPPORTED_INPUT: serwis koszyków nie pobiera świec M15 innych symboli z MT5 (tylko symbol bota) – planer nie ma danych do relacji"
        if fam == "session_transition" and not any(isinstance(v, dict) and v.get("spread_median_price") is not None for v in (ctx.get("spec") or {}).values()):
            return "UNSUPPORTED_INPUT: serwis koszyków nie liczy referencyjnej mediany spreadu – planer nie ma progu porównania"
        return None

    # ------------------------------------------------------------------ views
    def _ctxs(self, prof: str | None = None) -> list[Ctx]:
        """1.46: snapshot taken under the lock - the API threads iterated self.ctx while the basket thread added contexts
        ("dictionary changed size during iteration" -> HTTP 500 on GET /api/v1/baskets)."""
        with self._lock:
            return [c for c in list(self.ctx.values()) if prof is None or c.profile == prof]

    def basket_view(self, basket: str | None = None) -> list[dict]:
        st = self.settings()
        stats = self.ledger.stats()
        out = []
        for b in CAT.baskets():
            if basket and b["basket_id"] != basket:
                continue
            cfg = st["baskets"][b["basket_id"]]
            prof = b["profile_id"]
            ctxs = self._ctxs(prof)
            rows = []
            for sid in b["strategy_ids"]:
                s = CAT.BY_ID[sid]
                states = {c.instrument: c.state.get(sid) for c in ctxs if sid in c.state}
                rows.append({"strategy_id": sid, "name": s["name"], "enabled": self.strat_enabled(s, st), "tf": s["signal_timeframe"],
                             "context": s["context_timeframes"], "family": s["family_id"], "states": states, "hedge": self.hedge_state.get(sid)})
            counts = {}
            for r in rows:
                for v in (r["states"] or {}).values():
                    k = (v or {}).get("state", "?")
                    counts[k] = counts.get(k, 0) + 1
            out.append({**b, "enabled": cfg.get("enabled", True), "config": cfg, "mode": st["profiles"][prof].get("selection"),
                        "data_status": {c.instrument: {"state": c.data_state, "reason": c.reason, "regime": c.regime} for c in ctxs} or
                        {"-": {"state": "WAITING_FOR_DATA", "reason": "profil jeszcze nie odczytał danych" if st["profiles"][prof].get("enabled", True) else "profil wyłączony"}},
                        "active_strategy_count": sum(1 for r in rows if r["enabled"]), "status_counts": counts, "strategies": rows,
                        "ledger": stats.get(b["basket_id"], {}), "reserved_risk": None,
                        "execution_note": CAT.PROFILES[prof]["execution_note"]})
        return out

    def status(self) -> dict:
        st = self.settings()
        return {"catalog": CAT.validate(), "version": CAT.VERSION, "activation_policy": st["activation_policy"], "active_profile": st["active_profile"],
                "profiles": {p: {**CAT.PROFILES[p], "enabled": st["profiles"][p].get("enabled", True), "selection": st["profiles"][p].get("selection"),
                                 "contexts": [{"key": c.key, "instrument": c.instrument, "data_state": c.data_state, "reason": c.reason, "regime": c.regime}
                                              for c in self._ctxs(p)], "error": self.loop["profile_errors"].get(p)} for p in CAT.PROFILES},
                "otc_feed": {"state": "RETIRED", "reason": "RETIRED_PROFILE", "history": "READ_ONLY"}, "retired": CAT.manifest()["retired"], "hyperliquid": {"errors": self.hl.errors, "last_error": self.hl.last_error, "capabilities": __import__(
                    "masterquo.baskets.hyperliquid", fromlist=["CAPABILITIES"]).CAPABILITIES}, "loop": dict(self.loop),
                "counts": {"implemented": len(CAT.CATALOG), "executable_now": sum(1 for c in self._ctxs() for v in c.state.copy().values()   # 1.46: copy
                                                                                    if (v or {}).get("state") in ("NO_SETUP", "SIGNAL", "DUPLICATE_EVENT", "CONFLICT", "NO_HEDGE", "HEDGE_PLAN", "NO_EXPOSURE", "COOLDOWN", "LIMIT"))}}
