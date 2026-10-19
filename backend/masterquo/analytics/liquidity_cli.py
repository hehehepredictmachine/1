"""`python -m masterquo liquidity <cmd>` (25_LIQUIDITY.bat): status | sessions | poll | import | evaluate. Exit 0 ok, 2 blocked, 1 error.
Never sends orders; the key is read from the SecretStore / env COINGLASS_API_KEY and never printed."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo liquidity", description="Boksy sesji + heatmapa likwidacji (PMW-UPD-06)")
    sub = ap.add_subparsers(dest="c", required=True)
    for n in ("status", "sessions", "poll", "import", "evaluate"):
        s = sub.add_parser(n)
        s.add_argument("--asset", choices=("XAUUSD", "BTC"), default="XAUUSD")
        if n == "evaluate":
            s.add_argument("--dataset")
            s.add_argument("--commission", type=float)
            s.add_argument("--allow-synthetic-fixture", action="store_true")
        if n == "sessions":
            s.add_argument("--profile")
    a = ap.parse_args(argv)
    from ..config import ConfigStore
    from ..db.database import Database
    from ..secrets_store import SecretStore
    from .liquidation.service import LiquidityService
    db = Database()
    liq = LiquidityService(ConfigStore(), db, None, None, secrets=SecretStore())
    if a.c == "status":
        print(json.dumps({k: v for k, v in liq.heatmap_public(a.asset, None, 0).items() if k != "grid"}, indent=1, ensure_ascii=False, default=str))
        return 0
    if a.c == "poll":
        print(json.dumps({"polled": liq.poll_once(time.monotonic() + 10 ** 9)}, indent=1))
        st = liq.heatmap_public(a.asset, None, 0)
        print(json.dumps({"status": st["status"], "source_status": st.get("source_status")}, indent=1, default=str))
        return 0 if st["status"] in ("OK", "STALE") else 2
    if a.c == "import":
        print(json.dumps(liq.scan_inbox(), indent=1, ensure_ascii=False))
        return 0
    from ..extind.cli import _latest_real
    if a.c == "sessions":
        ds = _latest_real(a.asset)
        if ds is None:
            print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA (00_TRENING_START.bat)")
            return 2
        from ..extind.trainer import _bars
        meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
        m1 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M1")
        r = liq.sessions(m1, 60, a.asset, (m1[-1]["open_utc"] if m1 else None), a.profile, days=3)
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str)[:20000])
        return 0
    from . import liquidity_eval as le
    ds = Path(a.dataset) if a.dataset else _latest_real(a.asset)
    if ds is None or not (ds / "source_metadata.json").exists():
        print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA (00_TRENING_START.bat) – podaj --dataset")
        return 2
    if json.loads((ds / "source_metadata.json").read_text(encoding="utf-8")).get("data_kind") != "REAL_USER_DATA" and not a.allow_synthetic_fixture:
        print("[BLAD] dane syntetyczne nie są źródłem oceny")
        return 2
    try:
        rep = le.evaluate(a.asset, ds, commission=a.commission, db=db, liquidity=liq)
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    p = le.save_report(rep)
    print(json.dumps({k: (v["status"] if isinstance(v, dict) and "status" in v else v) for k, v in rep["variants"].items()}, indent=1))
    print(f"Raport: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
