"""External adapters with an explicit status contract - no fabricated values.

Contract of every snapshot:
  {adapter, status: AVAILABLE | UNAVAILABLE | STALE | UNVALIDATED | UNDOCUMENTED_EXTERNAL, version, symbol, values (numbers or
   null), known_at, received_at, delay_seconds, reason, needs}
A missing variable is null, never 0. Without a verified, licensed interface the adapter stays UNAVAILABLE and the core
works on its own explicit computations. Nothing here reads iCustom buffers: the Python MT5 package cannot read an
arbitrary custom indicator without an MQL5 bridge, and the public description of IQ Gold Gann MT5 states it has no buffer
output for EA integration.

Optional file bridge (for a user who HAS a licensed export): data/scalp/external/<adapter>.json written by the user's own
tool with {symbol, known_at (ISO UTC), values:{...}, source, version}. It is read as-is, checked for symbol and age, and
reported UNVALIDATED (no incremental out-of-sample evidence yet) - never promoted automatically.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import paths

STATUSES = ("AVAILABLE", "UNAVAILABLE", "STALE", "UNVALIDATED", "UNDOCUMENTED_EXTERNAL")

ADAPTERS = {
    "IQ_GOLD_GANN": {"title": "IQ Gold Gann (MT5, produkt 134935; MT4 = 134335)",
                     "reason": "brak licencjonowanego eksportu; opis produktu MT5 wskazuje brak buforów do integracji z EA",
                     "needs": ["licencjonowana wersja MT5 na tym komputerze", "udokumentowany eksport (plik/obiekty wykresu) z nazwami poziomów",
                               "historia snapshotów point-in-time do walidacji"]},
    "IQ_FX_GANN": {"title": "IQ FX Gann (MT5, produkt 119707) – inny produkt niż Gold Gann",
                   "reason": "nie skonfigurowano; algorytmu nie utożsamiamy z Gold Gann", "needs": ["licencja", "udokumentowany eksport"]},
    "IQ_STAR_LINES": {"title": "IQ Star Lines (opis autora: astrologia wedyjska)",
                      "reason": "brak eksportu; twierdzenie autora nie jest dowodem przewagi – tylko SHADOW po osobnym teście przyrostowym",
                      "needs": ["eksport poziomów/czasów", "test przyrostowy poza treningiem"]},
    "VOLATILITY_MASTER": {"title": "Volatility Master (MT4, produkt 111302)",
                          "reason": "produkt MT4 – plik EX4 nie działa w MT5; brak eksportu", "needs": ["wersja MT5 lub eksport", "definicja reżimu"]},
    "LIQUIDATION_HEATMAP": {"title": "Liquidation heatmap (np. CoinGlass, rynek kryptoderywatów XAUT)",
                            "reason": "brak autoryzowanego API użytkownika; XAUT ≠ brokerowy XAUUSD- – nie jest arkuszem zleceń rynku złota",
                            "needs": ["klucz/API opłacony przez użytkownika (bez zakupu przez bota)", "instrument i metoda", "historia snapshotów z source_time",
                                      "basis XAUT vs XAUUSD-"]},
    "SESSION_SWEEP_BOXES_EXT": {"title": "Session Sweep Boxes (zewnętrzny wskaźnik, iCustom bufory 0/1)",
                                "reason": "mapowanie buforów niezweryfikowane w posiadanej wersji; używamy własnego modułu sesji SESS-1.0.0",
                                "needs": ["plik wskaźnika i licencja", "mostek MQL5 eksportujący bufory zamkniętych barów"]},
    "PAL02M": {"title": "PAL02M (narzędzie wskazane przez użytkownika)",
               "reason": "tożsamość i algorytm niepotwierdzone w repozytorium i dokumentacji – UNDOCUMENTED_EXTERNAL",
               "needs": ["pełna nazwa produktu i dostawca", "platforma (MT4/MT5) i wersja", "udokumentowany interfejs (bufory/eksport) z jednostkami",
                         "licencja pozwalająca na odczyt automatyczny", "deklaracja repaint i historia snapshotów"]},
}


def ext_dir() -> Path:
    return paths.data_dir() / "scalp" / "external"


def snapshot(name: str, symbol: str, now: datetime | None = None, max_age_s: float = 120.0) -> dict:
    meta = ADAPTERS[name]
    now = now or datetime.now(timezone.utc)
    base = {"adapter": name, "title": meta["title"], "version": None, "symbol": symbol, "values": None, "known_at": None,
            "received_at": now.isoformat(), "delay_seconds": None, "needs": meta["needs"]}
    if name == "PAL02M":
        return dict(base, status="UNDOCUMENTED_EXTERNAL", reason=meta["reason"])
    f = ext_dir() / f"{name}.json"
    if not f.exists():
        return dict(base, status="UNAVAILABLE", reason=meta["reason"])
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        ka = datetime.fromisoformat(str(d["known_at"]).replace("Z", "+00:00"))
        vals = {k: (float(v) if isinstance(v, (int, float)) else None) for k, v in (d.get("values") or {}).items()}
    except Exception as exc:                                  # malformed export -> unavailable, never a value
        return dict(base, status="UNAVAILABLE", reason=f"nieczytelny eksport: {type(exc).__name__}")
    if d.get("symbol") != symbol:
        return dict(base, status="UNAVAILABLE", reason=f"symbol eksportu {d.get('symbol')!r} ≠ {symbol!r}")
    if ka > now:
        return dict(base, status="UNAVAILABLE", reason="known_at w przyszłości")
    delay = (now - ka).total_seconds()
    st = "STALE" if delay > max_age_s else "UNVALIDATED"
    return dict(base, status=st, values=vals, known_at=ka.isoformat(), delay_seconds=round(delay, 1), version=d.get("version"),
                source=d.get("source"), reason="eksport użytkownika – brak dowodu przyrostowej wartości poza treningiem" if st == "UNVALIDATED"
                else f"eksport starszy niż {max_age_s:.0f} s")


def all_snapshots(symbol: str, now: datetime | None = None) -> list[dict]:
    return [snapshot(n, symbol, now) for n in ADAPTERS]
