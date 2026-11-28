"""Smoke of the extind area (`models check --smoke --area extind`): the indicator-context model (features.FEATURE_SCHEMA, since 1.46 arch
SCALP_INDICATOR_CONTEXT_V2: training gets the live decision inputs ref_close_bid / range ATR frozen at arming; V1 artefacts ABSTAIN), the SAR
context with its grid calibration, the knowledge rules IND-K01..K12 and the bot side of the two native MQL5 sources (IQ Gold Gann,
IQ Star Lines: pmw-extind-1 envelope -> ingest -> approved mapping -> point-in-time archive -> composer).

Every check runs on SYNTHETIC_TEST data of the FakeMT5 terminal (ctx.fake()) through a real MarketBridge session (verified server
offset), in the temporary data folder of the area process. The native indicators themselves are never run here (MT5 terminal on
Windows + MQL5 Market licence) - their rows stay NIEZWERYFIKOWANY even when the bot-side ingest passes.
"""
from __future__ import annotations

import atexit

from . import check, fail, ok, unverified

_CORE: dict = {}
INST = "XAUUSD"


def _core(ctx) -> dict:
    """Bot objects shared by the area: config, migrated database, FakeMT5 + MT5Worker + MarketBridge (closed bars, verified offset)."""
    if "bridge" in _CORE:
        return _CORE
    import time

    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import AppLog, EventBus
    from ...extind.service import ExtIndService
    from ...mt5.bridge import MarketBridge
    from ...mt5.worker import MT5Worker
    fake = ctx.fake()
    cfg = ConfigStore()
    db = Database()
    db.migrate()
    bus = EventBus()
    log = AppLog(db, bus)
    worker = MT5Worker(lambda: fake)
    worker.start()
    atexit.register(worker.stop)
    bridge = MarketBridge(cfg, worker, db, bus, log)
    bridge.connect()
    end = time.monotonic() + 40
    while time.monotonic() < end:
        bridge.poll(time.monotonic())
        if bridge.clock.verified and len(bridge.bars("M15", 50, include_forming=False)) >= 50:
            break
        time.sleep(0.3)
    _CORE.update(cfg=cfg, db=db, bus=bus, log=log, fake=fake, worker=worker, bridge=bridge, ext=ExtIndService(cfg, db, bridge, bus, log))
    return _CORE


def _closed(bridge, tf: str, n: int) -> list[dict]:
    return [b for b in bridge.bars(tf, n, include_forming=False) if b.get("open_utc")]


# ---------------------------------------------------------------------------------------------------------------- indicator context
def _ic_data(ctx) -> dict:
    """Generated cycle table on the FakeMT5 history (the shape trainer.build_dataset produces from the replay): decision at the close
    of an M5 bar, price = that close, atr_m5 = trainer.ind_atr of the 40 closed M5 (the fallback of trainer.decision_inputs for a replay
    record without range_atr_m5 - a synthetic fixture, the real dataset takes the range ATR frozen at arming), BASE = random setup
    features, y = 1 with a logistic signal on er10 (SYNTHETIC_TEST, the fixture of tests/test_ind_context.py)."""
    if "ic_data" in _CORE:
        return _CORE["ic_data"]
    import math
    from datetime import timedelta

    import numpy as np

    from ...extind import trainer as T
    from ...scalp.strategy import SETUP_FEATURES
    from ...timeutil import iso, parse_iso
    m5, m15 = ctx.bars("M5", 1500), ctx.bars("M15", 600)
    rng = np.random.default_rng(5)
    rows = []
    for i in range(420, len(m5) - 4, 6):
        t = parse_iso(m5[i]["open_utc"]) + timedelta(minutes=5)
        base = {f: float(rng.normal()) for f in SETUP_FEATURES}
        y = int(rng.random() < 1 / (1 + math.exp(-1.5 * base["er10"])))
        rows.append({"side": "BUY" if len(rows) % 2 else "SELL", "decision_time": iso(t), "exit_time": iso(t + timedelta(minutes=20)),
                     "price": m5[i]["c"], "atr_m5": T.ind_atr(m5[i - 39:i + 1]), "base": base, "y": y, "net_r": 1.0 if y else -1.0,
                     "ext": {"IQ_GOLD_GANN": None, "IQ_STAR_LINES": None}})
    data = {"instrument": INST, "rows": rows, "bars": {"M5": m5, "M15": m15}, "symbol": ctx.fake().symbol, "dataset_id": "SMOKE_FAKEMT5",
            "data_kind": "SYNTHETIC_TEST", "profile_id": "smoke"}
    _CORE["ic_data"] = (data, T.split(rows))
    return _CORE["ic_data"]


