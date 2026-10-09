"""MT5 connector -> central server (telemetry the account owner explicitly consented to).

* Only ONE account: the one shown in the monitor when the user switched the connection on (server + login).
  If the terminal is logged into another account, sending stops until the user consents again (no silent switch,
  no scanning of other accounts on the computer). Broker passwords are never read or sent.
* balance / equity / currency from account_info() every `snapshot_seconds` (default 15 s), with measured time and seq;
* deals from history_deals_get(): first a resumable import of `initial_history_days` in 30-day windows (cursor stored
  locally + import status on the server), then incremental sync every `deals_seconds` (default 60 s) with overlap;
  duplicates are removed by the server by deal ticket. Missing older entries of positions are fetched by position id.
* MT5 deal times are broker-server time; they are converted to UTC with the verified server offset - without a
  verified offset deals are not sent (status TIME_OFFSET_UNKNOWN), never guessed.
The win ratio is computed by the SERVER from these deals - the client never sends a ready-made statistic.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from .central_client import CentralError

log = logging.getLogger("masterquo.connector")
DAY_MS = 86400_000


def _row(x) -> dict:
    if isinstance(x, dict):
        return x
    if hasattr(x, "_asdict"):
        return x._asdict()
    return {k: getattr(x, k) for k in dir(x) if not k.startswith("_") and not callable(getattr(x, k))}


class Connector:
    def __init__(self, lic, bridge, cfg_store):
        self.lic, self.bridge, self.cfg_store = lic, bridge, cfg_store
        self.path = lic.device.dir / "connector.json"
        self.status_text = "OFF"
        self.last_snapshot_at: float | None = None
        self.last_deals_at: float | None = None
        self.account_id: str | None = None
        self._stop = threading.Event()
        self._last_snap = self._last_deals = 0.0

    @property
    def cfg(self):
        return self.cfg_store.get().central.connector

    def _state(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------ consent
    def current_terminal_account(self) -> dict | None:
        a = self.bridge.account_status()
        return {"server": a.get("server"), "login": str(a.get("login")), "trade_mode": a.get("trade_mode"), "currency": a.get("currency"),
                "company": a.get("company")} if a and a.get("login") else None

    def set_consent(self, on: bool) -> dict:
        if on:
            acc = self.current_terminal_account()
            if not acc:
                raise CentralError("NO_MT5_ACCOUNT_CONNECTED", 400)
            self.cfg_store.update({"central": {"connector": {"enabled": True, "server": acc["server"], "login": acc["login"]}}})
        else:
            self.cfg_store.update({"central": {"connector": {"enabled": False}}})
            try:
                self._device_call("POST", "/api/v1/connector/unlink", {})
            except Exception:
                pass
            self.account_id = None
        return self.status()

    # ------------------------------------------------------------ calls
    def _device_call(self, method: str, path: str, body: dict | None):
        st = self.lic.device.state()
        out, _t0, _t1 = self.lic.client().device_call(self.lic.device.private_key(), st["device_id"], method, path, body)
        return out

    def _call(self, fn):
        return self.bridge.raw_call(fn, 2)

    # ------------------------------------------------------------ loop
    def start(self) -> None:
        threading.Thread(target=self._loop, name="mt5-connector", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception as exc:
                self.status_text = f"ERROR:{type(exc).__name__}"
                log.exception("connector")

    def tick(self, now_mono: float | None = None) -> None:
        now = time.monotonic() if now_mono is None else now_mono
        c = self.cfg
        if not c.enabled:
            self.status_text = "OFF"
            return
        if not self.lic.guard.allows("telemetry"):
            self.status_text = "PAUSED_NO_VALID_LICENSE"          # last values stay on the server, marked as old
            return
        acc = self.current_terminal_account()
        if not acc or self.bridge.state != "CONNECTED":
            self.status_text = "MT5_NOT_CONNECTED"
            return
        if (acc["server"], acc["login"]) != (c.server, c.login):
            self.status_text = "ACCOUNT_DIFFERS_FROM_CONSENTED"     # explicit re-consent required
            self.account_id = None
            return
        if self.account_id is None:
            info = _row(self._call(lambda m: m.account_info()) or {})
            out = self._device_call("POST", "/api/v1/connector/link", {
                "server": acc["server"], "login": acc["login"], "company": acc.get("company"), "trade_mode": acc["trade_mode"] if acc["trade_mode"] in ("DEMO", "REAL", "CONTEST") else "DEMO",
                "currency": acc["currency"] or "", "currency_digits": int(info.get("currency_digits") or 2),
                "bot_magic": int(self.cfg_store.get().mt5.magic_number), "consent": True})
            self.account_id = out["account_id"]
            st = self._state()
            st.setdefault(self.account_id, {"cursor_ms": None, "complete": False})
            self._save(st)
        if now - self._last_snap >= c.snapshot_seconds:
            self._last_snap = now
            self.send_snapshot()
        if now - self._last_deals >= c.deals_seconds:
            self._last_deals = now
            self.sync_deals()
        self.status_text = "ONLINE"

    def send_snapshot(self) -> dict | None:
        a = _row(self._call(lambda m: m.account_info()) or {})
        if not a:
            return None
        ms = int(time.time() * 1000)
        out = self._device_call("POST", "/api/v1/telemetry/snapshot", {
            "account_id": self.account_id, "seq": ms, "measured_ms": ms, "balance": float(a["balance"]), "equity": float(a["equity"]),
            "margin": float(a.get("margin") or 0), "margin_free": float(a.get("margin_free") or 0), "currency": a.get("currency") or ""})
        self.last_snapshot_at = time.time()
        return out

    def _deal_json(self, d: dict, off: float) -> dict:
        t_ms = int(d.get("time_msc") or int(d["time"]) * 1000) - int(off * 1000)
        return {"ticket": int(d["ticket"]), "order": int(d.get("order") or 0), "position_id": int(d.get("position_id") or 0), "time_ms": t_ms,
                "type": int(d["type"]), "entry": int(d.get("entry") or 0), "volume": float(d.get("volume") or 0), "price": float(d.get("price") or 0),
                "profit": float(d.get("profit") or 0), "commission": float(d.get("commission") or 0), "swap": float(d.get("swap") or 0),
                "fee": float(d.get("fee") or 0), "symbol": d.get("symbol") or "", "magic": int(d.get("magic") or 0), "comment": (d.get("comment") or "")[:64]}

    def sync_deals(self) -> dict | None:
        off = self.bridge.clock.offset
        if off is None:
            self.status_text = "TIME_OFFSET_UNKNOWN"
            return None
        st = self._state()
        cur = st.get(self.account_id) or {"cursor_ms": None, "complete": False}
        now_ms = int(time.time() * 1000)
        start = cur["cursor_ms"] if cur["cursor_ms"] is not None else now_ms - self.cfg.initial_history_days * DAY_MS
        end = min(now_ms, start + 30 * DAY_MS) if not cur["complete"] else now_ms
        frm = datetime.fromtimestamp((start - DAY_MS) / 1000 + off, timezone.utc).replace(tzinfo=None)    # 1 day overlap, broker time
        to = datetime.fromtimestamp(end / 1000 + off + 60, timezone.utc).replace(tzinfo=None)
        raw = self._call(lambda m: m.history_deals_get(frm, to))
        if raw is None:
            self.status_text = "HISTORY_UNAVAILABLE"
            return None
        deals = [_row(d) for d in raw]
        # earlier entries of positions that are closed inside the window (needed to rebuild whole cycles)
        have_in = {d.get("position_id") for d in deals if int(d.get("entry") or 0) == 0}
        missing = {d.get("position_id") for d in deals if int(d.get("type", 9)) in (0, 1) and int(d.get("entry") or 0) != 0
                   and d.get("position_id") not in have_in}
        for pid in list(missing)[:200]:
            more = self._call(lambda m, pid=pid: m.history_deals_get(position=pid)) or ()
            deals += [_row(x) for x in more]
        uniq = {int(d["ticket"]): self._deal_json(d, off) for d in deals}
        done = cur["complete"] or end >= now_ms
        body = list(uniq.values())
        out = None
        for i in range(0, max(1, len(body)), 500):
            out = self._device_call("POST", "/api/v1/telemetry/deals", {
                "account_id": self.account_id, "batch_id": f"{start}-{end}-{i}", "deals": body[i:i + 500],
                "import": {"from_ms": None if cur["cursor_ms"] is not None else start, "to_ms": end, "complete": done}})
        st[self.account_id] = {"cursor_ms": end, "complete": done}
        self._save(st)
        self.last_deals_at = time.time()
        return out

    def status(self) -> dict:
        c = self.cfg
        return {"enabled": c.enabled, "server": c.server, "login": c.login, "status": self.status_text, "account_id": self.account_id,
                "last_snapshot_at": self.last_snapshot_at, "last_deals_at": self.last_deals_at,
                "terminal_account": self.current_terminal_account(),
                "disclosure": "Po włączeniu właściciel usługi MasterQUO widzi saldo, equity, walutę, typ rachunku, serwer, login i historię transakcji "
                              "tego jednego rachunku oraz status połączenia. Hasło brokera nie jest odczytywane ani wysyłane."}
