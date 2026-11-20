"""1.41 upgrade steps (idempotent, recorded in <data>/upgrade/1.41.0.json):

  before()   once, at the very start of the first 1.41 run, BEFORE any 1.41 service reads its settings: inventory "before" + a snapshot
             of every configuration file the update touches (<data>/backups/pre-1.41.0/) - the rollback source. Ledgers / databases are
             NOT copied: a rollback restores configuration and routing, never older trade / event history.
  after(rt)  after the services started: inventory "after" + strategy_preservation.json + model_inventory_after.json.
  auto_install(rt)  TiRex-2 then TabICLv2 installed in the background (own environments + pinned weights) when missing; at most one
             attempt per 24 h; never while the user switched auto_install off. The bot works during the installation.

Activation policy of the update: DIRECT_USER_REQUEST (enabled, autostart, analysis use ACTIVE as soon as the technical inputs exist;
no SHADOW / backtest / win-rate gate). It never changes the account execution mode, STOP, risk, stakes or leverage.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from . import inventory as INV

VERSION = "1.41.0"
SNAPSHOT_FILES = ("config.json", "sh/config_override.json", "sh/pack_override.json", "tsfm/settings.json", "quant/settings.json",
                  "kronos/settings.json", "research/settings.json", "baskets/settings.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path() -> Path:
    p = paths.data_dir() / "upgrade"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{VERSION}.json"


def state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    p = state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def backup_dir() -> Path:
    return paths.data_dir() / "backups" / f"pre-{VERSION}"


def before() -> dict:
    st = state()
    if st.get("before_done"):
        return st
    d = paths.data_dir()
    bdir = backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for rel in SNAPSHOT_FILES:
        src = d / rel
        if src.is_file():
            dst = bdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():                           # first snapshot wins (a re-run never overwrites the pre-update state)
                shutil.copy2(src, dst)
            saved.append(rel)
    try:
        rep = INV.write_reports("before")
    except Exception as exc:  # noqa: BLE001
        rep = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    st.update(version=VERSION, before_done=True, before_at=_now(), snapshot_dir=str(bdir), snapshot_files=saved, reports_before=rep,
              activation_policy="DIRECT_USER_REQUEST",
              activation_scope=["tsfm:tirex2 (analysis ACTIVE; hold-roles OBSERVE)", "quant:tabicl_v2 (confidence estimator)",
                                "research modules (ETC, G7, graph, SDformerFlow, COA, BChimp)", "baskets (9 x 10 profiles, SIGNALS)"],
              not_changed=["account execution mode", "STOP", "risk / stakes / leverage", "existing strategy parameters and switches"])
    _save(st)
    return st


def after(rt) -> dict:
    st = state()
    try:
        rep = INV.write_reports("after", rt.cfg)
        from . import preservation as P
        catalog = []
        try:
            from ..baskets import catalog as BC
            catalog = BC.preservation_view()
        except Exception:  # noqa: BLE001
            catalog = []
        pres = P.write(paths.data_dir() / "reports", new_catalog=catalog)
        st.update(after_at=_now(), reports_after=rep, preservation=pres["result"], preservation_counts={k: len(pres[k]) for k in (
            "missing_strategy_ids", "unexpected_config_changes", "duplicate_execution_routes", "orphaned_history_keys")})
    except Exception as exc:  # noqa: BLE001
        st.update(after_error=f"{type(exc).__name__}: {exc}"[:300])
    _save(st)
    return st


def auto_install(rt) -> dict:
    """TiRex-2 -> TabICLv2, sequential (one heavy job at a time), background; one attempt per 24 h."""
    st = state()
    cfg = st.get("auto_install") or {}
    if cfg.get("enabled") is False:
        return {"ok": False, "reason": "auto_install wyłączony przez użytkownika"}
    if time.time() - float(cfg.get("last_try") or 0) < 86400:
        return {"ok": False, "reason": "ostatnia próba < 24 h temu"}
    from ..tsfm.settings import find_python
    from ..quant import tabicl as QT
    need_tirex = find_python("tirex2", rt.tsfm.settings.get().models["tirex2"]) is None
    need_tabicl = QT.find_python() is None or not QT.installed(0)["weights"]
    try:
        from tsfm_runtime import manifest as TM
        need_tirex = need_tirex or not TM.summary(str(rt.tsfm.weights_root()), "tirex2")["installed"]
    except Exception:  # noqa: BLE001
        pass
    if not (need_tirex or need_tabicl):
        return {"ok": True, "reason": "oba modele zainstalowane"}
    cfg.update(enabled=True, last_try=time.time(), started_at=_now(), tirex2=need_tirex, tabicl=need_tabicl)
    st["auto_install"] = cfg
    _save(st)

    def tabicl_job(*_a):
        if need_tabicl:
            import sys
            from ..tsfm.settings import default_weights_root
            argv = [sys.executable, str(paths.ROOT_DIR / "tools" / "tsfm_setup.py"), "--model", "tabicl", "--root", str(paths.ROOT_DIR),
                    "--weights-root", str(default_weights_root())]
            rt.tsfm._run_job_proc("install_tabicl", argv, on_done=lambda ok, job: QT._INST_CACHE.clear())

    def run():
        time.sleep(30)                                        # after the start burst (feed, UI) - installation is background work
        if need_tirex:
            r = rt.tsfm.start_install("tirex2")
            if r.get("ok"):
                for _ in range(3600):                         # wait for the TiRex-2 job (max 1 h) before the TabICL job: one heavy job
                    j = rt.tsfm.job("install_tirex2") or {}
                    if j.get("state") in ("DONE", "FAILED", "CANCELLED"):
                        break
                    time.sleep(1)
        tabicl_job()
    threading.Thread(target=run, name="ai141-autoinstall", daemon=True).start()
    rt.log.info("UPGRADE", "AI_AUTO_INSTALL", "Automatyczna instalacja modeli 1.41 w tle: "
                + ", ".join(x for x, n in (("TiRex-2", need_tirex), ("TabICLv2", need_tabicl)) if n) + " (bot działa dalej).")
    return {"ok": True, "tirex2": need_tirex, "tabicl": need_tabicl}


def rollback_config() -> dict:
    """Restore the configuration snapshot (not the ledgers): every file that existed before the update gets its pre-update content."""
    bdir = backup_dir()
    if not bdir.is_dir():
        return {"ok": False, "reason": "brak migawki pre-1.41.0"}
    restored = []
    for rel in SNAPSHOT_FILES:
        src = bdir / rel
        if src.is_file():
            dst = paths.data_dir() / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel)
    st = state()
    st.setdefault("rollbacks", []).append({"at": _now(), "restored": restored})
    _save(st)
    return {"ok": True, "restored": restored, "note": "ledgery, historia transakcji i zdarzeń po aktualizacji pozostają bez zmian"}


# ====================================================================== 1.42 (DIRECT_USER_REQUEST, recorded in <data>/upgrade/1.42.0.json)
V142 = "1.42.0"


def _st142_path() -> Path:
    p = paths.data_dir() / "upgrade"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{V142}.json"


def state_142() -> dict:
    try:
        return json.loads(_st142_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_142(rt) -> dict:
    """Once per installation (idempotent): the user's 1.42 decision "Modele: OBSERVE -> ASSIST, 90 strategii: zlecenia FOREX".
      * Chronos-2 / Granite TTM / TiRex-2: every path (ACTIVE / SCALPING / HEDGING) OBSERVE -> ASSIST (DIRECT_USER_REQUEST, no report is
        invented; REQUIRED set by the user is kept);
      * Kronos: SCALPING / HEDGING OBSERVE -> ASSIST (REQUIRED kept);
      * FOREX_MT5 baskets: execution AUTO_SH (plans go to the existing SH path).
    ASSIST may only HOLD an entry on a fresh contrary forecast - it never opens a position. Not changed: the account execution mode,
    STOP, the user's risk limits, stakes, leverage, SL; CRYPTO / OTC stay manual. A later user change is never overwritten (runs once)."""
    st = state_142()
    if st.get("models_assist_done"):
        return st
    done, errors = [], []
    ts = getattr(rt, "tsfm", None)
    if ts is not None:
        try:
            s = ts.settings.get()
            for mid, mc in s.models.items():
                for path, u in mc.use.items():
                    if u.use == "OBSERVE":
                        tf = u.timeframe if u.timeframe in mc.timeframes else (mc.timeframes[0] if mc.timeframes else u.timeframe)
                        r = ts.set_use(mid, path, "ASSIST", timeframe=tf, confirm=True)
                        (done if r.get("ok") else errors).append(f"tsfm:{mid}:{path}:{tf}:" + ("ASSIST" if r.get("ok") else str(r.get("reason"))[:120]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"tsfm: {type(exc).__name__}: {exc}"[:200])
    kr = getattr(rt, "kronos", None)
    if kr is not None:
        try:
            for strat, u in kr.settings.get().strategy_use.items():
                if u.use == "OBSERVE":
                    r = kr.set_strategy_use(strat, "ASSIST", timeframe=u.timeframe, confirm=True)
                    (done if r.get("ok") else errors).append(f"kronos:{strat}:" + ("ASSIST" if r.get("ok") else str(r.get("reason"))[:120]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"kronos: {type(exc).__name__}: {exc}"[:200])
    bs = getattr(rt, "baskets", None)
    if bs is not None:
        try:
            bs.update_settings({"profiles": {"FOREX_MT5": {"execution": "AUTO_SH"}}})
            done.append("baskets:FOREX_MT5:AUTO_SH")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"baskets: {type(exc).__name__}: {exc}"[:200])
    st.update(version=V142, models_assist_done=True, at=_now(), activation_policy="DIRECT_USER_REQUEST", applied=done, errors=errors,
              not_changed=["account execution mode", "STOP", "risk limits / stakes / leverage / SL", "CRYPTO / OTC (manual)"])
    p = _st142_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    try:
        rt.log.info("UPGRADE", "1_42_ASSIST", f"1.42: modele ASSIST + zlecenia koszyków FX przez ścieżkę SH ({len(done)} zmian, {len(errors)} błędów)")
    except Exception:  # noqa: BLE001
        pass
    return st