def _indicator_context(ctx) -> dict:
    import hashlib
    import json
    import time
    from datetime import UTC, datetime, timedelta

    import numpy as np

    from ...extind import features as F
    from ...extind import trainer as T
    from ...scalp.service import ScalpService
    out: dict = {}
    ctx.step = "train"
    data, sp = _ic_data(ctx)
    t0 = time.monotonic()
    r = T.run_variant(data, ("BASE", "SAR"), sp)
    if r.get("status") != "EVALUATED":
        out["train"] = fail(f"trainer.run_variant(BASE+SAR) -> {r.get('status')} {r.get('sizes') or r.get('coverage')} (extind/trainer.py:226)")
        return out
    h = r["holdout"]
    out["train"] = ok(f"trainer.split + run_variant(BASE+SAR) na {len(data['rows'])} cyklach SYNTHETIC_TEST ze świec FakeMT5 (najmniejsze wywołanie: bez "
                      f"build_dataset – replay scalp na syntetyce daje 0 cykli, por. scalp:C_policy) -> EVALUATED, wybór {r['model_kind']} na TUNE, Platt {tuple(round(x, 3) for x in r['platt'])}, "
                      f"próg {r['threshold']:.2f}, holdout n={h['n']} log loss {h['log_loss']:.3f} vs baseline {h['baseline_log_loss']:.3f} "
                      f"(technicznie, nie jakość), {time.monotonic() - t0:.1f} s")
    ctx.step = "artifact"
    rid = "SMOKE_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_FIXTURE"
    rd = T.root(INST) / "fixture_runs" / rid                       # synthetic runs land in fixture_runs, as train() does (trainer.py:291-292)
    rd.mkdir(parents=True, exist_ok=True)
    T._save_artifact(rd, INST, r, data, {"role": "fixture_only"})
    man = json.loads((rd / "model_BASE+SAR.json").read_text(encoding="utf-8"))
    m = T.load_artifact(rd, "BASE+SAR")
    X, _ = T.matrix(data, r["spec"])
    diff = float(np.max(np.abs(m.predict_raw(X[r["_hold"]]) - r["_ph"])))
    reg_p = T.root(INST) / "registry.json"
    reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"schema": "pmw-indicator-context-registry-1", "active": None, "runs": {}}
    reg["runs"][rid] = {"run_dir": str(rd), "status": "EVALUATED", "role": "fixture_only", "data_kind": "SYNTHETIC_TEST",
                        "artifacts": [p.name for p in rd.glob("model_*.json")]}
    T._write_registry(reg_p, reg)
    try:
        T.activate(INST, rid, "BASE+SAR")
        gate = "AKTYWOWANO artefakt fixture (bramka nie zadziałała)"
    except ValueError as exc:
        gate = f"odmowa zgodnie z bramką: {exc}"
    sha_ok = hashlib.sha256((rd / "model_BASE+SAR.pkl").read_bytes()).hexdigest() == man["pkl_sha256"]
    out["artifact"] = check(man["parity"]["status"] == "OK" and diff <= 1e-9 and sha_ok and gate.startswith("odmowa"),
                            f"_save_artifact -> model_BASE+SAR.pkl/.json (fixture_runs, role fixture_only), parity trenera {man['parity']['max_abs_diff']:.1e} "
                            f"({man['parity']['rows']} wierszy), load_artifact (sha256 OK) -> predict_raw holdoutu vs pamięć: różnica {diff:.1e}; "
                            f"trainer.activate: {gate}",
                            f"parity {man['parity']}, różnica po odczycie {diff:.3e}, sha256 {sha_ok}, activate: {gate} (extind/trainer.py:338-410)")
    ctx.step = "predict"
    c = _core(ctx)
    br = c["bridge"]
    bars = {tf: _closed(br, tf, 400) for tf in ("M5", "M15")}
    sc = ScalpService(c["cfg"], br, c["db"], c["bus"], c["log"])
    sc.extind = c["ext"]
    sc._bars = bars                                                  # what ScalpService.tick stores for the plan evaluation
    tdec = datetime.fromisoformat(bars["M5"][-1]["open_utc"]) + timedelta(minutes=5)
    atr_dec = T.ind_atr(bars["M5"][-40:])
    plan = {"decision_ts": tdec.timestamp(), "decision_time": tdec.isoformat(), "direction": "BUY", "ref_close_bid": bars["M5"][-1]["c"],
            "range": {"atr_m5": atr_dec}, "features": data["rows"][0]["base"], "setup_id": "SMOKE-IC-1"}
    live = sc.indicator_context(plan)                                # real live method: no active model (fixture refused) -> NO_MODEL
    snap = {"decision_time": tdec, "side": "BUY", "price": plan["ref_close_bid"], "base": plan["features"], "bars": bars,
            "ext": {a: c["ext"].as_of(a, INST, tdec) for a in ("IQ_GOLD_GANN", "IQ_STAR_LINES")}}
    p_dec = m.predict(dict(snap, atr_m5=atr_dec), INST)               # ContextModel.predict as ScalpService.indicator_context calls it, ATR at the decision
    atr_frozen = T.ind_atr(bars["M5"][-52:-12])
    p_frz = m.predict(dict(snap, atr_m5=atr_frozen), INST)            # ATR frozen 12 M5 earlier (range armed) - the live and V2 training input
    btc = m.predict(dict(snap, atr_m5=atr_dec), "BTC")
    warm = m.predict(dict(snap, atr_m5=atr_dec, bars={"M5": bars["M5"][:3], "M15": []}), INST)
    okp = (live.get("status") == "NO_MODEL" and p_dec.get("status") == "READY_INFERENCE" and 0.0 < p_dec.get("p_tp1_first", -1) < 1.0
           and btc.get("status") == "ABSTAIN" and warm.get("status") == "ABSTAIN")
    pd_, pf_ = p_dec.get("p_tp1_first", float("nan")), p_frz.get("p_tp1_first", float("nan"))
    out["predict"] = check(okp, f"ScalpService.indicator_context -> {live.get('status')} (fixture nieaktywowalny); ContextModel.predict (wywołanie "
                                f"ScalpService.indicator_context) -> {p_dec.get('status')} p={pd_:.3f} SHADOW; BTC/3 świece -> ABSTAIN. Informacyjnie: "
                                f"wrażliwość na atr_m5 (od {F.FEATURE_SCHEMA} trening i live biorą ATR zakresu z uzbrojenia, trainer.decision_inputs): ATR "
                                f"w decyzji {atr_dec:.2f} vs z uzbrojenia {atr_frozen:.2f} -> p {pd_:.3f} vs {pf_:.3f}",
                           f"live {live.get('status')}, predict {p_dec.get('status')} {p_dec.get('reason')}, BTC {btc.get('status')}, warmup "
                           f"{warm.get('status')} (scalp/service.py:400-416, extind/trainer.py:362-374)")
    ctx.step = "contract"
    need = {"status", "task_id", "p_tp1_first", "threshold", "groups", "role", "mode"}
    miss = sorted(need - set(p_dec))
    out["contract"] = check(not miss and p_dec.get("task_id") == F.TASK_ID and p_dec.get("mode") == "SHADOW" and p_dec.get("role") == "fixture_only",
                            f"własny słownik (nie PMW-PRED-2 – brak adaptera Quant, wynik tylko w planie scalp_shadow): klucze {sorted(need)}, task_id "
                            f"{F.TASK_ID}, mode SHADOW, role fixture_only, p w (0,1)",
                            f"brak kluczy {miss} albo task/mode/role niezgodne: {p_dec}"[:400])
    return out


