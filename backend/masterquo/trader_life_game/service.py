"""TraderLifeGame service (TASK 019): local-first, single local profile, EXECUTION_ISOLATED.

Storage: its own SQLite file (<data>/trader_life_game/game.sqlite) - a separate game domain, never the trading DB tables.
Ledgers are append-only with UNIQUE idempotency keys: XP, Trader Gold, verified activity events, quest claims.

Hard boundary: the service receives only a ReadOnlyAccountView (deals / account snapshot / closed bars). It has no reference to the
bridge, the MT5 worker, the execution engine, risk, STOP, baskets or strategies - there is no code path that can send / modify / close an
order, change SL/TP, lot, leverage, risk, STOP, execution mode, strategy or SFB eligibility.

Separate typed money/progress domains, never added together: real_balance/real_equity (MT5 snapshot), realized_pnl (MT5 deals),
virtual_balance + simulated_pnl (simulator), trader_gold (cosmetic), xp (progression).
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import content as C

SCHEMA_VERSION = 1
PROVENANCE = ("MT5_REAL", "USER_NOTE", "SIMULATOR", "ACADEMY", "AI_COACH", "RULES_COACH", "DEMO_FIXTURE")


class GameError(ValueError):
    """Validation / state error with a machine-readable code (API -> 400/404/409)."""

    def __init__(self, code: str, detail: str = "", status: int = 400):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail, self.status = code, detail, status


class ReadOnlyAccountView:
    """The ONLY window of the game onto the trading side: three read functions. Any other attribute access raises PermissionError,
    so even a bug cannot reach order_send / position modify / risk / STOP through this object."""

    __slots__ = ("_deals", "_account", "_bars")

    def __init__(self, deals=None, account=None, bars=None):
        # 1.46: no deal source = deal history UNAVAILABLE (None), not "0 trades" ([])
        object.__setattr__(self, "_deals", deals or (lambda: None))
        object.__setattr__(self, "_account", account or (lambda: None))
        object.__setattr__(self, "_bars", bars or (lambda symbol, tf, count: []))

    @classmethod
    def from_bridge(cls, bridge):
        if bridge is None:
            return cls()

        def deals():
            with bridge._lock:
                # 1.46: bridge.deals is [] until the first successful history read (deals_loaded_at None) - that is "not loaded",
                # never "no trades"; a bridge object without the attribute keeps the previous behaviour
                if getattr(bridge, "deals_loaded_at", True) is None:
                    return None
                return [dict(d) for d in (bridge.deals or [])]

        def account():
            a = bridge.account_status()
            return dict(a) if a else None

        def bars(symbol, tf, count):
            return [dict(b) for b in (bridge.symbol_bars(symbol, tf, count) or [])]
        return cls(deals, account, bars)

    def deals(self) -> list[dict] | None:
        """Canonical MT5 deals, or None when the history is not available (no bridge / not loaded yet)."""
        return self._deals()

    def account(self) -> dict | None:
        return self._account()

    def bars(self, symbol: str, tf: str, count: int) -> list[dict]:
        return self._bars(symbol, tf, count)

    def __setattr__(self, k, v):
        raise PermissionError("READ_ONLY_ACCOUNT_VIEW")

    def __getattr__(self, k):
        raise PermissionError(f"READ_ONLY_ACCOUNT_VIEW: '{k}' is not available to TraderLifeGame")


_DDL = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id = 1), username TEXT NOT NULL, class_id TEXT NOT NULL, difficulty TEXT NOT NULL,
  currency TEXT NOT NULL, virtual_capital REAL NOT NULL, leaderboard_opt_in INTEGER NOT NULL DEFAULT 0, anonymize INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, ts REAL NOT NULL,
  day TEXT NOT NULL, week TEXT NOT NULL, source TEXT NOT NULL, payload TEXT);
CREATE INDEX IF NOT EXISTS ix_events_kind_day ON events(kind, day);
CREATE TABLE IF NOT EXISTS xp_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, ts REAL NOT NULL, amount INTEGER NOT NULL,
  reason TEXT NOT NULL, ref TEXT);
CREATE TABLE IF NOT EXISTS gold_ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, ts REAL NOT NULL, amount INTEGER NOT NULL,
  reason TEXT NOT NULL, ref TEXT);
CREATE TABLE IF NOT EXISTS skills(skill_id TEXT PRIMARY KEY, unlocked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quest_claims(key TEXT PRIMARY KEY, quest_id TEXT NOT NULL, period TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS academy(lesson_id TEXT PRIMARY KEY, completed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS quiz(id INTEGER PRIMARY KEY AUTOINCREMENT, level INTEGER NOT NULL, ts REAL NOT NULL, score REAL NOT NULL, passed INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS journal(ref TEXT PRIMARY KEY, data TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ts REAL NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, tf TEXT NOT NULL, bars TEXT NOT NULL,
  cursor INTEGER NOT NULL, start_cursor INTEGER NOT NULL, status TEXT NOT NULL, virtual_start REAL NOT NULL, provenance TEXT NOT NULL,
  created_at REAL NOT NULL, finished_at REAL);
CREATE TABLE IF NOT EXISTS sim_trades(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, side TEXT NOT NULL, size REAL NOT NULL,
  entry REAL NOT NULL, sl REAL, tp REAL, opened_idx INTEGER NOT NULL, closed_idx INTEGER, exit REAL, pnl REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS inventory(item_id TEXT PRIMARY KEY, acquired_at REAL NOT NULL, equipped INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS coach_memory(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL);
"""


def level_for_xp(xp: int) -> int:
    lvl = 1
    while lvl < C.MAX_LEVEL and xp >= xp_to_reach(lvl + 1):
        lvl += 1
    return lvl


def xp_to_reach(level: int) -> int:
    return 0 if level <= 1 else int(round(C.XP_BASE * (level - 1) ** C.XP_EXP))


def rank_for(level: int) -> str:
    for top, name in C.RANKS:
        if level <= top:
            return name
    return C.RANKS[-1][1]


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _week(ts: float) -> str:
    y, w, _ = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


