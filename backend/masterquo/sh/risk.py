"""Shared risk engine for SCALPING and HEDGING. Risk and data checks have priority over every model signal: a BLOCK here can
never be overridden by a score or a probability.

Sizing: volume = floor(risk budget / loss per lot at SL including costs), capped by volume_max, exposure and margin; the result
must allow the configured partial split (or the explicitly configured two-leg fallback) - otherwise BLOCK with the reason.
HEDGING: exposure and margin are checked for the WORST gross case (primary + max hedge ratio), the basket loss budget
(basket_loss_limit_x_risk x trade risk) must fit into risk_per_basket_pct, and the account must be a HEDGING account.
"""
from __future__ import annotations

from .units import SymbolSpec, UnitError

REAL_MODES = ("AUTO_DEMO", "AUTO_LIVE")


def evaluate(*, setup: dict, spec: SymbolSpec, prof: dict, cfg: dict, inst: str, account: dict, state: dict, exec_mode: str,
             now: float, quote: dict | None) -> dict:
    """account: equity, margin, margin_free, margin_mode (HEDGING/NETTING/EXCHANGE/UNKNOWN), margin_per_lot (account currency
    for 1 lot at the current price, from order_calc_margin), currency.
    state: open_plans [{plan_id, strategy, symbol, side, volume, hedge_volume, state}], daily_realized_money,
    last_close_at {strategy: t}, recent_signals [{signal_id, strategy, side, created_at}], foreign_positions (count of
    positions on the symbol owned by another manager)."""
    r = cfg["risk"]
    ic = prof.get("_instrument") or {}
    checks, warn = [], []

    def chk(cid, ok, detail):
        checks.append({"id": cid, "ok": bool(ok), "detail": detail})
        return ok

    strat = setup["strategy"]
    side = setup.get("side")
    out = {"status": "BLOCK", "checks": checks, "warnings": warn, "volume": 0.0, "legs": [], "shares_used": None}

    def done():
        bad = [c for c in checks if not c["ok"]]
        out["status"] = "PASS" if not bad else "BLOCK"
        out["reasons"] = [f"{c['id']}: {c['detail']}" for c in bad]
        return out

    # --- validity / mode -------------------------------------------------------------------------------------------------
    if not chk("setup_ready", setup.get("status") == "READY", f"status setupu {setup.get('status')}"):
        return done()
    if not chk("not_expired", now <= float(setup.get("valid_until") or 0), "setup wygasł (TTL)"):
        return done()
    if exec_mode == "AUTO_LIVE":
        chk("exec_mode", False, "AUTO_LIVE dla SCALPING/HEDGING zablokowane – brak zaliczonej walidacji na danych klienta")
    if exec_mode in REAL_MODES:
        chk("model_mode", setup.get("model_mode") == "PEŁNA",
            "tryb OGRANICZONY (brak skalibrowanego modelu zdarzenia) – dozwolone tylko SIGNALS/PAPER")
        chk("commission_known", ic.get("commission_per_lot_side") is not None, "prowizja instrumentu nieznana – koszt nie jest pełny")
    if strat == "HEDGING":
        chk("account_hedging", account.get("margin_mode") == "HEDGING",
            f"rachunek {account.get('margin_mode')} – HEDGING wymaga rachunku typu hedging (brak cichego zastępowania)")
    # --- data ------------------------------------------------------------------------------------------------------------
    q_age = (quote or {}).get("age_s")
    chk("quote_fresh", q_age is not None and q_age <= r["max_quote_age_s"], f"wiek notowania {q_age} s (limit {r['max_quote_age_s']})")
    spread = (quote or {}).get("spread")
    lim_sp = ic.get("max_spread_usd")
    chk("spread", spread is not None and (lim_sp is None or spread <= lim_sp), f"spread {spread} (limit {lim_sp})")
    # --- account-level limits --------------------------------------------------------------------------------------------
    eq = float(account.get("equity") or 0)
    if not chk("equity", eq > 0, f"equity {eq}"):
        return done()
    dl = -abs(r["daily_loss_limit_pct"]) / 100.0 * eq
    chk("daily_loss", float(state.get("daily_realized_money") or 0) > dl, f"dzienny wynik {state.get('daily_realized_money')} ≤ limit {dl:.2f}")
    opens = [p for p in state.get("open_plans") or [] if p.get("state") not in ("CLOSED",)]
    npos = sum(1 + (1 if p.get("hedge_volume") else 0) for p in opens)
    chk("max_positions", npos + (2 if strat == "HEDGING" else 1) <= r["max_open_positions"],
        f"otwarte pozycje SH {npos} + nowe > limit {r['max_open_positions']}")
    lc = (state.get("last_close_at") or {}).get(strat)
    chk("cooldown", lc is None or now - lc >= 60 * r["cooldown_minutes"], f"cooldown {r['cooldown_minutes']} min po ostatnim zamknięciu")
    dup = [s for s in state.get("recent_signals") or []
           if s["signal_id"] == setup.get("signal_id") or (s["strategy"] == strat and s["side"] == side and now - s["created_at"] < 60 * r["duplicate_window_minutes"])]
    chk("duplicate", not dup, f"duplikat sygnału ({dup[0]['signal_id']})" if dup else "")
    chk("foreign_owner", not state.get("foreign_positions"), f"{state.get('foreign_positions')} pozycji innego menedżera na symbolu – jeden właściciel")

    # --- sizing ----------------------------------------------------------------------------------------------------------
    try:
        mpp = spec.money_per_price(1.0)
    except UnitError as exc:
        chk("tick_value", False, str(exc))
        return done()
    sl_dist = abs(setup["entry_ref"] - setup["sl"])
    cost_price = float((setup.get("costs") or {}).get("round_trip_price") or 0.0)
    comm = ic.get("commission_per_lot_side")
    loss_per_lot = (sl_dist + cost_price) * mpp + (2 * comm if comm is not None else 0.0)
    risk_budget = eq * r["risk_per_trade_pct"] / 100.0
    vol = spec.floor_volume(risk_budget / loss_per_lot) if loss_per_lot > 0 else 0.0
    if spec.volume_max:
        vol = min(vol, spec.floor_volume(spec.volume_max))
    hedge_mult = 1.0 + ((prof.get("hedge") or {}).get("max_ratio", 0.0) if strat == "HEDGING" else 0.0)
    cur_expo = sum(float(p.get("volume") or 0) + float(p.get("hedge_volume") or 0) for p in opens)
    max_expo = (r.get("max_exposure_lots") or {}).get(inst)
    if max_expo is not None:
        room = max(0.0, max_expo - cur_expo)
        vol = min(vol, spec.floor_volume(room / hedge_mult))
    mpl = account.get("margin_per_lot")
    if mpl:
        margin_room = eq * r["max_margin_use_pct"] / 100.0 - float(account.get("margin") or 0)
        vol = min(vol, spec.floor_volume(max(0.0, margin_room) / (mpl * hedge_mult)))
    else:
        warn.append("brak wyceny depozytu (order_calc_margin) – depozyt sprawdzi order_check przed wysłaniem")
    if not chk("min_volume", vol >= spec.volume_min - 1e-9,
               f"budżet ryzyka {risk_budget:.2f} / strata na lot {loss_per_lot:.2f} → {vol} < min lot {spec.volume_min} (lub limit ekspozycji/depozytu)"):
        return done()
    shares = list(prof["shares"])
    sp = spec.split(vol, shares)
    used = "PRIMARY"
    if sp["status"] != "OK" and prof.get("shares_fallback_two"):
        sp2 = spec.split(vol, list(prof["shares_fallback_two"]))
        if sp2["status"] == "OK":
            sp, used, shares = sp2, "FALLBACK_TWO (TP1+TP2, bez TP3)", list(prof["shares_fallback_two"])
            warn.append(f"trzy części niewykonalne przy {vol} lot – użyty skonfigurowany fallback {shares}: {sp2}")
    if not chk("split", sp["status"] == "OK", sp.get("reason", "")):
        return done()
    risk_money = vol * loss_per_lot
    out.update(volume=vol, legs=sp["legs"], shares_used={"variant": used, "shares": shares}, loss_per_lot=round(loss_per_lot, 4),
               risk_money=round(risk_money, 2), risk_pct=round(100 * risk_money / eq, 4), money_per_price_per_lot=mpp,
               margin_required=round(mpl * vol * hedge_mult, 2) if mpl else None, gross_exposure_after=round(cur_expo + vol * hedge_mult, 4))
    if strat == "HEDGING":
        h = prof["hedge"]
        basket_budget = eq * r["risk_per_basket_pct"] / 100.0
        basket_limit = h["basket_loss_limit_x_risk"] * risk_money
        out["basket_loss_limit_money"] = round(basket_limit, 2)
        chk("basket_budget", basket_limit <= basket_budget + 1e-9, f"limit straty koszyka {basket_limit:.2f} > budżet koszyka {basket_budget:.2f}")
    return done()