# ---------------------------------------------------------------------------------------------------------------- SAR context
def _sar_context(ctx) -> dict:
    import time
    from types import SimpleNamespace

    from ...engine.service import EngineService
    from ...extind import trainer as T
    from ...scalp import indicators as ind
    from ...timeutil import iso, utcnow
    out: dict = {}
    ctx.step = "train"
    data, sp = _ic_data(ctx)
    t0 = time.monotonic()
    cal = T.calibrate_sar(data, sp)
    grid = [(x["step"], x["max"]) for x in cal.get("trials") or []]
    sel = cal.get("selected") or {}
    out["train"] = check(cal.get("status") == "OK" and grid == list(T.SAR_GRID) and (sel.get("step"), sel.get("max")) in T.SAR_GRID
                         and cal.get("live_default_unchanged") == {"step": 0.02, "max": 0.2},
                         f"trainer.calibrate_sar (siatka {len(grid)} par, wybór na TUNE, nigdy holdout) -> wybrano step {sel.get('step')} max {sel.get('max')}; "
                         f"parametry na żywo bez zmian 0.02/0.2; {time.monotonic() - t0:.1f} s",
                         f"calibrate_sar -> {cal.get('status')}, próby {grid}, wybór {sel} (extind/trainer.py:267-281)")
    ctx.step = "predict"
    c = _core(ctx)
    stub = SimpleNamespace(bridge=c["bridge"], extind=c["ext"], cfg_store=c["cfg"])
    ic = EngineService._indicator_context(stub, {"as_of": iso(utcnow())})       # the snapshot builder of the agent context (engine/service.py:615)
    c["engine_ctx"] = ic
    sar = (ic or {}).get("sar") or {}
    good = {"PRESSURE_UP", "PRESSURE_DOWN", "NO_DIRECTIONAL_EVIDENCE"}
    okm = all((sar.get(tf) or {}).get("status") == "OK" and sar[tf].get("interpretation") in good and sar[tf].get("params") == {"step": 0.02, "max": 0.2}
              for tf in ("M5", "M15"))
    hh = [100 + i * 0.1 for i in range(60)]
    ref = ind.sar_diagnostics(hh, [x - 0.5 for x in hh], [x - 0.2 for x in hh], 0.5)
    out["predict"] = check(okm and ref.get("interpretation") == "PRESSURE_UP",
                           "EngineService._indicator_context na 400 zamkniętych świecach MarketBridge (FakeMT5): " +
                           ", ".join(f"{tf} {sar[tf]['interpretation']} SAR {sar[tf]['sar']:.2f}, {sar[tf]['bars_since_flip']} świec od flipu"
                                     for tf in ("M5", "M15") if (sar.get(tf) or {}).get("status") == "OK") +
                           "; wzorzec rosnący -> PRESSURE_UP",
                           f"sar {sar}, wzorzec {ref.get('interpretation')} (engine/service.py:615-641, scalp/indicators.py:164)"[:400])
    ctx.step = "contract"
    need = {"status", "profile", "params", "sar", "raw_trend", "interpretation", "bars_since_flip", "flips_in_window", "distance_atr", "whipsaw_risk"}
    miss = {tf: sorted(need - set(sar.get(tf) or {})) for tf in ("M5", "M15")}
    prof = {(sar.get(tf) or {}).get("profile") for tf in ("M5", "M15")}
    out["contract"] = check(not any(miss.values()) and prof == {ind.SAR_PROFILE},
                            f"klucze diagnostyki SAR {sorted(need)} obecne, profil {ind.SAR_PROFILE} (M5, M15)",
                            f"brak kluczy {miss}, profil {prof}")
    return out