class _Result:
    """Rows fetched while the lock was held (the shared cursor is never read outside it)."""
    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, rows, lastrowid, rowcount):
        self._rows, self.lastrowid, self.rowcount = rows, lastrowid, rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _LockedConnection:
    """1.46: the game's one SQLite connection is shared by the API threads. 1.45.0 ran most reads and several writes without the lock:
    parallel /tlg/state, /tlg/quests and /tlg/skills of one panel interleaved statements on it (InterfaceError -> 500, a missing profile row
    -> a false NO_PROFILE / needs_character). Every statement now runs - and is fetched - under the service RLock."""

    def __init__(self, conn: sqlite3.Connection, lock):
        self._conn, self._lock = conn, lock

    def execute(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
            return _Result(rows, cur.lastrowid, cur.rowcount)

    def executescript(self, script):
        with self._lock:
            return self._conn.executescript(script)

    def close(self):
        with self._lock:
            self._conn.close()


class GameService:
    def __init__(self, data_dir: Path, account: ReadOnlyAccountView | None = None, clock=time.time):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.account = account if isinstance(account, ReadOnlyAccountView) else ReadOnlyAccountView()
        self.clock = clock
        self._lock = threading.RLock()
        conn = sqlite3.connect(str(self.dir / "game.sqlite"), check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        self.db = _LockedConnection(conn, self._lock)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_DDL)
        self.db.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))

    def close(self):
        self.db.close()

    # ------------------------------------------------------------------ helpers
    # 1.46: one connection shared by the API threads - reads ran without the lock; parallel /tlg/state, /quests, /skills of one panel
    # interleaved statements on it (InterfaceError -> 500, a missing profile row -> false NO_PROFILE / needs_character)
    def _q(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        with self._lock:
            r = self.db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def _profile(self, required=True):
        p = self._one("SELECT * FROM profile WHERE id = 1")
        if p is None and required:
            raise GameError("NO_PROFILE", "utwórz postać", 409)
        return p

    def xp_total(self) -> int:
        return int(self._one("SELECT COALESCE(SUM(amount), 0) s FROM xp_ledger")["s"])

    def gold_total(self) -> int:
        return int(self._one("SELECT COALESCE(SUM(amount), 0) s FROM gold_ledger")["s"])

    def _ledger(self, table: str, key: str, amount: int, reason: str, ref: str | None = None) -> bool:
        cur = self.db.execute(f"INSERT OR IGNORE INTO {table}(key, ts, amount, reason, ref) VALUES(?, ?, ?, ?, ?)",  # noqa: S608 - fixed names
                              (key, self.clock(), int(amount), reason, ref))
        return cur.rowcount == 1

    # ------------------------------------------------------------------ module 01: profile / character
    def classes(self) -> dict:
        return {"classes": C.CLASSES, "difficulties": C.DIFFICULTIES, "milestone_note": C.MILESTONE_NOTE, "attributes": C.ATTRIBUTES}

    def create_profile(self, body: dict) -> dict:
        with self._lock:
            if self._profile(required=False):
                raise GameError("PROFILE_EXISTS", "lokalny profil już istnieje – użyj edycji", 409)
            p = self._validate_profile(body, partial=False)
            now = self.clock()
            self.db.execute("INSERT INTO profile(id, username, class_id, difficulty, currency, virtual_capital, leaderboard_opt_in, anonymize, created_at, "
                            "updated_at) VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (p["username"], p["class_id"], p["difficulty"], p["currency"], p["virtual_capital"], int(p.get("leaderboard_opt_in", False)),
                             int(p.get("anonymize", True)), now, now))
            for it in C.DEFAULT_ITEMS:
                self.db.execute("INSERT OR IGNORE INTO inventory(item_id, acquired_at, equipped) VALUES(?, ?, 1)", (it, now))
            return self.state()

    def update_profile(self, body: dict) -> dict:
        with self._lock:
            cur = self._profile()
            p = self._validate_profile({**cur, **body}, partial=True)
            self.db.execute("UPDATE profile SET username=?, class_id=?, difficulty=?, currency=?, virtual_capital=?, leaderboard_opt_in=?, anonymize=?, "
                            "updated_at=? WHERE id = 1", (p["username"], p["class_id"], p["difficulty"], p["currency"], p["virtual_capital"],
                                                          int(bool(p.get("leaderboard_opt_in"))), int(bool(p.get("anonymize", True))), self.clock()))
            return self.state()

    @staticmethod
    def _validate_profile(b: dict, partial: bool) -> dict:
        name = str(b.get("username") or "").strip()
        if not (2 <= len(name) <= 32) or any(ch in name for ch in "<>\"'`"):
            raise GameError("INVALID_USERNAME", "2–32 znaki, bez < > \" ' `")
        if b.get("class_id") not in C.CLASSES:
            raise GameError("INVALID_CLASS", ", ".join(C.CLASSES))
        if b.get("difficulty") not in C.DIFFICULTIES:
            raise GameError("INVALID_DIFFICULTY", ", ".join(C.DIFFICULTIES))
        cur = str(b.get("currency") or "USD").upper()
        if not (cur.isalpha() and 3 <= len(cur) <= 5):
            raise GameError("INVALID_CURRENCY")
        try:
            cap = float(b.get("virtual_capital", 10_000))
        except (TypeError, ValueError):
            raise GameError("INVALID_VIRTUAL_CAPITAL") from None
        if not (100 <= cap <= 10_000_000) or math.isnan(cap):
            raise GameError("INVALID_VIRTUAL_CAPITAL", "100 – 10 000 000")
        return {"username": name, "class_id": b["class_id"], "difficulty": b["difficulty"], "currency": cur, "virtual_capital": cap,
                "leaderboard_opt_in": bool(b.get("leaderboard_opt_in", False)), "anonymize": bool(b.get("anonymize", True))}

    def attributes(self, prof: dict | None = None) -> dict:
        prof = prof or self._profile()
        a = dict(C.CLASSES[prof["class_id"]]["start"])
        expl = {k: [f"start klasy {C.CLASSES[prof['class_id']]['name']}: {v}"] for k, v in a.items()}
        for r in self._q("SELECT kind, COUNT(*) n FROM events GROUP BY kind"):
            for attr, d in C.ACTIVITIES.get(r["kind"], (0, {}))[1].items():
                a[attr] += d * r["n"]
                expl[attr].append(f"{r['kind']} × {r['n']} (+{d} każde)")
        return {"values": {k: min(100, v) for k, v in a.items()}, "explanation": expl}

    def state(self) -> dict:
        prof = self._profile()
        xp, gold = self.xp_total(), self.gold_total()
        lvl = level_for_xp(xp)
        acc = self._real_account()
        sim = self._one("SELECT COALESCE(SUM(pnl), 0) s FROM sim_trades WHERE pnl IS NOT NULL")["s"]
        return {"profile": {**prof, "class": C.CLASSES[prof["class_id"]]["name"], "difficulty_name": C.DIFFICULTIES[prof["difficulty"]]["name"],
                            "milestone": C.DIFFICULTIES[prof["difficulty"]]["milestone"], "milestone_note": C.MILESTONE_NOTE,
                            "intro": C.CLASSES[prof["class_id"]]["intro"]},
                "progress": {"xp": xp, "level": lvl, "rank": rank_for(lvl), "xp_level_start": xp_to_reach(lvl),
                             "xp_next_level": xp_to_reach(lvl + 1) if lvl < C.MAX_LEVEL else None},
                "attributes": self.attributes(prof)["values"],
                # separate domains - never summed
                "balances": {"trader_gold": gold, "xp": xp,
                             "virtual_balance": round(prof["virtual_capital"] + sim, 2), "simulated_pnl": round(sim, 2), "virtual_currency": prof["currency"],
                             "real_balance": acc.get("balance"), "real_equity": acc.get("equity"), "real_currency": acc.get("currency"),
                             "real_source": acc.get("source")},
                "execution": "ISOLATED (brak uprawnień do zleceń)", "content_version": C.CONTENT_VERSION}

    def _real_account(self) -> dict:
        try:
            a = self.account.account()
        except Exception:  # noqa: BLE001 - an MT5 outage never breaks the game
            a = None
        if not a:
            return {"balance": None, "equity": None, "currency": None, "source": "UNAVAILABLE"}
        return {"balance": a.get("balance"), "equity": a.get("equity"), "currency": a.get("currency"), "source": "MT5_REAL"}

    # ------------------------------------------------------------------ verified activity events + XP
    def _record(self, kind: str, key: str, source: str, payload: dict | None = None) -> dict:
        """Idempotent: the same key never records twice. XP = base x class bonus; daily caps stop farming of cheap activities."""
        if kind not in C.ACTIVITIES and kind not in ("RULE_COMPLIANT_REVIEW",):
            raise GameError("UNKNOWN_ACTIVITY", kind)
        prof = self._profile()
        now = self.clock()
        cur = self.db.execute("INSERT OR IGNORE INTO events(key, kind, ts, day, week, source, payload) VALUES(?, ?, ?, ?, ?, ?, ?)",
                              (key, kind, now, _day(now), _week(now), source, json.dumps(payload or {}, ensure_ascii=False)))
        if cur.rowcount != 1:
            return {"recorded": False, "xp": 0, "reason": "DUPLICATE_EVENT"}
        base = C.ACTIVITIES.get(kind, (0, {}))[0]
        cap = C.DAILY_ACTIVITY_CAP.get(kind)
        if cap is not None:
            n = self._one("SELECT COUNT(*) n FROM events WHERE kind = ? AND day = ?", (kind, _day(now)))["n"]
            if n > cap:
                return {"recorded": True, "xp": 0, "reason": "DAILY_CAP"}
        xp = int(round(base * C.CLASSES[prof["class_id"]]["xp_bonus"].get(kind, 1.0)))
        if xp:
            self._ledger("xp_ledger", f"evt:{key}", xp, kind, key)
        return {"recorded": True, "xp": xp}

    def xp_history(self, limit: int = 100) -> list[dict]:
        return self._q("SELECT ts, amount, reason, ref FROM xp_ledger ORDER BY id DESC LIMIT ?", (int(limit),))

    # ------------------------------------------------------------------ module 03: journal over canonical MT5 deals (read-only)
    def journal(self) -> dict:
        self._profile()
        try:
            deals = self.account.deals()
        except Exception:  # noqa: BLE001
            deals = None
        if deals is None:       # 1.46: history not loaded / no bridge / read error -> UNAVAILABLE with items null, never "MT5_REAL, 0 trades"
            return {"source": "UNAVAILABLE", "items": None,
                    "note": "historia transakcji MT5 niedostępna (terminal niepołączony lub historia jeszcze niewczytana) – brak danych, nie 0 transakcji"}
        src = "MT5_REAL"
        notes = {r["ref"]: json.loads(r["data"]) for r in self._q("SELECT ref, data FROM journal")}
        pos: dict[str, dict] = {}
        for d in sorted(deals, key=lambda x: (x.get("time") or 0, x.get("ticket") or 0)):
            t = d.get("type")
            if t not in (0, 1):                 # balance / credit / commission rows are not trades
                continue
            pid = str(d.get("position_id") or d.get("ticket"))
            p = pos.setdefault(pid, {"ref": f"MT5:{pid}", "position_id": pid, "symbol": d.get("symbol"), "deals": [], "opened": None, "closed": None,
                                     "side": None, "volume_in": 0.0, "volume_out": 0.0, "realized_pnl": 0.0, "costs": 0.0})
            if str(d.get("ticket")) in {str(x["ticket"]) for x in p["deals"]}:
                continue                         # dedupe by stable deal ticket
            p["deals"].append({"ticket": d.get("ticket"), "time": d.get("time"), "entry": d.get("entry"), "type": t, "volume": d.get("volume"),
                               "price": d.get("price")})
            entry = d.get("entry")              # 0 IN, 1 OUT, 2 INOUT, 3 OUT_BY
            if entry in (0, 2) and p["opened"] is None:
                p["opened"], p["side"] = d.get("time"), ("BUY" if t == 0 else "SELL")
            if entry in (0, 2):
                p["volume_in"] += float(d.get("volume") or 0)
            if entry in (1, 2, 3):
                p["volume_out"] += float(d.get("volume") or 0)
                p["closed"] = d.get("time")
            p["realized_pnl"] += float(d.get("profit") or 0)
            p["costs"] += float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)
        out = []
        for p in pos.values():
            closed = p["volume_out"] >= p["volume_in"] - 1e-9 and p["volume_in"] > 0
            out.append({**p, "status": "CLOSED" if closed else ("OPEN_PARTIAL" if p["volume_out"] else "OPEN"),
                        "net_pnl": round(p["realized_pnl"] + p["costs"], 2), "realized_pnl": round(p["realized_pnl"], 2), "costs": round(p["costs"], 2),
                        "strategy_attribution": "UNATTRIBUTED", "provenance": "MT5_REAL", "time_basis": "BROKER_SERVER_TIME",
                        "annotation": notes.get(p["ref"])})
        out.sort(key=lambda x: x["opened"] or 0, reverse=True)
        return {"source": src, "items": out, "note": "dziennik jest warstwą adnotacji nad transakcjami MT5 – tylko odczyt, bez drugiego rejestru"}

    _JOURNAL_FIELDS = ("setup", "reason", "emotion_before", "emotion_after", "rule_compliance", "mistakes", "lesson", "review_score", "screenshot")

    def annotate(self, ref: str, body: dict) -> dict:
        self._profile()
        items = self.journal()["items"]
        if items is None:       # 1.46: unknown history is not "unknown trade" (404) - the trade may exist, retry once MT5 history is loaded
            raise GameError("DEALS_UNAVAILABLE", "historia transakcji MT5 nie jest wczytana – spróbuj ponownie po połączeniu terminala", 409)
        refs = {x["ref"] for x in items}
        if ref not in refs:
            raise GameError("UNKNOWN_TRADE_REF", "adnotacja tylko do istniejącej transakcji MT5", 404)
        bad = [k for k in body if k not in self._JOURNAL_FIELDS]
        if bad:
            raise GameError("JOURNAL_FIELDS_NOT_ALLOWED", str(bad))
        cur = self._one("SELECT data FROM journal WHERE ref = ?", (ref,))
        data = {**(json.loads(cur["data"]) if cur else {}), **body}
        if "review_score" in data and data["review_score"] is not None:
            rs = data["review_score"]
            if not isinstance(rs, (int, float)) or not 0 <= rs <= 10:
                raise GameError("INVALID_REVIEW_SCORE", "0–10 (jakość wykonania, nie zysk)")
        if "mistakes" in data and not isinstance(data["mistakes"], list):
            raise GameError("INVALID_MISTAKES", "lista")
        now = self.clock()
        self.db.execute("INSERT INTO journal(ref, data, created_at, updated_at) VALUES(?, ?, ?, ?) ON CONFLICT(ref) DO UPDATE SET data=excluded.data, "
                        "updated_at=excluded.updated_at", (ref, json.dumps(data, ensure_ascii=False), now, now))
        got = []
        if all(str(data.get(k) or "").strip() for k in ("setup", "reason", "emotion_before", "lesson")) and "rule_compliance" in data:
            got.append(self._record("JOURNAL_NOTE_COMPLETED", f"journal:{ref}", "USER_NOTE"))
        if data.get("review_score") is not None and "rule_compliance" in data:
            got.append(self._record("TRADE_REVIEWED", f"review:{ref}", "USER_NOTE"))
            if data.get("rule_compliance") is True:
                got.append(self._record("RULE_COMPLIANT_REVIEW", f"compliant:{ref}", "USER_NOTE"))
        for m in data.get("mistakes") or []:
            m = " ".join(str(m).lower().split())
            if len(m) >= 5:
                got.append(self._record("MISTAKE_IDENTIFIED", "mistake:" + hashlib.sha256(m.encode()).hexdigest()[:16], "USER_NOTE"))
        return {"ref": ref, "annotation": data, "rewards": got}

    _NOTE_KINDS = {"PLAN": "PLAN_PREPARED", "ANALYSIS": "CHART_ANALYSIS", "WEEKLY": "WEEKLY_REVIEW"}

    def add_note(self, kind: str, body: dict) -> dict:
        self._profile()
        if kind not in self._NOTE_KINDS:
            raise GameError("INVALID_NOTE_KIND", "PLAN | ANALYSIS | WEEKLY")
        text = str(body.get("text") or "").strip()
        if len(text) < 40:
            raise GameError("NOTE_TOO_SHORT", "min. 40 znaków – notatka musi coś zawierać")
        if kind == "ANALYSIS" and not str(body.get("invalidation") or "").strip():
            raise GameError("MISSING_INVALIDATION", "analiza wymaga poziomu unieważnienia")
        if kind == "PLAN" and not str(body.get("max_risk") or "").strip():
            raise GameError("MISSING_MAX_RISK", "plan wymaga maksymalnego ryzyka")
        now = self.clock()
        nid = self.db.execute("INSERT INTO notes(kind, ts, data) VALUES(?, ?, ?)", (kind, now, json.dumps(body, ensure_ascii=False))).lastrowid
        key = f"weekly:{_week(now)}" if kind == "WEEKLY" else f"note:{nid}"
        return {"id": nid, "reward": self._record(self._NOTE_KINDS[kind], key, "USER_NOTE", {"note_id": nid})}

    def notes(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        rows = self._q("SELECT * FROM notes " + ("WHERE kind = ? " if kind else "") + "ORDER BY id DESC LIMIT ?", ((kind, limit) if kind else (limit,)))
        return [{**r, "data": json.loads(r["data"])} for r in rows]

    # ------------------------------------------------------------------ module 07a: academy
    def academy(self) -> dict:
        done = {r["lesson_id"] for r in self._q("SELECT lesson_id FROM academy")}
        passed = {r["level"] for r in self._q("SELECT DISTINCT level FROM quiz WHERE passed = 1")}
        lv = []
        for n, L in C.ACADEMY.items():
            lv.append({"level": n, "name": L["name"], "passed_quiz": n in passed,
                       "lessons": [{**ls, "completed": ls["id"] in done} for ls in L["lessons"]],
                       "quiz": [{"q": q, "options": o} for q, o, _ in L["quiz"]], "progress": sum(ls["id"] in done for ls in L["lessons"]) / len(L["lessons"])})
        return {"levels": lv, "content_version": C.CONTENT_VERSION, "source": "ACADEMY (treści autorskie, materiał edukacyjny – nie porada inwestycyjna)"}

    def complete_lesson(self, lesson_id: str) -> dict:
        self._profile()
        if lesson_id not in {ls["id"] for L in C.ACADEMY.values() for ls in L["lessons"]}:
            raise GameError("UNKNOWN_LESSON", lesson_id, 404)
        self.db.execute("INSERT OR IGNORE INTO academy(lesson_id, completed_at) VALUES(?, ?)", (lesson_id, self.clock()))
        return self._record("LESSON_COMPLETED", f"lesson:{lesson_id}", "ACADEMY")

    def submit_quiz(self, level: int, answers: list) -> dict:
        self._profile()
        L = C.ACADEMY.get(int(level))
        if not L:
            raise GameError("UNKNOWN_LEVEL", str(level), 404)
        if not isinstance(answers, list) or len(answers) != len(L["quiz"]):
            raise GameError("INVALID_ANSWERS", f"oczekiwano {len(L['quiz'])} odpowiedzi")
        done = {r["lesson_id"] for r in self._q("SELECT lesson_id FROM academy")}
        if not all(ls["id"] in done for ls in L["lessons"]):
            raise GameError("LESSONS_NOT_COMPLETED", "najpierw ukończ wszystkie lekcje poziomu", 409)
        good = sum(1 for a, (_, _, ok) in zip(answers, L["quiz"]) if a == ok)        # graded on the server - answers are never sent to the UI
        score = good / len(L["quiz"])
        passed = score >= C.QUIZ_PASS - 1e-9
        self.db.execute("INSERT INTO quiz(level, ts, score, passed) VALUES(?, ?, ?, ?)", (int(level), self.clock(), score, int(passed)))
        rewards = []
        if passed:
            rewards.append(self._record("QUIZ_PASSED", f"quiz:{int(level)}", "ACADEMY"))
            if int(level) == C.RISK_QUIZ_LEVEL:
                rewards.append(self._record("RISK_EXERCISE", "risk:quiz2", "ACADEMY"))
        return {"level": int(level), "score": round(score, 3), "correct": good, "passed": passed, "rewards": rewards}

    def risk_exercise(self) -> dict:
        """Deterministic position-sizing exercise of the day: (account, risk %, SL distance) -> size."""
        n = self._one("SELECT COUNT(*) n FROM events WHERE kind = 'RISK_EXERCISE'")["n"]
        seed = int(hashlib.sha256(f"{_day(self.clock())}:{n}".encode()).hexdigest()[:8], 16)
        acc = 5_000 + (seed % 20) * 1_000
        risk = [0.25, 0.5, 1.0, 1.5, 2.0][seed % 5]
        sl = round(1.0 + (seed % 37) / 4, 2)
        return {"exercise_id": f"{_day(self.clock())}:{n}", "account": acc, "risk_pct": risk, "sl_distance": sl,
                "question": f"Konto {acc}, ryzyko {risk}% na transakcję, SL {sl} (wartość punktu = 1 na jednostkę). Ile jednostek?"}

    def submit_risk_exercise(self, exercise_id: str, answer: float) -> dict:
        ex = self.risk_exercise()
        if exercise_id != ex["exercise_id"]:
            raise GameError("STALE_EXERCISE", "pobierz aktualne ćwiczenie", 409)
        want = ex["account"] * ex["risk_pct"] / 100 / ex["sl_distance"]
        try:
            ok = abs(float(answer) - want) <= max(0.01, want * 0.01)
        except (TypeError, ValueError):
            ok = False
        rew = self._record("RISK_EXERCISE", f"risk:{exercise_id}", "ACADEMY") if ok else None
        return {"correct": ok, "expected": round(want, 4), "reward": rew}

    # ------------------------------------------------------------------ module 06: quests
    def _period(self, cat: str, now: float) -> str:
        return {"DAILY": _day(now), "WEEKLY": _week(now)}.get(cat, "LIFETIME")

    def _progress(self, activity: str, cat: str, now: float, count: int | None = None) -> int:
        if activity == "DISCIPLINE_DAYS":
            return self._one("SELECT COUNT(DISTINCT day) n FROM events WHERE kind IN ('JOURNAL_NOTE_COMPLETED', 'PLAN_PREPARED')")["n"]
        if activity == "JOURNAL_DAYS_WEEK":
            return self._one("SELECT COUNT(DISTINCT day) n FROM events WHERE kind = 'JOURNAL_NOTE_COMPLETED' AND week = ?", (_week(now),))["n"]
        if activity == "LESSON_COMPLETED" and cat == "SPECIAL":     # psychology track = level-2 PSY lessons + level-2 skills
            return self._one("SELECT COUNT(*) n FROM events WHERE kind = 'LESSON_COMPLETED' AND key LIKE 'lesson:L2_%'")["n"]
        if activity == "QUIZ_PASSED" and cat == "MAIN":
            if count is None:
                return self._one("SELECT COUNT(*) n FROM events WHERE kind = 'QUIZ_PASSED'")["n"]
            # 1.46: a MAIN campaign of N = quizzes of academy levels 1..N (M_EASY 1-2, M_MEDIUM 1-3, M_HARD 1-4) - passing levels 3 and 4
            # must not complete M_EASY; key 'quiz:<level>' is unique per level
            passed = {r["key"] for r in self._q("SELECT key FROM events WHERE kind = 'QUIZ_PASSED'")}
            return sum(f"quiz:{lv}" in passed for lv in range(1, int(count) + 1))
        if cat == "DAILY":
            return self._one("SELECT COUNT(*) n FROM events WHERE kind = ? AND day = ?", (activity, _day(now)))["n"]
        if cat == "WEEKLY":
            return self._one("SELECT COUNT(*) n FROM events WHERE kind = ? AND week = ?", (activity, _week(now)))["n"]
        return self._one("SELECT COUNT(*) n FROM events WHERE kind = ?", (activity,))["n"]

    def quests(self) -> list[dict]:
        prof = self._profile()
        now = self.clock()
        out = []
        for qid, cat, title, desc, act, cnt, xp, gold, diff in C.QUESTS:
            per = self._period(cat, now)
            claimed = self._one("SELECT ts FROM quest_claims WHERE key = ?", (f"{qid}|{per}",))
            locked = diff is not None and C.DIFF_ORDER[prof["difficulty"]] < C.DIFF_ORDER[diff]
            pr = min(cnt, self._progress(act, cat, now, cnt))
            status = "LOCKED" if locked else ("CLAIMED" if claimed else ("COMPLETED" if pr >= cnt else ("IN_PROGRESS" if pr else "AVAILABLE")))
            out.append({"id": qid, "category": cat, "title": title, "description": desc, "difficulty": diff or "ANY", "requirement": {"activity": act,
                        "count": cnt}, "progress": pr, "xp_reward": xp, "gold_reward": gold, "status": status, "period": per,
                        "completed_at": claimed["ts"] if claimed else None, "verification": "zliczanie zweryfikowanych zdarzeń gry w okresie"})
        return out

    def claim(self, quest_id: str) -> dict:
        with self._lock:
            q = next((x for x in self.quests() if x["id"] == quest_id), None)
            if not q:
                raise GameError("UNKNOWN_QUEST", quest_id, 404)
            if q["status"] == "CLAIMED":
                raise GameError("ALREADY_CLAIMED", quest_id, 409)
            if q["status"] != "COMPLETED":
                raise GameError("QUEST_NOT_COMPLETED", f"{q['progress']}/{q['requirement']['count']}", 409)
            key = f"{quest_id}|{q['period']}"
            self.db.execute("INSERT INTO quest_claims(key, quest_id, period, ts) VALUES(?, ?, ?, ?)", (key, quest_id, q["period"], self.clock()))
            self._ledger("xp_ledger", f"quest:{key}", q["xp_reward"], "QUEST_COMPLETED", quest_id)
            self._ledger("gold_ledger", f"quest:{key}", q["gold_reward"], "QUEST_COMPLETED", quest_id)
            return {"quest_id": quest_id, "xp": q["xp_reward"], "trader_gold": q["gold_reward"], "state": self.state()["progress"]}

    # ------------------------------------------------------------------ module 05: skill tree
    def skills(self) -> dict:
        lvl = level_for_xp(self.xp_total())
        un = {r["skill_id"] for r in self._q("SELECT skill_id FROM skills")}
        points = lvl // 2 + 1 - len(un)
        nodes = []
        for sid, br, name, desc, minl, req in C.SKILLS:
            st = "UNLOCKED" if sid in un else ("AVAILABLE" if lvl >= minl and all(r in un for r in req) and points > 0 else "LOCKED")
            nodes.append({"id": sid, "branch": br, "branch_name": C.SKILL_BRANCHES[br], "name": name, "description": desc, "min_level": minl,
                          "requires": req, "state": st})
        return {"level": lvl, "points_available": max(0, points), "nodes": nodes, "branches": C.SKILL_BRANCHES}

    def unlock_skill(self, skill_id: str) -> dict:
        with self._lock:
            node = next((n for n in self.skills()["nodes"] if n["id"] == skill_id), None)
            if not node:
                raise GameError("UNKNOWN_SKILL", skill_id, 404)
            if node["state"] == "UNLOCKED":
                raise GameError("ALREADY_UNLOCKED", skill_id, 409)
            if node["state"] != "AVAILABLE":
                raise GameError("SKILL_LOCKED", f"poziom {node['min_level']}, wymagane {node['requires']}, punkty", 409)
            self.db.execute("INSERT INTO skills(skill_id, unlocked_at) VALUES(?, ?)", (skill_id, self.clock()))
            return self.skills()

    # ------------------------------------------------------------------ module 07b: historical simulator (no lookahead)
    def sim_start(self, symbol: str, tf: str, count: int = 400, warmup: int = 60) -> dict:
        prof = self._profile()
        count = max(warmup + 20, min(int(count), 3000))
        try:
            # 1.46: MarketBridge.symbol_bars marks the newest bar closed=False (it has no 'forming' key) - drop it, only closed bars
            bars = [b for b in self.account.bars(symbol, tf, count) if b.get("closed") is not False and not b.get("forming")]
        except Exception:  # noqa: BLE001
            bars = []
        if len(bars) < warmup + 20:
            raise GameError("SIM_DATA_UNAVAILABLE", f"za mało zamkniętych świec {symbol} {tf} ({len(bars)})", 409)
        rows = [{"t": b.get("time") or b.get("t") or b.get("open_utc"), "o": float(b["o"] if "o" in b else b["open"]),
                 "h": float(b["h"] if "h" in b else b["high"]), "l": float(b["l"] if "l" in b else b["low"]),
                 "c": float(b["c"] if "c" in b else b["close"])} for b in bars]
        prov = {"provider": "MT5 (konto użytkownika, tylko odczyt)", "symbol": symbol, "tf": tf, "price_basis": "BID (MT5 bars)",
                "first": rows[0]["t"], "last": rows[-1]["t"], "bars": len(rows), "time_basis": "jak w źródle MT5"}
        sid = self.db.execute("INSERT INTO sim_sessions(symbol, tf, bars, cursor, start_cursor, status, virtual_start, provenance, created_at) "
                              "VALUES(?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)", (symbol, tf, json.dumps(rows), warmup, warmup, prof["virtual_capital"],
                                                                         json.dumps(prov), self.clock())).lastrowid
        return self.sim_view(sid)

    def _sess(self, sid: int) -> dict:
        s = self._one("SELECT * FROM sim_sessions WHERE id = ?", (int(sid),))
        if not s:
            raise GameError("UNKNOWN_SESSION", str(sid), 404)
        return s

    def sim_view(self, sid: int) -> dict:
        s = self._sess(sid)
        bars = json.loads(s["bars"])[: s["cursor"]]                  # ONLY revealed bars - future bars never leave the server
        trades = self._q("SELECT * FROM sim_trades WHERE session_id = ? ORDER BY id", (int(sid),))
        pnl = sum(t["pnl"] or 0 for t in trades)
        last = bars[-1]["c"]
        unreal = sum((last - t["entry"]) * t["size"] * (1 if t["side"] == "BUY" else -1) for t in trades if t["closed_idx"] is None)
        return {"id": s["id"], "symbol": s["symbol"], "tf": s["tf"], "status": s["status"], "cursor": s["cursor"], "bars": bars,
                "remaining_hidden": None, "trades": trades, "simulated_pnl": round(pnl, 2), "simulated_unrealized": round(unreal, 2),
                "virtual_balance": round(s["virtual_start"] + pnl, 2), "provenance": {**json.loads(s["provenance"]), "type": "SIMULATOR"},
                "isolation": "symulacja – brak połączenia ze zleceniami MT5, wynik nie trafia do ROI strategii"}

    def sim_step(self, sid: int, n: int = 1) -> dict:
        with self._lock:
            s = self._sess(sid)
            if s["status"] != "ACTIVE":
                raise GameError("SESSION_NOT_ACTIVE", s["status"], 409)
            allb = json.loads(s["bars"])
            cur = s["cursor"]
            for _ in range(max(1, min(int(n), 50))):
                if cur >= len(allb):
                    break
                b = allb[cur]
                for t in self._q("SELECT * FROM sim_trades WHERE session_id = ? AND closed_idx IS NULL", (s["id"],)):
                    hit = self._sltp(t, b)
                    if hit:
                        self._close_trade(t, cur, *hit)
                cur += 1
            self.db.execute("UPDATE sim_sessions SET cursor = ? WHERE id = ?", (cur, s["id"]))
            return self.sim_view(sid)

    @staticmethod
    def _sltp(t: dict, b: dict):
        buy = t["side"] == "BUY"
        sl_hit = t["sl"] is not None and (b["l"] <= t["sl"] if buy else b["h"] >= t["sl"])
        tp_hit = t["tp"] is not None and (b["h"] >= t["tp"] if buy else b["l"] <= t["tp"])
        if sl_hit:                                                    # both in one bar -> conservative: SL first
            return t["sl"], "SL"
        if tp_hit:
            return t["tp"], "TP"
        return None

    def _close_trade(self, t: dict, idx: int, price: float, reason: str):
        pnl = (price - t["entry"]) * t["size"] * (1 if t["side"] == "BUY" else -1)
        self.db.execute("UPDATE sim_trades SET closed_idx = ?, exit = ?, pnl = ?, reason = ? WHERE id = ?", (idx, price, round(pnl, 6), reason, t["id"]))

    def sim_open(self, sid: int, side: str, size: float, sl: float | None = None, tp: float | None = None) -> dict:
        s = self._sess(sid)
        if s["status"] != "ACTIVE":
            raise GameError("SESSION_NOT_ACTIVE", s["status"], 409)
        if side not in ("BUY", "SELL"):
            raise GameError("INVALID_SIDE", "BUY | SELL")
        try:
            size = float(size)
        except (TypeError, ValueError):
            raise GameError("INVALID_SIZE") from None
        if not (0 < size <= 1_000_000):
            raise GameError("INVALID_SIZE")
        entry = json.loads(s["bars"])[s["cursor"] - 1]["c"]           # last revealed CLOSE - no fill inside a hidden bar
        buy = side == "BUY"
        if sl is not None and ((buy and float(sl) >= entry) or (not buy and float(sl) <= entry)):
            raise GameError("INVALID_SL", "SL po złej stronie ceny")
        if tp is not None and ((buy and float(tp) <= entry) or (not buy and float(tp) >= entry)):
            raise GameError("INVALID_TP", "TP po złej stronie ceny")
        self.db.execute("INSERT INTO sim_trades(session_id, side, size, entry, sl, tp, opened_idx) VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (s["id"], side, size, entry, None if sl is None else float(sl), None if tp is None else float(tp), s["cursor"] - 1))
        return self.sim_view(sid)

    def sim_close(self, sid: int, trade_id: int) -> dict:
        s = self._sess(sid)
        t = self._one("SELECT * FROM sim_trades WHERE id = ? AND session_id = ? AND closed_idx IS NULL", (int(trade_id), s["id"]))
        if not t:
            raise GameError("UNKNOWN_OPEN_TRADE", str(trade_id), 404)
        self._close_trade(t, s["cursor"] - 1, json.loads(s["bars"])[s["cursor"] - 1]["c"], "MANUAL")
        return self.sim_view(sid)

    def sim_finish(self, sid: int) -> dict:
        with self._lock:
            s = self._sess(sid)
            if s["status"] != "ACTIVE":
                raise GameError("SESSION_NOT_ACTIVE", s["status"], 409)
            last = json.loads(s["bars"])[s["cursor"] - 1]["c"]
            for t in self._q("SELECT * FROM sim_trades WHERE session_id = ? AND closed_idx IS NULL", (s["id"],)):
                self._close_trade(t, s["cursor"] - 1, last, "SESSION_END")
            self.db.execute("UPDATE sim_sessions SET status = 'DONE', finished_at = ? WHERE id = ?", (self.clock(), s["id"]))
            stepped = s["cursor"] - s["start_cursor"]
            ntr = self._one("SELECT COUNT(*) n FROM sim_trades WHERE session_id = ?", (s["id"],))["n"]
            rew = (self._record("SIM_SESSION_COMPLETED", f"sim:{s['id']}", "SIMULATOR", {"bars": stepped, "trades": ntr})
                   if stepped >= 30 and ntr >= 1 else {"recorded": False, "xp": 0, "reason": "MIN_30_BARS_AND_1_TRADE"})
            return {**self.sim_view(sid), "reward": rew, "analytics": self._sim_analytics(s["id"])}

    def _sim_analytics(self, sid: int) -> dict:
        # 1.46: equity curve / drawdown in the order PnL was realised (closed_idx), not in insertion (= opening) order
        tr = [t for t in self._q("SELECT * FROM sim_trades WHERE session_id = ? AND pnl IS NOT NULL ORDER BY closed_idx, id", (sid,))]
        wins = [t["pnl"] for t in tr if t["pnl"] > 0]
        losses = [t["pnl"] for t in tr if t["pnl"] < 0]
        eq, peak, dd = 0.0, 0.0, 0.0
        for t in tr:
            eq += t["pnl"]
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        return {"trades": len(tr), "wins": len(wins), "losses": len(losses), "win_rate": round(len(wins) / (len(wins) + len(losses)), 3) if wins or losses else None,
                "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else None, "net": round(sum(t["pnl"] for t in tr), 2),
                "max_drawdown": round(dd, 2), "type": "SIMULATOR"}

    def sim_sessions(self) -> list[dict]:
        return self._q("SELECT id, symbol, tf, status, cursor, created_at, finished_at FROM sim_sessions ORDER BY id DESC LIMIT 50")

    # ------------------------------------------------------------------ module 04: calendar
    def calendar(self, month: str) -> dict:
        self._profile()
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise GameError("INVALID_MONTH", "YYYY-MM") from None
        days: dict[str, dict] = {}
        jr = self.journal()
        real_ok = jr["items"] is not None       # 1.46: MT5 history unavailable -> real trades/PnL per day are null, not 0

        def d(k):
            return days.setdefault(k, {"date": k, "real_trades": 0 if real_ok else None, "real_net_pnl": 0.0 if real_ok else None, "xp": 0,
                                       "activities": {}, "sim_sessions": 0})
        for p in jr["items"] or []:
            if p["status"] == "CLOSED" and p["closed"]:
                k = datetime.fromtimestamp(p["closed"], timezone.utc).strftime("%Y-%m-%d")
                if k.startswith(month):
                    x = d(k)
                    x["real_trades"] += 1
                    x["real_net_pnl"] = round(x["real_net_pnl"] + p["net_pnl"], 2)
        for r in self._q("SELECT day, kind, COUNT(*) n FROM events WHERE day LIKE ? GROUP BY day, kind", (month + "%",)):
            d(r["day"])["activities"][r["kind"]] = r["n"]
        for r in self._q("SELECT ts, amount FROM xp_ledger"):
            k = _day(r["ts"])
            if k.startswith(month):
                d(k)["xp"] += r["amount"]
        for r in self._q("SELECT created_at FROM sim_sessions"):
            k = _day(r["created_at"])
            if k.startswith(month):
                d(k)["sim_sessions"] += 1
        for x in days.values():
            # 1.46: REST means "no trades" - with the MT5 history unavailable that is unknown (UNAVAILABLE), not a rest day
            x["type"] = ("TRADING" if x["real_trades"] else "SIMULATOR" if x["sim_sessions"] else "LEARNING" if x["activities"] else
                         "REST" if real_ok else "UNAVAILABLE")
        return {"month": month, "days": sorted(days.values(), key=lambda x: x["date"]), "real_source": jr["source"],
                "time_basis": {"real_trades": "BROKER_SERVER_TIME (czas zamknięcia z MT5)", "game_events": "UTC"},
                "note": "dzień bez transakcji jest neutralny (REST), nie negatywny"}

    # ------------------------------------------------------------------ module 02: Grand Master Coach (deterministic, no fake AI)
    def coach(self) -> dict:
        st = self.state()
        q = self.quests()
        jr = self.journal()
        ac = self.academy()
        plan = [f"Quest dzienny: {x['title']} ({x['progress']}/{x['requirement']['count']})" for x in q if x["category"] == "DAILY" and x["status"] in
                ("AVAILABLE", "IN_PROGRESS")]
        nxt = next((ls for L in ac["levels"] for ls in L["lessons"] if not ls["completed"]), None)
        if nxt:
            plan.append(f"Następna lekcja: {nxt['title']}")
        items = jr["items"] or []
        missing = [p["ref"] for p in items if p["status"] == "CLOSED" and not p["annotation"]][:5]
        obs = []
        if jr["items"] is None:     # 1.46: no MT5 history -> say so instead of silently reporting "no trades without a journal entry"
            obs.append({"kind": "OBSERVATION", "text": "Historia transakcji MT5 niedostępna (UNAVAILABLE) – nie sprawdzono wpisów w dzienniku."})
        if missing:
            obs.append({"kind": "OBSERVATION", "text": f"{len(missing)} zamkniętych transakcji bez wpisu w dzienniku.", "refs": missing})
        ann = [p["annotation"] for p in items if p["annotation"]]
        nc = sum(1 for a in ann if a.get("rule_compliance") is False)
        if ann:
            obs.append({"kind": "OBSERVATION", "text": f"Zgodność z regułami: {len(ann) - nc}/{len(ann)} opisanych transakcji."})
        if nc >= 2:
            obs.append({"kind": "INFERENCE", "text": "Powtarzają się wejścia niezgodne z planem – rozważ regułę przerwy po stracie (lekcja: Revenge trading)."})
        mem = self._q("SELECT id, ts, text FROM coach_memory ORDER BY id DESC LIMIT 20")
        return {"mode": "RULES_ONLY", "ai": "AI_UNAVAILABLE", "persona": "GRAND MASTER COACH",
                "greeting": st["profile"]["intro"], "daily_plan": plan, "observations": obs, "memory": mem,
                "disclaimer": "Coach opisuje wyłącznie dane z dziennika, akademii i symulatora. Nie diagnozuje psychiki i nie daje sygnałów handlowych.",
                "provenance": "RULES_COACH"}

    def coach_memory_add(self, text: str) -> dict:
        text = str(text or "").strip()
        if not (3 <= len(text) <= 500):
            raise GameError("INVALID_MEMORY", "3–500 znaków")
        low = text.lower()
        if any(w in low for w in ("password", "hasło", "haslo", "token", "api key", "apikey", "secret")):
            raise GameError("SECRET_NOT_ALLOWED", "pamięć coacha nie przechowuje haseł ani kluczy")
        mid = self.db.execute("INSERT INTO coach_memory(ts, text) VALUES(?, ?)", (self.clock(), text)).lastrowid
        return {"id": mid}

    def coach_memory_delete(self, mid: int | None = None) -> dict:
        if mid is None:
            self.db.execute("DELETE FROM coach_memory")
        else:
            self.db.execute("DELETE FROM coach_memory WHERE id = ?", (int(mid),))
        return {"ok": True}

    # ------------------------------------------------------------------ module 08: lifestyle + leaderboard
    def lifestyle(self) -> dict:
        lvl = level_for_xp(self.xp_total())
        gold = self.gold_total()
        own = {r["item_id"]: r for r in self._q("SELECT * FROM inventory")}
        items = [{"id": i, "slot": sl, "name": nm, "price": pr, "min_level": ml, "owned": i in own, "equipped": bool(own.get(i, {}).get("equipped")),
                  "state": "OWNED" if i in own else ("LOCKED" if lvl < ml else ("AFFORDABLE" if gold >= pr else "TOO_EXPENSIVE"))}
                 for i, sl, nm, pr, ml in C.LIFESTYLE]
        return {"trader_gold": gold, "level": lvl, "items": items, "note": "przedmioty są wyłącznie kosmetyczne; Trader Gold nie ma wartości pieniężnej"}

    def buy(self, item_id: str) -> dict:
        with self._lock:
            it = next((x for x in self.lifestyle()["items"] if x["id"] == item_id), None)
            if not it:
                raise GameError("UNKNOWN_ITEM", item_id, 404)
            if it["owned"]:
                raise GameError("ALREADY_OWNED", item_id, 409)
            if it["state"] != "AFFORDABLE":
                raise GameError("CANNOT_BUY", it["state"], 409)
            if not self._ledger("gold_ledger", f"buy:{item_id}", -it["price"], "COSMETIC_PURCHASE", item_id):
                raise GameError("ALREADY_OWNED", item_id, 409)
            self.db.execute("INSERT INTO inventory(item_id, acquired_at, equipped) VALUES(?, ?, 0)", (item_id, self.clock()))
            return self.lifestyle()

    def equip(self, item_id: str) -> dict:
        it = next((x for x in self.lifestyle()["items"] if x["id"] == item_id), None)
        if not it or not it["owned"]:
            raise GameError("NOT_OWNED", item_id, 409)
        self.db.execute("UPDATE inventory SET equipped = 0 WHERE item_id IN (%s)" % ",".join("?" * len([x for x in C.LIFESTYLE if x[1] == it["slot"]])),  # noqa: S608
                        [x[0] for x in C.LIFESTYLE if x[1] == it["slot"]])
        self.db.execute("UPDATE inventory SET equipped = 1 WHERE item_id = ?", (item_id,))
        return self.lifestyle()

    def leaderboard(self) -> dict:
        prof = self._profile()
        st = self.state()
        quests_done = self._one("SELECT COUNT(*) n FROM quest_claims")["n"]
        lessons = self._one("SELECT COUNT(*) n FROM academy")["n"]
        att = st["attributes"]
        score = st["progress"]["xp"] + 10 * quests_done + 20 * lessons + 5 * (att["discipline"] + att["risk_management"] + att["consistency"])
        me = {"name": "Ty (anonimowo)" if prof["anonymize"] else prof["username"], "level": st["progress"]["level"], "xp": st["progress"]["xp"],
              "discipline": att["discipline"], "risk_management": att["risk_management"], "consistency": att["consistency"], "quests": quests_done,
              "lessons": lessons, "score": score}
        return {"local": [me], "formula": "XP + 10×questy + 20×lekcje + 5×(dyscyplina + ryzyko + konsekwencja); bez zysku i liczby transakcji",
                "global": {"enabled": False, "reason": "NO_IDENTITY_PRIVACY_ANTICHEAT", "message": "Ranking globalny/tygodniowy/miesięczny/znajomych "
                           "jest wyłączony – aplikacja nie ma uwierzytelnionej tożsamości, zgód i ochrony przed oszustwami."},
                "weekly": {"enabled": False, "reason": "NO_IDENTITY_PRIVACY_ANTICHEAT"}, "monthly": {"enabled": False, "reason": "NO_IDENTITY_PRIVACY_ANTICHEAT"},
                "friends": {"enabled": False, "reason": "NO_IDENTITY_PRIVACY_ANTICHEAT"}}
