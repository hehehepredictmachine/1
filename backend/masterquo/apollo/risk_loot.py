"""RiskLootCalculator (Apollo23 TASK 025) - TraderLifeGame reward selector for PROCESS quality and risk discipline. It is NOT position sizing.

Score = 25 % setup quality + 30 % risk discipline + 20 % execution adherence + 10 % journal / learning + 15 % evidence quality (0-100 each).
Hard vetoes (any -> no grant): missing critical data (NOT_EVALUABLE), SFB not eligible, Market Trap hard NO_TRADE (a verified, respected
NO_TRADE maps to PATIENCE loot instead), any Risk / STOP breach, strategy RETIRED / RESEARCH_ONLY / UNVALIDATED for live loot, missing canonical
setup attribution. PnL, account size, leverage and notional are never positive features. One canonical reward per (event, policy version);
partial exits are grouped to one position-level award. Items are cosmetic / educational: no cash value, no trading effect. Default OFF.

Default OFF (1.46, audit chunk_05#11): the grant switch lives in the game's own settings (game.sqlite meta, key GRANT_SETTING; not in
config.json) and is OFF until the player turns it on (PUT /api/v1/tlg/loot/settings). While it is OFF, grant() writes nothing unless
the chosen item is marked enabled_by_default=YES in the catalogue (none is today) -> reason GRANT_DISABLED (the API answers 409).
evaluate() keeps working (assessment only, no write).
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
from pathlib import Path

POLICY_VERSION = "RLC-POLICY-1"
DATA = Path(__file__).parent / "data"
WEIGHTS = {"setup_quality": 0.25, "risk_discipline": 0.30, "execution_adherence": 0.20, "journal_learning": 0.10, "evidence_quality": 0.15}
TIERS = ((95, "LEGENDARY"), (90, "EPIC"), (80, "RARE"), (70, "UNCOMMON"), (60, "COMMON"))
SOURCE_MODES = ("SIMULATOR", "MT5_READ_ONLY", "MANUAL_JOURNAL")
GRANT_SETTING = "risk_loot.grant_enabled"


def catalog() -> list[dict]:
    with open(DATA / "t025_loot_catalog.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def mapping() -> dict:
    with open(DATA / "t025_setup_to_loot.csv", encoding="utf-8-sig", newline="") as f:
        return {r["setup_family"]: r for r in csv.DictReader(f)}


def tier(score: float) -> str | None:
    for lo, name in TIERS:
        if score >= lo:
            return name
    return None


def grant_enabled(game) -> bool:
    """The player's switch (game settings); a missing / unreadable value = OFF (the catalogue default)."""
    try:
        r = game._one("SELECT v FROM meta WHERE k = ?", (GRANT_SETTING,))
    except Exception:  # noqa: BLE001 - an unreadable setting is the default (OFF), never an implicit ON
        return False
    return bool(r) and r.get("v") == "1"


def set_grant_enabled(game, on: bool) -> dict:
    if not isinstance(on, bool):
        raise TypeError("grant_enabled: true / false")
    game.db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (GRANT_SETTING, "1" if on else "0"))
    return settings(game)


def settings(game) -> dict:
    return {"grant_enabled": grant_enabled(game), "default": False, "setting": GRANT_SETTING,
            "enabled_by_default_items": [i["item_id"] for i in catalog() if i.get("enabled_by_default") == "YES"],
            "note": "nagrody kosmetyczne (bez wartości pieniężnej i wpływu na handel); domyślnie wyłączone"}


