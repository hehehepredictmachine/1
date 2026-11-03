"""Optional Telegram notifications - disabled by default.

Sends information only (never accepts commands, never places orders): signals, opened / closed positions, a daily summary.
Messages are bilingual - English + Simplified Chinese (config telegram.language: EN_ZH / EN / ZH). Deduplicated by key in
SQLite. The bot token is a local secret (DPAPI on Windows), chat_id is configuration; neither the token nor a message body is
ever logged. The connection state shown in the panel is what really happened: NOT_CONFIGURED / DISABLED / UNTESTED until a
message was accepted by Telegram, then OK or ERROR with Telegram's own description. A failure never affects trading.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..timeutil import iso, utcnow

log = logging.getLogger("masterquo.telegram")

API = "https://api.telegram.org"


def _num(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def _signed(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    return ("+" if float(v) > 0 else "") + _num(v, digits)


def _pick(lang: str, en: str, zh: str) -> str:
    """Whole line in the chosen language(s): EN_ZH = English line followed by the Chinese line."""
    if lang == "EN":
        return en
    if lang == "ZH":
        return zh
    return f"{en}\n{zh}"


def _lbl(lang: str, en: str, zh: str) -> str:
    """Short inline label: EN_ZH = "en | zh"."""
    return en if lang == "EN" else zh if lang == "ZH" else f"{en} | {zh}"


def _side(lang: str, side: str | None) -> str:
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(side or "", side or "—")
    return _lbl(lang, side, {"BUY": "买入", "SELL": "卖出"}.get(side, side))


def fmt_signal(d: dict, lang: str = "EN_ZH") -> str:
    """Signal of the bot (analytical; not an order)."""
    syn = _lbl(lang, "[SYNTHETIC DATA]", "[模拟数据]") + " " if d.get("synthetic") else ""
    return "\n".join([
        f"📡 {syn}{_lbl(lang, 'Signal', '信号')}: {d.get('symbol')} {_side(lang, d.get('side'))}",
        f"{d.get('strategy') or '—'} · {d.get('timeframe') or '—'} · {_lbl(lang, 'stage', '阶段')} {d.get('stage') or '—'}",
        f"{_lbl(lang, 'Entry', '入场')} {_num(d.get('entry'))} · SL {_num(d.get('sl'))} · TP {' / '.join(_num(t) for t in (d.get('tps') or [])) or '—'}",
        _pick(lang, "Analysis only – not an order.", "仅供分析 – 并非下单指令。")])


def fmt_opened(d: dict, lang: str = "EN_ZH") -> str:
    return "\n".join([
        f"🟢 {_lbl(lang, 'Position opened', '已开仓')} · {d.get('mode')}",
        f"{d.get('symbol')} {_side(lang, d.get('side'))} {_num(d.get('volume'))} lot @ {_num(d.get('price'))}",
        f"SL {_num(d.get('sl'))} · TP {_num(d.get('tp'))}",
        f"{_lbl(lang, 'Strategy', '策略')}: {d.get('strategy') or '—'}"])


def fmt_closed(d: dict, lang: str = "EN_ZH") -> str:
    r = f" ({_signed(d.get('r_multiple'))}R)" if d.get("r_multiple") is not None else ""
    unknown = "" if d.get("commission_known", True) else " " + _lbl(lang, "(commission unknown)", "（佣金未知）")
    return "\n".join([
        f"⚪ {_lbl(lang, 'Position closed', '已平仓')} · {d.get('mode')}",
        f"{d.get('symbol')} {_side(lang, d.get('side'))} {_num(d.get('volume'))} lot",
        f"{_lbl(lang, 'net', '净盈亏')}: {_signed(d.get('net'))} {d.get('currency') or ''}{r}{unknown}",
        f"{_lbl(lang, 'Strategy', '策略')}: {d.get('strategy') or '—'}"])


def fmt_stats(day: dict, mode: str, currency: str | None, date: str, lang: str = "EN_ZH") -> str:
    n = day.get("trades") or 0
    wr = day.get("win_rate")
    lines = [f"📊 {_lbl(lang, 'Daily summary', '每日汇总')} {date} · {mode}"]
    if not n:
        lines.append(_pick(lang, "No closed trades today.", "今日无已平仓交易。"))
    else:
        lines.append(f"{_lbl(lang, 'Trades', '交易')}: {n} · {_lbl(lang, 'net', '净盈亏')}: {_signed(day.get('net'))} {currency or ''}")
        lines.append(f"{_lbl(lang, 'Win rate', '胜率')}: {_num(wr, 1) + ' %' if wr is not None else '—'} · PF {_num(day.get('profit_factor'))}")
    lines.append(_pick(lang, "Small samples do not show an edge. Past results do not guarantee future results.",
                       "样本较少无法说明优势。过去的结果不代表未来。"))
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, cfg_store, secrets, db, *, stats_fn=None, clock=time.time):
        self.cfg_store = cfg_store
        self.secrets = secrets
        self.db = db
        self.stats_fn = stats_fn                      # () -> (mode, day_stats, currency) for the daily summary
        self.clock = clock
        self._lock = threading.Lock()
        self.last_ok_at: str | None = None
        self.last_error: str | None = None
        self.last_error_at: str | None = None
        self.sent = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ state
    def _token(self) -> str | None:
        try:
            return self.secrets.get("TELEGRAM_BOT_TOKEN")
        except Exception:
            return None

    def status(self) -> dict:
        cfg = self.cfg_store.get().telegram
        has_token = bool(self._token())
        if not has_token or not cfg.chat_id:
            state = "NOT_CONFIGURED"
        elif not cfg.enabled:
            state = "DISABLED"
        elif self.last_error and (not self.last_ok_at or self.last_error_at > self.last_ok_at):
            state = "ERROR"
        elif self.last_ok_at:
            state = "OK"
        else:
            state = "UNTESTED"
        return {"state": state, "token_set": has_token, "chat_id_set": bool(cfg.chat_id), "enabled": cfg.enabled,
                "send_signals": cfg.send_signals, "send_trades": cfg.send_trades, "send_stats": cfg.send_stats,
                "stats_hour_utc": cfg.stats_hour_utc, "language": cfg.language, "last_ok_at": self.last_ok_at,
                "last_error": self.last_error, "last_error_at": self.last_error_at, "sent": self.sent}

    # ------------------------------------------------------------------ sending
    def _post(self, token: str, chat_id: str, text: str) -> tuple[bool, str | None]:
        """Returns (ok, error). The error is Telegram's description or the exception type - never the token or the URL."""
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3800], "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"{API}/bot{token}/sendMessage", data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read().decode() or "{}")
            if body.get("ok"):
                return True, None
            return False, str(body.get("description") or "Telegram odrzucił wiadomość")[:200]
        except urllib.error.HTTPError as exc:
            try:
                desc = json.loads(exc.read().decode() or "{}").get("description")
            except Exception:
                desc = None
            return False, f"HTTP {exc.code}: {desc or exc.reason}"[:200]
        except Exception as exc:
            return False, f"brak połączenia z api.telegram.org ({type(exc).__name__})"

    def _record(self, ok: bool, err: str | None) -> None:
        with self._lock:
            if ok:
                self.last_ok_at = iso(utcnow())
                self.sent += 1
            else:
                self.last_error, self.last_error_at = err, iso(utcnow())
                log.warning("Telegram send failed: %s", err)

    def _send_async(self, token: str, chat_id: str, text: str) -> None:
        def run():
            ok, err = self._post(token, chat_id, text)
            self._record(ok, err)
        threading.Thread(target=run, daemon=True).start()

    def send_test(self) -> dict:
        """Synchronous test message (works also while notifications are disabled - it checks the token and the chat)."""
        cfg = self.cfg_store.get().telegram
        token = self._token()
        if not token or not cfg.chat_id:
            return {"ok": False, "error": "NOT_CONFIGURED: zapisz token bota i chat_id"}
        text = _pick(cfg.language, "✅ PepeMarketWizard: test message – notifications are configured.", "✅ PepeMarketWizard：测试消息 – 通知已配置。")
        ok, err = self._post(token, cfg.chat_id, text)
        self._record(ok, err)
        return {"ok": ok, "error": err, "status": self.status()}

    def _deliver(self, flag: str, dedup_key: str, text: str) -> bool:
        cfg = self.cfg_store.get().telegram
        token = self._token()
        if not (cfg.enabled and getattr(cfg, flag) and cfg.chat_id and token):
            return False
        if self.db.one("SELECT 1 AS x FROM notifications_sent WHERE dedup_key=?", (dedup_key,)):
            return False
        self.db.execute("INSERT OR IGNORE INTO notifications_sent(dedup_key, ts) VALUES (?,?)", (dedup_key, iso(utcnow())))
        self._send_async(token, cfg.chat_id, text)
        return True

    # ------------------------------------------------------------------ public notifications
    def notify(self, dedup_key: str, text: str) -> None:
        """Legacy free-text signal notification."""
        self._deliver("send_signals", dedup_key, text)

    def signal(self, dedup_key: str, d: dict) -> bool:
        return self._deliver("send_signals", dedup_key, fmt_signal(d, self.cfg_store.get().telegram.language))

    def trade_opened(self, dedup_key: str, d: dict) -> bool:
        return self._deliver("send_trades", "open:" + dedup_key, fmt_opened(d, self.cfg_store.get().telegram.language))

    def trade_closed(self, dedup_key: str, d: dict) -> bool:
        return self._deliver("send_trades", "close:" + dedup_key, fmt_closed(d, self.cfg_store.get().telegram.language))

    def daily_stats_due(self, now: datetime | None = None) -> bool:
        cfg = self.cfg_store.get().telegram
        now = now or datetime.fromtimestamp(self.clock(), timezone.utc)
        if not (cfg.enabled and cfg.send_stats and self.stats_fn) or now.hour < cfg.stats_hour_utc:
            return False
        return not self.db.one("SELECT 1 AS x FROM notifications_sent WHERE dedup_key=?", (f"stats:{now.date().isoformat()}",))

    def send_daily_stats(self, now: datetime | None = None, force: bool = False) -> bool:
        now = now or datetime.fromtimestamp(self.clock(), timezone.utc)
        if not force and not self.daily_stats_due(now):
            return False
        mode, day, cur = self.stats_fn()
        cfg = self.cfg_store.get().telegram
        text = fmt_stats(day or {}, mode, cur, now.date().isoformat(), cfg.language)
        if force:
            token = self._token()
            if not (token and cfg.chat_id):
                return False
            self._send_async(token, cfg.chat_id, text)
            return True
        return self._deliver("send_stats", f"stats:{now.date().isoformat()}", text)

    def start(self) -> None:
        if self._thread:
            return

        def loop():
            while not self._stop.wait(60):
                try:
                    self.send_daily_stats()
                except Exception:
                    log.exception("daily summary failed")

        self._thread = threading.Thread(target=loop, name="telegram-daily", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
