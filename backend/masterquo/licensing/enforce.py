"""What happens when the license stops being valid (expired, revoked, blocked, device reset, no fresh lease).

* new analyses / setups / ML training / agent calls / NEW opening orders stop (checked by LicenseGuard at each entry point);
* data, trade history and models are kept;
* positions are NOT closed automatically. The limited protection module keeps working for positions owned by the bot
  (magic number): viewing, existing SL/TP on the broker side, the previously fixed protective handling (TP1 partial close,
  stop to break-even) and manual close / reduce - never increasing exposure;
* pending OPENING orders placed by the bot (same magic, pending types) are cancelled; protective orders and manual /
  foreign orders are left alone. If an order got filled while being cancelled, the remove fails, the terminal state is
  reconciled and the resulting position is protected like any other bot position.
"""
from __future__ import annotations

import logging

log = logging.getLogger("masterquo.enforce")
PENDING_OPENING_TYPES = (2, 3, 4, 5, 6, 7)       # BUY/SELL LIMIT, STOP, STOP_LIMIT
TRADE_RETCODE_DONE = 10009


def cancel_bot_opening_orders(bridge, cfg_store, applog=None, manager=None) -> dict:
    magic = int(cfg_store.get().mt5.magic_number)
    try:
        orders = bridge.raw_call(lambda m: m.orders_get(), 0) or ()
    except Exception as exc:
        return {"cancelled": [], "failed": [], "error": f"{type(exc).__name__}"}
    rows = []
    for o in orders:
        d = o._asdict() if hasattr(o, "_asdict") else (o if isinstance(o, dict) else {k: getattr(o, k, None) for k in ("ticket", "type", "magic", "symbol", "position_id")})
        rows.append(d)
    cancelled, failed = [], []
    for d in rows:
        if d.get("magic") != magic or d.get("type") not in PENDING_OPENING_TYPES or d.get("position_id"):
            continue                                            # manual / foreign / protective orders are untouched
        try:
            r = bridge.raw_call(lambda m, t=d["ticket"]: m.order_send({"action": m.TRADE_ACTION_REMOVE, "order": int(t)}), 0)
            ok = r is not None and getattr(r, "retcode", None) == TRADE_RETCODE_DONE
        except Exception:
            ok = False
        (cancelled if ok else failed).append(d["ticket"])
    if failed and manager is not None:
        try:
            manager.tick()                                      # race with execution: reconcile and protect what exists
        except Exception:
            log.exception("reconcile after failed cancel")
    if applog and (cancelled or failed):
        applog.warn("LICENSE", "PENDING_ORDERS", f"Licencja nieważna: anulowano zlecenia otwierające bota {cancelled}; "
                                                 f"nieudane (możliwa realizacja – uzgodniono z terminalem): {failed}")
    return {"cancelled": cancelled, "failed": failed}
