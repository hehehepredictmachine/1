"""Optional Telegram notifications (legacy M15 feature) - disabled by default.

Sends analytical notifications only (never orders). Deduplicated by key in SQLite.
The bot token is a local secret; chat_id is configuration. Failure never affects trading logic.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request

from ..timeutil import iso, utcnow

log = logging.getLogger("masterquo.telegram")


class TelegramNotifier:
    def __init__(self, cfg_store, secrets, db):
        self.cfg_store = cfg_store
        self.secrets = secrets
        self.db = db

    def notify(self, dedup_key: str, text: str) -> None:
        cfg = self.cfg_store.get().telegram
        token = self.secrets.get("TELEGRAM_BOT_TOKEN")
        if not (cfg.enabled and cfg.send_signals and cfg.chat_id and token):
            return
        if self.db.one("SELECT 1 AS x FROM notifications_sent WHERE dedup_key=?", (dedup_key,)):
            return
        self.db.execute("INSERT OR IGNORE INTO notifications_sent(dedup_key, ts) VALUES (?,?)", (dedup_key, iso(utcnow())))
        threading.Thread(target=self._send, args=(token, cfg.chat_id, text), daemon=True).start()

    @staticmethod
    def _send(token: str, chat_id: str, text: str) -> None:
        try:
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500], "disable_web_page_preview": "true"}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                json.loads(r.read().decode() or "{}")
        except Exception as exc:  # token never logged
            log.warning("Telegram send failed: %s", type(exc).__name__)