# ---------------------------------------------------------------------------------------------------------------- knowledge
def _knowledge(ctx) -> dict:
    from types import SimpleNamespace

    from ...engine.service import EngineService
    from ...extind import knowledge as K
    from ...timeutil import iso, utcnow
    out: dict = {}
    ctx.step = "predict"
    c = _core(ctx)
    ic = c.get("engine_ctx") or EngineService._indicator_context(SimpleNamespace(bridge=c["bridge"], extind=c["ext"], cfg_store=c["cfg"]),
                                                                 {"as_of": iso(utcnow())})
    ids = {rid for rid, _, _ in K.RULES}
    rules = list(ic.get("applied_rules") or [])
    expl = str(ic.get("explanation_pl") or "")
    base = {"IND-K07", "IND-K09", "IND-K10", "IND-K11", "IND-K12", "IND-K01", "IND-K06"}   # no IQ source on the chart, PAL02M not identified
    src = dict(ic.get("sources") or {})
    src["IQ_GOLD_GANN"] = dict(src.get("IQ_GOLD_GANN") or {}, source_status="RECEIVING", levels=[{"kind": "LEVEL", "price": 1.0}])
    src["IQ_STAR_LINES"] = dict(src.get("IQ_STAR_LINES") or {}, windows=[{"kind": "ASPECT"}])
    more = set(K.applied_rules(dict(ic, sources=src)))
    okr = (set(rules) <= ids and base <= set(rules) and {"IND-K02", "IND-K03", "IND-K04", "IND-K05"} <= more and "SAR M5" in expl
           and "PAL02M" in expl)
    out["predict"] = check(okr, f"EngineService._indicator_context -> applied_rules {rules}; z poziomami IQ i oknem Star dochodzą "
                                f"{sorted(more - set(rules))}; explain_pl (PL, bez LLM): {expl[:90]}",
                           f"reguły {rules} (oczekiwane ⊇ {sorted(base)}), z IQ {sorted(more)}, opis: {expl[:150]} (extind/knowledge.py:29-64)")
    ctx.step = "contract"
    ps = K.prompt_section()
    miss = sorted(i for i in ids if i not in ps)
    out["contract"] = check(len(ids) == 12 and not miss and K.KNOWLEDGE_VERSION in ps and ic.get("knowledge_version") == K.KNOWLEDGE_VERSION,
                            f"{K.KNOWLEDGE_VERSION}: 12 reguł IND-K01..K12 w sekcji promptu agenta, wersja wiedzy w kontekście snapshotu",
                            f"brak w prompcie {miss}, wersja kontekstu {ic.get('knowledge_version')}")
    return out


