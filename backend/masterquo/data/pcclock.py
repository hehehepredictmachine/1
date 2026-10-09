"""Independent check of the PC clock against an HTTPS server's `Date` header.

The broker offset is measured relative to the PC clock, so a wrong PC clock would shift every
UTC timestamp. This check is coarse (1 s resolution of the Date header) and optional.
"""
from __future__ import annotations

import email.utils
import threading
import urllib.request
from datetime import datetime

from ..timeutil import UTC, iso, utcnow


class PCClockCheck:
    def __init__(self, url: str | None, max_skew: float):
        self.url = url
        self.max_skew = max_skew
        self.result: dict = {"status": "NOT_CHECKED" if url else "DISABLED", "skew_seconds": None, "checked_at": None, "source": url}
        self._lock = threading.Lock()

    def check(self) -> dict:
        if not self.url:
            return self.result
        sent = utcnow()
        try:
            req = urllib.request.Request(self.url, method="HEAD", headers={"User-Agent": "MasterQUO-AI-clockcheck"})
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    date_hdr = resp.headers.get("Date")
            except urllib.error.HTTPError as e:  # 4xx still carries a Date header
                date_hdr = e.headers.get("Date")
            recv = utcnow()
            if not date_hdr:
                raise ValueError("NO_DATE_HEADER")
            server = email.utils.parsedate_to_datetime(date_hdr).astimezone(UTC)
            mid = sent + (recv - sent) / 2
            skew = (mid - server).total_seconds()
            status = "OK" if abs(skew) <= self.max_skew else "SKEW"
            res = {"status": status, "skew_seconds": round(skew, 1), "checked_at": iso(recv), "source": self.url,
                   "note": "rozdzielczość nagłówka Date = 1 s"}
        except Exception as exc:  # network down etc. -> unknown, not OK
            res = {"status": "UNAVAILABLE", "skew_seconds": None, "checked_at": iso(utcnow()), "source": self.url,
                   "error": type(exc).__name__}
        with self._lock:
            self.result = res
        return res

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.result)


__all__ = ["PCClockCheck", "datetime"]
