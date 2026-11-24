"""Client of the bot's LOCAL HTTP API - one leaf module for the command-line entry points (1.46 arch I0080 / I0075).

Before 1.46 these helpers lived in the entry-point modules themselves (``__main__._port`` / ``__main__._health``,
``train_all.Bot`` / ``train_all._health``) and exports/cli, training/cli, training/runner and studio/app imported them from there,
which tied ten entry-point modules into one import cycle and kept two different ``_health`` implementations.

* ``port()``        the configured server port (data/config.json ``server.port``), paths.DEFAULT_PORT when the configuration cannot be read;
* ``health(port, timeout)``  GET /api/v1/health of the local bot -> dict, or ``None`` when nothing (healthy) answers; each caller keeps
                    its former timeout (__main__ 1.5 s, train_all / training 3 s, Studio 2 s);
* ``Bot``           same-origin client of the local API (session cookie + CSRF token, as the monitor uses).

Only the standard library at module level (``port()`` reads the configuration lazily, as before). The old names stay as aliases
(``__main__._port`` / ``_health``, ``train_all.Bot`` / ``_health``). This is a local HTTP client only - nothing here trades.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request

def port() -> int:
    """The port of the local server from the configuration; paths.DEFAULT_PORT when it cannot be read (same as the former __main__._port)."""
    try:
        from .config import server_port            # 1.46 arch I0094: read-only (no migration write / .bak from a CLI process)
        return server_port()
    except Exception:  # noqa: BLE001 - unreadable configuration -> the default port (as before)
        from .paths import DEFAULT_PORT             # 1.46 arch I0125: the one literal lives in paths.py
        return DEFAULT_PORT


def health(port: int, timeout: float = 1.5) -> dict | None:
    """GET http://127.0.0.1:<port>/api/v1/health -> parsed JSON, or None (no server, not ours, broken answer, timeout).

    One implementation for every entry point: the explicit Host header of the former __main__._health (urllib sends the same value
    itself) and the broad ``except Exception`` of the former train_all._health - None always meant 'no usable server' for the callers."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health", headers={"Host": f"127.0.0.1:{port}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 - every failure means 'no usable server' (URLError, OSError, ValueError, http.client errors)
        return None


class Bot:
    """Same-origin client of the local API (session cookie + CSRF token, as the monitor uses)."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None

    def _req(self, method: str, path: str, body=None, timeout: float = 30):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Origin", self.base)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if self.csrf and method != "GET":
            r.add_header("X-MQ-CSRF", self.csrf)
        try:
            with self.op.open(r, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt)
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(txt)
            except ValueError:
                return e.code, txt

    def login(self) -> None:
        self._req("GET", "/")
        st, j = self._req("GET", "/api/v1/session")
        if st != 200 or not isinstance(j, dict):
            raise RuntimeError(f"SESSION_FAILED {st}")
        self.csrf = j.get("csrf")

    def get(self, path, timeout=30):
        return self._req("GET", path, timeout=timeout)

    def post(self, path, body=None, timeout=60):
        return self._req("POST", path, body or {}, timeout=timeout)
