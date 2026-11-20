"""Czas z internetu dla licencji (1.44.0): nagłówek Date odpowiedzi HTTPS, krótki limit czasu (3 s), kilka serwerów równolegle –
pierwsza odpowiedź wygrywa. Wynik (przesunięcie względem zegara komputera) jest pamiętany 10 min, więc kolejne sprawdzenia licencji
(Guard, start trybu) nie czekają na sieć. Brak internetu = None (wtedy licencja używa zegara komputera z ochroną przed cofnięciem)."""
from __future__ import annotations

import email.utils
import os
import threading
import time
import urllib.error
import urllib.request

from .edition import dev_overrides

HOSTS = ("https://www.google.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace", "https://www.microsoft.com/")
TIMEOUT_S = 3.0
TTL_S = 600.0


def _one(url: str, out: list, done: threading.Event) -> None:
    sent = time.time()
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "PepeMarketWizard-license-time"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                hdr = r.headers.get("Date")
        except urllib.error.HTTPError as e:                          # 4xx/5xx też niosą Date
            hdr = e.headers.get("Date")
        recv = time.time()
        if hdr:
            server = email.utils.parsedate_to_datetime(hdr).timestamp()
            out.append(server - (sent + (recv - sent) / 2))         # przesunięcie: czas serwera − zegar komputera
            done.set()
    except Exception:  # noqa: BLE001 - brak sieci / proxy / TLS = ten serwer pomijamy
        pass


def fetch_offset(timeout: float = TIMEOUT_S) -> float | None:
    """Przesunięcie [s] zegara komputera względem czasu z internetu albo None (brak odpowiedzi w `timeout`)."""
    out: list = []
    done = threading.Event()
    for u in HOSTS:
        threading.Thread(target=_one, args=(u, out, done), name="license-nettime", daemon=True).start()
    done.wait(timeout + 0.5)
    return out[0] if out else None


class NetClock:
    def __init__(self, fetch=fetch_offset):
        self.fetch = fetch
        self._lock = threading.Lock()
        self._offset: float | None = None
        self._at: float | None = None                               # monotoniczny czas pomiaru

    def offset(self, *, refresh: bool = False) -> float | None:
        if dev_overrides():
            v = os.environ.get("PMW_TEST_NET_OFFSET")                # testy: "none" = brak internetu, liczba = przesunięcie [s]
            if v is not None:
                return None if v.lower() == "none" else float(v)
        with self._lock:
            fresh = self._at is not None and time.monotonic() - self._at < TTL_S
            if fresh and not refresh:
                return self._offset
        off = self.fetch()
        with self._lock:
            if off is not None or self._at is None or time.monotonic() - self._at >= TTL_S:
                self._offset, self._at = off, time.monotonic()
            return self._offset