# ---------------------------------------------------------------------------------------------------------------- native IQ sources
_NATIVE = {"IQ_GOLD_GANN": ("134935", "gann"), "IQ_STAR_LINES": ("145140", "star")}


def _exporter_fields(ctx) -> tuple[set, bool]:
    """Body field names written by the repository's exporter (mql5/PMW_ExtIndicatorExporter.mq5) - the envelope fixture of the repo."""
    import re
    src = (ctx.root / "mql5" / "PMW_ExtIndicatorExporter.mq5").read_text(encoding="utf-8", errors="replace")
    body = src[src.find('string body = "'):src.find("string outer")]
    return set(re.findall(r'\\"([a-z_]+)\\":', body)), '\\"time_basis\\":\\"BROKER_SERVER\\"' in body


def _native(adapter: str):
    pid, prefix = _NATIVE[adapter]

    def run(ctx) -> dict:
        import json
        from datetime import timedelta

        from ...extind import contract as XC
        from ...extind import features as F
        from ...extind import mapping as M
        from ...timeutil import utcnow
        out = {"env": unverified(f"natywny wskaźnik MQL5 Market (produkt {pid}) działa tylko w terminalu MT5 (Windows) z licencją; eksporter "
                                 "mql5/PMW_ExtIndicatorExporter.mq5 nieuruchomiony – sprawdzono wyłącznie stronę bota (koperta pmw-extind-1)")}
        ctx.step = "contract"
        c = _core(ctx)
        br, ext, off = c["bridge"], c["ext"], c["bridge"].clock.offset
        fields, broker_basis = _exporter_fields(ctx)
        miss = sorted(set(XC.REQUIRED) - fields)
        man = M.manifest(adapter)
        now = utcnow()
        srv = int(now.timestamp()) + int(off or 0)                    # exporter: TimeCurrent() = broker server wall clock (BROKER_SERVER)
        px = float(_closed(br, "M5", 1)[-1]["c"])
        objs = [{"name": f"{prefix.upper()}_lv1", "type": "HLINE", "prices": [round(px + 5.0, 2)], "times": [], "text": "", "color": 255},
                {"name": f"{prefix.upper()}_lv2", "type": "HLINE", "prices": [round(px - 5.0, 2)], "times": [], "text": "", "color": 255},
                {"name": "OTHER_obj", "type": "TEXT", "prices": [], "times": [], "text": "x", "color": 0}]
        rules = [{"prefix": f"{prefix.upper()}_lv", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"}]
        if adapter == "IQ_STAR_LINES":
            objs.append({"name": "STAR_win1", "type": "RECTANGLE", "prices": [px - 1, px + 1], "times": [srv + 1800, srv + 5400], "text": "", "color": 1})
            rules.append({"prefix": "STAR_win", "type": "RECTANGLE", "kind": "TIME_WINDOW", "role": "ASPECT"})
        body = {"schema_version": XC.SCHEMA, "producer_version": "PMW_ExtIndicatorExporter/1.00", "adapter_id": adapter, "product": {"version": "1.0"},
                "terminal_fingerprint": "Synthetic-Demo:5550001", "chart_id": "1001", "symbol": c["cfg"].get().mt5.symbol, "tf": "PERIOD_M5",
                "time_basis": "BROKER_SERVER", "captured_at_server": srv, "captured_at_gmt": int(now.timestamp()), "generation": 1, "sequence": 1,
                "complete": True, "objects": objs}
        extra = sorted(set(body) - fields)
        mp = M.save_mapping(adapter, {"product_version": "1.0", "approved": True, "verified_examples": [{"name": objs[0]["name"], "chart": objs[0]["prices"][0]}],
                                      "rules": rules})
        map_file = M.ext_root() / "mappings" / f"{adapter}.json"
        in_tmp = ctx.data_dir in map_file.parents
        raw = XC.wrap(body)
        n1 = ext.ingest_bytes(raw, f"{adapter}_1.json", now)
        n_dup = ext.ingest_bytes(raw, f"{adapter}_dup.json", now)
        bad = json.loads(raw)
        bad["body"] = bad["body"].replace('"sequence":1', '"sequence":2')
        n_bad = ext.ingest_bytes(json.dumps(bad).encode(), f"{adapter}_bad.json", now)
        bad_reason = ext.errors[-1]["reason"] if ext.errors else None
        snap = ext.as_of(adapter, INST, now + timedelta(seconds=1))
        before = ext.as_of(adapter, INST, now - timedelta(seconds=5))
        st = ext.status(INST, now + timedelta(seconds=1))["adapters"][adapter]
        lv = sorted(x["price"] for x in (snap or {}).get("levels") or [])
        feat = F.build_indicator_context_features({"decision_time": now + timedelta(seconds=1), "side": "BUY", "price": px, "atr_m5": 2.0, "base": {},
                                                   "bars": {}, "ext": {adapter: snap}}, F.default_spec((adapter,)))
        fv = {k: round(v, 3) for k, v in feat["features"].items()}
        win = ""
        okw = True
        if adapter == "IQ_STAR_LINES":
            w = ((snap or {}).get("windows") or [{}])[0]
            okw = w.get("scheduled_start_utc") == srv + 1800 - int(off or 0) and abs(fv.get("star_min_to_start", 0) - 30.0) < 0.1
            win = f"; okno Star za {fv.get('star_min_to_start'):.1f} min (serwer − offset)"
        good = (not miss and broker_basis and man.get("identity_status") == "IDENTIFIED" and mp["approved"] and in_tmp and n1 == 1 and n_dup == 0
                and n_bad == 0 and bad_reason == "CHECKSUM_MISMATCH" and snap is not None and before is None and snap.get("time_status") == "OK"
                and lv == sorted(o["prices"][0] for o in objs[:2]) and st["runtime_status"] == "READY_RUNTIME" and st["dataset_status"] == "BLOCKED_NO_ARCHIVE"
                and feat["groups"].get(adapter) == "OK" and okw)
        out["contract"] = check(good,
                                f"koperta w formacie eksportera repo ({len(fields)} pól .mq5 ⊇ REQUIRED, BROKER_SERVER{', dodatkowe ' + str(extra) if extra else ''})"
                                f" -> manifest {man.get('identity_status')}, mapping zatwierdzony (tmp) -> ingest 1, duplikat 0, zły checksum 0; as_of poziomy "
                                f"{lv} time_status OK (offset {off} s), przed odbiorem brak; status {st['source_status']}/{st['mapping_status']}/"
                                f"{st['runtime_status']}/{st['dataset_status']}; composer OK{win}",
                                f"brak pól eksportera {miss}, BROKER_SERVER {broker_basis}, manifest {man.get('identity_status')}, mapping w tmp {in_tmp}, "
                                f"ingest {n1}/{n_dup}/{n_bad} ({bad_reason}), as_of {lv} {(snap or {}).get('time_status')}, przed {before is not None}, status "
                                f"{st['runtime_status']}, grupy {feat['groups']}, okno {okw} (extind/service.py:97-160, extind/mapping.py)")
        out["predict"] = unverified(f"odczyt prawdziwego {adapter} niemożliwy bez terminala MT5 + licencji – poziomy pochodzą z koperty syntetycznej; "
                                    "zgodność liczb z wykresem (mapping) sprawdza tylko użytkownik na Windows")
        return out

    run.__name__ = f"_native_{adapter.lower()}"
    return run


SMOKES = {
    "extind:indicator_context": _indicator_context,
    "extind:sar_context": _sar_context,
    "extind:knowledge": _knowledge,
    "extind:IQ_GOLD_GANN": _native("IQ_GOLD_GANN"),
    "extind:IQ_STAR_LINES": _native("IQ_STAR_LINES"),
}
