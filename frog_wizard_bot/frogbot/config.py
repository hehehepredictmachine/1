"""Configuration (data/config.json) and secrets (never in config.json).

Secrets: TELEGRAM_BOT_TOKEN and MT5_PASSWORD_<account id>. On Windows they are encrypted with DPAPI (readable only by the same
Windows user on the same machine); elsewhere stored in data/secrets.json with file mode 0600. Environment variables with the
same names take precedence (FROG_ prefix optional). Secret values are never returned by the configurator API or logged.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import secrets as _secrets
from pathlib import Path

DEFAULT = {
    "schema": "frog-wizard-1",
    "telegram": {"enabled": False, "channel_id": "", "owner_ids": [], "admin_ids": [], "public_commands": True, "allowed_chat_ids": [],
                 "public_show_money": True, "language_order": "en_zh", "rate_limit_seconds": 3,
                 "publish": {"opened": True, "closed": True, "partial": True, "protection": True, "connection": True},
                 "missed_events_window_minutes": 60},
    "accounts": [],
    "reporting": {"timezone_offset_minutes": 0, "breakeven_tolerance": None, "currency_digits": 2, "roi_method": "auto", "snapshot_minutes": 5},
    "sync": {"poll_seconds": 10, "allow_login_switch": False, "history_days": 3650},
}
ACCOUNT_DEFAULT = {"id": "", "label": "", "server": "", "login": 0, "terminal_path": "", "enabled": True, "publish_events": True,
                   "magic_filter": [], "symbol_filter": [], "server_utc_offset_minutes": "auto"}


def data_dir() -> Path:
    d = Path(os.environ.get("FROG_DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = copy.deepcopy(a)
        for k, v in b.items():
            out[k] = _merge(a.get(k), v) if k in a else copy.deepcopy(v)
        return out
    return copy.deepcopy(b)


def load() -> dict:
    p = data_dir() / "config.json"
    cfg = _merge(DEFAULT, json.loads(p.read_text(encoding="utf-8"))) if p.exists() else copy.deepcopy(DEFAULT)
    cfg["accounts"] = [_merge(ACCOUNT_DEFAULT, a) for a in cfg.get("accounts") or []]
    return cfg


ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def validate(cfg: dict) -> list[str]:
    e = []
    t = cfg["telegram"]
    if t.get("language_order") not in ("en_zh", "zh_en"):
        e.append("telegram.language_order: en_zh lub zh_en")
    for k in ("owner_ids", "admin_ids", "allowed_chat_ids"):
        if not all(isinstance(x, int) for x in t.get(k) or []):
            e.append(f"telegram.{k}: liczby całkowite (identyfikatory Telegram)")
    if t.get("enabled") and not t.get("channel_id"):
        e.append("telegram.channel_id: wymagany, gdy bot jest włączony")
    if t.get("enabled") and not t.get("owner_ids"):
        e.append("telegram.owner_ids: podaj co najmniej jednego właściciela (dostęp do /account)")
    ids = set()
    for a in cfg["accounts"]:
        if not ID_RE.match(str(a.get("id") or "")):
            e.append(f"konto {a.get('id')!r}: id 1-32 znaki A-Z a-z 0-9 _ -")
        if a["id"] in ids:
            e.append(f"konto {a['id']}: zduplikowane id")
        ids.add(a["id"])
        if not a.get("label"):
            e.append(f"konto {a['id']}: etykieta (publiczna nazwa) wymagana")
        if not isinstance(a.get("login"), int) or a["login"] <= 0 or not a.get("server"):
            e.append(f"konto {a['id']}: login (liczba) i serwer wymagane")
        off = a.get("server_utc_offset_minutes")
        if off != "auto" and not (isinstance(off, int) and -840 <= off <= 840):
            e.append(f"konto {a['id']}: server_utc_offset_minutes = 'auto' albo minuty -840..840")
    r = cfg["reporting"]
    if r.get("roi_method") not in ("auto", "simple", "dietz", "twr"):
        e.append("reporting.roi_method: auto / simple / dietz / twr")
    if not isinstance(r.get("currency_digits"), int) or not 0 <= r["currency_digits"] <= 4:
        e.append("reporting.currency_digits: 0..4")
    if r.get("breakeven_tolerance") is not None and (not isinstance(r["breakeven_tolerance"], (int, float)) or r["breakeven_tolerance"] < 0):
        e.append("reporting.breakeven_tolerance: liczba >= 0 albo puste")
    if not isinstance(cfg["sync"].get("poll_seconds"), int) or cfg["sync"]["poll_seconds"] < 3:
        e.append("sync.poll_seconds >= 3")
    return e


def save(cfg: dict) -> None:
    errs = validate(cfg)
    if errs:
        raise ValueError("; ".join(errs))
    p = data_dir() / "config.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def account_key(server: str, login: int) -> str:
    """Protected account identifier stored in the database (salted hash; the login is not stored)."""
    sp = data_dir() / "salt.bin"
    if not sp.exists():
        sp.write_bytes(_secrets.token_bytes(32))
    return "ACC-" + hashlib.sha256(sp.read_bytes() + f"{server}:{login}".encode()).hexdigest()[:16]


def mask_login(login: int) -> str:
    s = str(login)
    return "****" + s[-3:] if len(s) > 3 else "****"


# ------------------------------------------------------------------------------------------------ secrets
class Secrets:
    NAMES = re.compile(r"^(TELEGRAM_BOT_TOKEN|MT5_PASSWORD_[A-Za-z0-9_-]{1,32})$")

    def __init__(self, directory: Path | None = None):
        self.dir = directory or data_dir()
        self.win = os.name == "nt"
        self.path = self.dir / ("secrets.dpapi.json" if self.win else "secrets.json")

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, name: str) -> str | None:
        env = os.environ.get(name) or os.environ.get("FROG_" + name)
        if env:
            return env
        v = self._read().get(name)
        if v is None:
            return None
        return _dpapi(base64.b64decode(v), False).decode() if self.win else v

    def set(self, name: str, value: str | None) -> None:
        if not self.NAMES.match(name):
            raise ValueError("UNKNOWN_SECRET")
        d = self._read()
        if value:
            d[name] = base64.b64encode(_dpapi(value.encode(), True)).decode() if self.win else value
        else:
            d.pop(name, None)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        if not self.win:
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def status(self, name: str) -> str:
        if os.environ.get(name) or os.environ.get("FROG_" + name):
            return "ENV"
        return "SET" if name in self._read() else "MISSING"


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = BLOB(len(data), buf), BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI_FAILED")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