def evaluate(ev: dict, *, enabled_only: bool = False) -> dict:
    """ev: {event_id, position_id?, source_mode, setup_family, strategy_status, sfb_status, trap_no_trade, no_trade_respected, risk_breach,
    attribution, scores{...0-100}, independent_evidence?}. Unknown -> veto, never zero-filled. enabled_only: pick only among the items
    marked enabled_by_default=YES (the catalogue for a grant while the player's switch is OFF)."""
    vetoes = []
    if ev.get("source_mode") not in SOURCE_MODES:
        vetoes.append("UNKNOWN_SOURCE_MODE")
    sc = ev.get("scores") or {}
    # 1.46: scores are validated here too (not only in the API route) - a list was an AttributeError, 'abc' a ValueError, NaN came back
    # as score=NaN (unserialisable JSON), 1e6 / True were accepted as points and 1e6 gave LEGENDARY on a 0-100 scale
    if not isinstance(sc, dict):
        vetoes.append("INVALID_SCORE")
        sc = {}
    elif any(sc.get(k) is not None and (isinstance(sc[k], bool) or not isinstance(sc[k], (int, float)) or not 0 <= sc[k] <= 100)
             for k in WEIGHTS):                  # NaN / inf fail the range check
        vetoes.append("INVALID_SCORE")
    if any(sc.get(k) is None for k in WEIGHTS):
        vetoes.append("DATA_INSUFFICIENT")
    if not ev.get("position_id") and not ev.get("event_id"):
        vetoes.append("EVENT_UNIDENTIFIED")     # 1.46: every such event shared ONE idempotency key (only the first was ever granted)
    if ev.get("risk_breach") is not False:
        vetoes.append("RISK_POLICY_BREACH" if ev.get("risk_breach") else "DATA_INSUFFICIENT")
    if not ev.get("attribution"):
        vetoes.append("SETUP_UNATTRIBUTED")
    fam = ev.get("setup_family") or "UNKNOWN"
    if not isinstance(fam, str):                 # 1.46: a list / dict family was a TypeError (unhashable) -> HTTP 500
        vetoes.append("INVALID_SETUP_FAMILY")
        fam = "UNKNOWN"
    mp = mapping().get(fam) or mapping()["UNKNOWN"]
    if mp["mapping_status"] == "BLOCK_AUTO_GRANT":
        vetoes.append("UNMAPPED_SETUP_FAMILY")
    patience = fam == "VERIFIED_NO_TRADE_VETO"
    if ev.get("trap_no_trade") and not patience:
        vetoes.append("MARKET_TRAP_NO_TRADE")
    if patience and not ev.get("no_trade_respected"):
        vetoes.append("NO_TRADE_NOT_RESPECTED")
    if patience and ev.get("trap_no_trade") is not True:
        vetoes.append("NO_TRADE_NOT_VERIFIED")   # 1.46: PATIENCE loot only for a VERIFIED NO_TRADE (was granted without any veto)
    if not patience:
        if ev.get("sfb_status") != "ELIGIBLE" and ev.get("source_mode") == "MT5_READ_ONLY":
            vetoes.append("SFB_BLOCKED")
        if ev.get("strategy_status") in ("RETIRED", "RESEARCH_ONLY", "UNVALIDATED") and ev.get("source_mode") == "MT5_READ_ONLY":
            vetoes.append("STRATEGY_NOT_ELIGIBLE")
    for forbidden in ("pnl", "account_size", "leverage", "notional"):
        if forbidden in sc:
            vetoes.append(f"{forbidden.upper()}_NOT_REWARD_BASIS")
    if vetoes:
        return {"eligible": False, "vetoes": sorted(set(vetoes)), "score": None, "tier": None, "policy_version": POLICY_VERSION}
    score = round(sum(WEIGHTS[k] * float(sc[k]) for k in WEIGHTS), 1)
    t = tier(score)
    if t == "LEGENDARY" and not ev.get("independent_evidence"):
        t = "EPIC"
    if t == "EPIC" and (sc.get("evidence_quality") or 0) < 80:
        t = "RARE"
    items = [i for i in catalog() if i["loot_family"] == mp["loot_family"] and ev["source_mode"] in i["source_mode"].split(";")
             and (not enabled_only or i.get("enabled_by_default") == "YES")]
    order = ["COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY"]
    pick = None
    if t:
        ok = [i for i in items if order.index(i["rarity"]) <= order.index(t)]
        pick = max(ok, key=lambda i: (order.index(i["rarity"]), i["item_id"])) if ok else None
    return {"eligible": t is not None, "vetoes": [], "score": score, "tier": t, "loot_family": mp["loot_family"], "item": pick,
            "breakdown": {k: sc[k] for k in WEIGHTS}, "policy_version": POLICY_VERSION, "monetary_value": "NONE", "trading_effect": "NONE"}


def grant_key(ev: dict) -> str:
    """Idempotency: one award per canonical position (partial exits grouped) / event and policy version."""
    base = ev.get("position_id") or ev.get("event_id")
    return "rlc:" + hashlib.sha256(f"{ev.get('source_mode')}|{base}|{POLICY_VERSION}".encode()).hexdigest()[:20]


def grant(game, ev: dict) -> dict:
    """Writes the cosmetic item into the TraderLifeGame inventory through the game's append-only ledger (idempotent).
    Switch OFF (default): only an item marked enabled_by_default=YES may be written; otherwise nothing -> reason GRANT_DISABLED."""
    on = grant_enabled(game)
    r = evaluate(ev, enabled_only=not on)
    if not on and r["eligible"] and not r.get("item"):
        return {**r, "granted": False, "grant_enabled": False, "reason": "GRANT_DISABLED"}
    if not r["eligible"] or not r.get("item"):
        return {**r, "granted": False}
    key = grant_key(ev)
    item_id = r["item"]["item_id"]
    # 1.46: the pick is deterministic per tier / family and inventory has PRIMARY KEY(item_id) - a second earned award for another position
    # wrote a new LOOT_GRANT ledger row and answered granted=True while INSERT OR IGNORE added nothing. Same order as GameService.buy:
    # duplicate event first, then an item already owned (no ledger row, granted=False), all under the game's lock.
    with getattr(game, "_lock", None) or contextlib.nullcontext():
        if game._one("SELECT 1 AS x FROM gold_ledger WHERE key = ?", (key,)):
            return {**r, "granted": False, "grant_key": key, "duplicate": True}
        if game._one("SELECT 1 AS x FROM inventory WHERE item_id = ?", (item_id,)):
            return {**r, "granted": False, "grant_key": key, "duplicate": False, "already_owned": True, "reason": "ALREADY_OWNED"}
        new = game._ledger("gold_ledger", key, 0, "LOOT_GRANT", item_id)
        if new:
            game.db.execute("INSERT OR IGNORE INTO inventory(item_id, acquired_at, equipped) VALUES(?, ?, 0)", (item_id, game.clock()))
    return {**r, "granted": new, "grant_key": key, "duplicate": not new}
