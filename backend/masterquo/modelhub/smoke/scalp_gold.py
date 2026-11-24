"""Smoke of the scalp_gold area (`models check --smoke --area scalp_gold`): scalp A (direction 1/3/5 min), scalp B (setup quality),
scalp C (hedge vs REDUCE policy evaluation), the gold_candles forecaster (5/15/30 min) and Double Retest v2 - all trained and served
by the separate environment .venv_candles (gold_candles_runtime); the bot venv is only the client (ForecastService worker protocol).

Chain (once per area process, shared by the five checks):
  1. `masterquo training export --synthetic` (FakeMT5, 1 month M1/M5/M30) into the temporary data folder;
  2. in .venv_candles: gold_candles_runtime.plan_train.main (full trainer, 10 trees) and this module's `_train_scalp` - the smallest
     real call of the scalp trainer functions (scalp_train.load / make_plan / SF.build / SF.labels / fit_lr / fit_calibrator /
     lr_to_json / train_setup_model / task_bc + registry write); scalp_train.main() itself (walk-forward HGB/MLP/quantiles) is too slow;
  3. activation through the real CLIs: first WITHOUT the test override (refusal = the honesty gate), then with
     MQ_FORECAST_TEST_ALLOW_SYNTHETIC=1 set ONLY in os.environ of this temporary area process (inherited by its child processes);
  4. bot side on a MarketBridge session of the FakeMT5 terminal: ForecastService.tick (spawns the .venv_candles worker) ->
     modelhub.adapters.forecast_predictions, ScalpService.forecasts / setup_quality -> quant.adapters.scalp_a, Double Retest state.
Without .venv_candles every step is NIEZWERYFIKOWANY (nothing is simulated in the bot venv).
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import check, fail, ok, unverified

VENV = ".venv_candles"
ALLOW = "MQ_FORECAST_TEST_ALLOW_SYNTHETIC"
INST = "XAUUSD"
SCALP_DAYS = 8                     # M1 days of the export used by the scalp trainer functions (60/20/20 cut at 00:00 UTC needs >= ~6)
_S: dict = {}


def _backend() -> Path:
    return Path(__file__).resolve().parents[3]


def _no_env(ctx, steps: tuple[str, ...]) -> dict | None:
    py = ctx.env_python(VENV)
    if py:
        return None
    why = ("brak środowiska .venv_candles (zmienna MQ_CANDLES_PYTHON albo <program>/.venv_candles) – trening i inferencja tego producenta "
           "działają tylko w procesie workera tego środowiska; nic nie jest symulowane w .venv bota")
    return {"env": unverified(why), **{k: unverified("niesprawdzone: brak .venv_candles") for k in steps}}


def _run(cmd: list[str], *, allow: bool, timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(_backend()), PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="1", MQ_INSTRUMENT=INST)
    if not allow:
        env.pop(ALLOW, None)
    return subprocess.run(cmd, cwd=str(_backend()), env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)


def _tail(p: subprocess.CompletedProcess, n: int = 2) -> str:
    return " | ".join(((p.stdout or "") + "\n" + (p.stderr or "")).strip().splitlines()[-n:])[:300]


# ---------------------------------------------------------------------------------------------------------------- shared chain
def _train(ctx) -> dict:
    """Export + both trainings (parallel processes) + activation gates. Errors are stored per stage, never raised."""
    if "train" in _S:
        return _S["train"]
    res: dict = {"py": ctx.env_python(VENV)}
    _S["train"] = res
    py = res["py"]
    ds = ctx.data_dir / "smoke_scalp_gold" / "ds"
    t0 = time.monotonic()
    p = _run([sys.executable, "-m", "masterquo", "training", "export", "--instrument", INST, "--symbol", ctx.fake().symbol, "--months", "1",
              "--out", str(ds), "--tfs", "M1,M5,M30", "--synthetic"], allow=False, timeout=180)
    if p.returncode != 0 or not (ds / "source_metadata.json").exists():
        res["error"] = f"eksport syntetyczny (masterquo training export --synthetic) kod {p.returncode}: {_tail(p)}"
        return res
    res["export_s"] = round(time.monotonic() - t0, 1)
    out_json = ctx.data_dir / "smoke_scalp_gold" / "scalp_train.json"
    env = dict(os.environ, PYTHONPATH=str(_backend()), PYTHONIOENCODING="utf-8", OMP_NUM_THREADS="1", MQ_INSTRUMENT=INST)
    env.pop(ALLOW, None)
    t1 = time.monotonic()
    procs = {"scalp": subprocess.Popen([py, "-m", "masterquo.modelhub.smoke.scalp_gold", "_train_scalp", str(ds), str(out_json)], cwd=str(_backend()),
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"),
             "gold": subprocess.Popen([py, "-m", "gold_candles_runtime.plan_train", "--data-dir", str(ds), "--data-kind", "SYNTHETIC_TEST", "--trees", "10",
                                       "--no-activate"], cwd=str(_backend()), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8")}
    for k, pr in procs.items():
        try:
            so, se = pr.communicate(timeout=150)
        except subprocess.TimeoutExpired:
            pr.kill()
            so, se = pr.communicate()
            res[f"{k}_error"] = "przekroczony limit 150 s"
            continue
        if pr.returncode != 0:
            res[f"{k}_error"] = f"kod {pr.returncode}: " + " | ".join((se or so or "").strip().splitlines()[-2:])[:300]
    res["train_s"] = round(time.monotonic() - t1, 1)
    if "scalp_error" not in res:
        res["scalp"] = json.loads(out_json.read_text(encoding="utf-8"))
    if "gold_error" not in res:
        reg = json.loads((ctx.data_dir / "forecast" / "registry.json").read_text(encoding="utf-8"))
        rid = max(r for r, e in reg["runs"].items() if e.get("data_dir") == str(ds.resolve()))
        res["gold"] = dict(reg["runs"][rid], run_id=rid)
    # activation: the honesty gate first (no override), then the test override in THIS temporary process only
    clis = {"scalp": ("gold_candles_runtime.scalp_registry", (res.get("scalp") or {}).get("run_id")),
            "gold": ("gold_candles_runtime.registry_cli", (res.get("gold") or {}).get("run_id"))}
    for k, (mod, rid) in clis.items():
        if not rid:
            continue
        g = _run([py, "-m", mod, "activate", rid], allow=False, timeout=60)
        res[f"{k}_gate"] = (g.returncode, _tail(g, 1))
    os.environ[ALLOW] = "1"
    atexit.register(os.environ.pop, ALLOW, None)
    for k, (mod, rid) in clis.items():
        if not rid:
            continue
        a = _run([py, "-m", mod, "activate", rid], allow=True, timeout=60)
        res[f"{k}_activate"] = (a.returncode, _tail(a, 1))
    return res


def _live(ctx) -> dict:
    """Bot side: MarketBridge on FakeMT5 -> ForecastService.tick (spawns the .venv_candles worker) -> adapters; ScalpService A/B."""
    if "live" in _S:
        return _S["live"]
    lv: dict = {}
    _S["live"] = lv
    from types import SimpleNamespace

    from ...config import ConfigStore
    from ...db.database import Database
    from ...events import AppLog, EventBus
    from ...forecast.service import ForecastService, candle_python
    from ...mt5.bridge import MarketBridge
    from ...mt5.worker import MT5Worker
    from ...scalp.service import ScalpService
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
        if bridge.clock.offset is not None and len(bridge.bars("M30", 100, include_forming=False)) >= 100 \
                and len(bridge.bars("M1", 400, include_forming=False)) >= 300:
            break
        time.sleep(0.3)
    fs = ForecastService(cfg, bridge, db, bus, log)
    atexit.register(fs.stop)
    lv["candle_python"] = candle_python(cfg.get())
    t0 = time.monotonic()
    fs.tick()                                                         # spawns the worker, analyze on the last closed M5
    lv["tick_s"] = round(time.monotonic() - t0, 1)
    lv["fs"] = fs
    lv["state"] = fs.public()
    lv["shadow_rows"] = db.query("SELECT horizon_minutes, outcome_status, horizon_status, session_check FROM forecast_shadow WHERE instrument=?", (INST,))
    sc = ScalpService(cfg, bridge, db, bus, log, forecast=fs)
    lv["sc"] = sc
    lv["rt"] = SimpleNamespace(forecast=fs, scalp=sc)
    lv["db"] = db
    return lv


def _common(ctx, steps: tuple[str, ...]) -> tuple[dict | None, dict | None]:
    """-> (steps to return immediately, train result). Environment missing or the shared chain broken -> immediate answer."""
    miss = _no_env(ctx, steps)
    if miss is not None:
        return miss, None
    ctx.step = steps[0]
    tr = _train(ctx)
    if tr.get("error"):
        return {"env": ok(f"{VENV}: {tr['py']}"), steps[0]: fail(tr["error"])}, None
    return None, tr


# ---------------------------------------------------------------------------------------------------------------- scalp A
def _scalp_a(ctx) -> dict:
    early, tr = _common(ctx, ("train", "artifact", "predict", "contract"))
    if early:
        return early
    out = {"env": ok(f"{VENV}: {tr['py']} (MQ_CANDLES_PYTHON / <program>/{VENV})")}
    if tr.get("scalp_error"):
        out["train"] = fail(f"_train_scalp w {VENV}: {tr['scalp_error']}")
        return out
    s = tr["scalp"]
    a = s["A"]
    hz = a["horizons"]
    out["train"] = check(a["overall"] != "INSUFFICIENT_DATA" and all(h.get("selected") == "LR" for h in hz.values()),
                         f"najmniejsze prawdziwe wywołanie trenera (pełny scalp_train.main za wolny): load {s['rows_m1']} M1 ({SCALP_DAYS} dni eksportu "
                         f"syntetycznego), make_plan(small), SF.build/labels, fit_lr + fit_calibrator per horyzont -> " +
                         ", ".join(f"h{k}: dev {v['rows']['dev']}/cal {v['rows']['cal']}/hold {v['rows']['hold']} {v['status']}" for k, v in hz.items()) +
                         f"; {s['seconds']} s (+ eksport {tr['export_s']} s)",
                         f"zadanie A: {a['overall']} {json.dumps(hz)[:300]}")
    ctx.step = "artifact"
    gate, act = tr.get("scalp_gate") or (None, ""), tr.get("scalp_activate") or (None, "")
    diff = max(v["roundtrip_max_abs_diff"] for v in hz.values())
    out["artifact"] = check(diff <= 1e-9 and gate[0] == 2 and "NOT_REAL_USER_DATA" in gate[1] and act[0] == 0,
                            f"lr_to_json + calib_to_json -> rejestr (sha256) -> ScalpModel (loader workera) vs pamięć trenera, 50 wierszy holdoutu: "
                            f"max |dP| {diff:.1e}; scalp_registry activate bez nadpisania: odmowa zgodnie z bramką (NOT_REAL_USER_DATA); aktywacja dopiero "
                            f"z {ALLOW}=1 ustawionym tylko w os.environ tymczasowego procesu obszaru (dziedziczą go CLI i worker)",
                            f"różnica {diff:.3e}, bramka {gate}, aktywacja {act} (gold_candles_runtime/scalp_infer.py:37-48, scalp_registry.py:58-71)")
    ctx.step = "predict"
    lv = _live(ctx)
    from ...quant import adapters as QA
    ans = lv["sc"].forecasts()
    recs = QA.scalp_a(lv["rt"], INST)
    h = ans.get("horizons") or {}
    sums = [abs(v["p_down"] + v["p_flat"] + v["p_up"] - 1) for v in h.values()]
    okp = (ans.get("status") == "SHADOW" and ans.get("execution_permission") is False and sorted(h) == ["1", "3", "5"] and max(sums or [1]) <= 2e-4
           and [r.get("state") for r in recs] == ["READY"] * 3)
    out["predict"] = check(okp, f"MarketBridge(FakeMT5) -> ScalpService.forecasts -> ForecastService worker {VENV} scalp_forecast -> {ans.get('status')}, "
                                f"exec {ans.get('execution_permission')}: " +
                                ", ".join(f"h{k} P(D/F/U) {v['p_down']:.3f}/{v['p_flat']:.3f}/{v['p_up']:.3f}" for k, v in h.items()) +
                                f"; quant.adapters.scalp_a -> {[r.get('state') for r in recs]} (etykieta UNCALIBRATED mimo kalibratora – quant/adapters.py:352)",
                           f"scalp_forecast {ans.get('status')} {ans.get('reason')}, quant {[(r.get('state'), r.get('unavailable_reason')) for r in recs]}"
                           " (scalp/service.py:483-497, quant/adapters.py:323-355)")
    ctx.step = "contract"
    out["contract"] = ctx.contract_step(recs)
    return out


# ---------------------------------------------------------------------------------------------------------------- scalp B
def _scalp_b(ctx) -> dict:
    early, tr = _common(ctx, ("train", "artifact", "predict", "contract"))
    if early:
        return early
    out = {"env": ok(f"{VENV}: {tr['py']}")}
    if tr.get("scalp_error"):
        out["train"] = fail(f"_train_scalp w {VENV}: {tr['scalp_error']}")
        return out
    b = tr["scalp"]["B"]
    out["train"] = check(b["status"] in ("FILTER_HELPS_IN_HOLDOUT", "FILTER_NOT_HELPING_IN_HOLDOUT") and b.get("spec_file"),
                         f"scalp_train.train_setup_model (walk-forward LR/HGB, Platt, próg na kalibracji, holdout raz) na wygenerowanych cyklach "
                         f"SYNTHETIC_TEST dev/cal/hold {'/'.join(str(v) for v in b['cycles'].values())} (task_bc na syntetyce: {b['replay']} -> "
                         f"{b['replay_status']}) -> "
                         f"{b['status']}, wybór {b['selected']}, próg {b['threshold']}, plik {b['spec_file']}",
                         f"train_setup_model -> {b['status']} {b.get('reason')} (gold_candles_runtime/scalp_train.py:540-630)")
    ctx.step = "artifact"
    out["artifact"] = check(b["roundtrip_max_abs_diff"] <= 1e-9,
                            f"{b['spec_file']} (sha256 w rejestrze) -> SetupModel (loader workera) vs ponowny _fit_bin({b['selected']}) + Platt z wpisu na "
                            f"{b['probe_rows']} cyklach holdoutu: max |dp| {b['roundtrip_max_abs_diff']:.1e}",
                            f"różnica {b['roundtrip_max_abs_diff']:.3e} (scalp_infer.SetupModel)")
    ctx.step = "predict"
    lv = _live(ctx)
    q = lv["sc"].setup_quality({"features": b["probe_features"]})
    dp = abs(float(q.get("p", -9)) - b["probe_p_file"])
    out["predict"] = check(q.get("status") == "SHADOW" and dp <= 1e-4 and q.get("execution_permission") is False,
                           f"ScalpService.setup_quality -> worker {VENV} setup_quality -> {q.get('status')} p={q.get('p')} (plik {b['probe_p_file']:.4f}, "
                           f"|dp| {dp:.1e} – zaokrąglenie 4 miejsc), próg {q.get('threshold')}, pass {q.get('pass')}, exec False",
                           f"setup_quality {q} (scalp/service.py:418-429, worker.py:151-174)"[:400])
    ctx.step = "contract"
    need = {"status", "p", "threshold", "pass", "model", "run_id", "execution_permission"}
    miss = sorted(need - set(q))
    out["contract"] = check(not miss and 0.0 < float(q["p"]) < 1.0 and q["pass"] == (q["threshold"] is not None and q["p"] >= q["threshold"]),
                            f"własny słownik (adapter Quant: brak – SETUP_EVENT w planie scalp_shadow): klucze {sorted(need)}, p w (0,1), pass = p ≥ próg",
                            f"brak kluczy {miss} albo p/pass niespójne: {q}"[:400])
    return out


# ---------------------------------------------------------------------------------------------------------------- gold candles
def _gold(ctx) -> dict:
    early, tr = _common(ctx, ("train", "artifact", "predict", "contract"))
    if early:
        return early
    out = {"env": ok(f"{VENV}: {tr['py']}")}
    if tr.get("gold_error"):
        out["train"] = fail(f"gold_candles_runtime.plan_train w {VENV}: {tr['gold_error']}")
        return out
    g = tr["gold"]
    out["train"] = check(sorted(g.get("horizons_trained") or []) == ["1", "3", "6"],
                         f"gold_candles_runtime.plan_train.main (pełny trener, --trees 10, --no-activate) na eksporcie syntetycznym 1 mies. -> "
                         f"{g['overall_status']} {g['horizon_status']} (REJECTED na syntetyce = poprawna ocena), {g.get('training_seconds')} s",
                         f"plan_train: horyzonty {g.get('horizons_trained')} {g.get('overall_status')}")
    ctx.step = "artifact"
    import hashlib
    rc = g.get("runtime_check") or {}
    par = rc.get("parity") or {}
    sha_ok = hashlib.sha256(Path(g["model_path"]).read_bytes()).hexdigest() == g["artifact_sha256"]
    gate, act = tr.get("gold_gate") or (None, ""), tr.get("gold_activate") or (None, "")
    out["artifact"] = check(rc.get("status") == "OK" and par.get("max_abs_prob_diff", 1) <= 1e-6 and sha_ok and gate[0] not in (0, None)
                            and "NOT_REAL_USER_DATA" in gate[1] and act[0] == 0,
                            f"forecast_model.json (sha256 OK) -> runtime_check trenera (loader bota, {rc.get('checked')} migawek holdoutu vs cechy batch): "
                            f"max |dp| {par.get('max_abs_prob_diff')}, obcy kontrakt odrzucony; registry_cli activate bez nadpisania: odmowa zgodnie z bramką; "
                            f"z {ALLOW}=1 (tylko os.environ tymczasowego procesu obszaru): aktywny. Uwaga: activate przyjmuje run {g['overall_status']} "
                            f"(common.py:158-173 nie sprawdza jakości)",
                            f"runtime_check {rc}, sha256 {sha_ok}, bramka {gate}, aktywacja {act}"[:400])
    ctx.step = "predict"
    lv = _live(ctx)
    from ...modelhub import adapters as MA
    st = lv["state"]
    recs = MA.forecast_predictions(lv["rt"], INST)
    fc = ((st.get("report") or {}).get("forecast") or {}).get("probabilities") or {}
    sess = sorted({str(v.get("session_check")) for v in fc.values()})
    rows = lv["shadow_rows"]
    okp = (st.get("status") == "SHADOW" and st.get("execution_permission") is False and len(fc) == 3 and [r.get("state") for r in recs] == ["READY"] * 3
           and len(rows) == 3 and {r["outcome_status"] for r in rows} == {"PENDING"})
    out["predict"] = check(okp, f"MarketBridge(FakeMT5) -> ForecastService.tick -> worker {VENV} analyze -> {st.get('status')}: " +
                                ", ".join(f"{k} min UP {v['probabilities']['UP']:.3f}" for k, v in fc.items()) +
                                f"; forecast_shadow {len(rows)}x PENDING; forecast_predictions {len(recs)}x READY. ZNANY PROBLEM (nie FAIL): adapter "
                                f"daje READY mimo horizon_status {'/'.join(sorted(set(g['horizon_status'].values())))} i nie filtruje BLOCKED_SESSION_BREAK "
                                f"(tu {'/'.join(sess)}) – modelhub/adapters.py:40-49",
                           f"status {st.get('status')} {st.get('reason')}, horyzonty {len(fc)}, adapter {[(r.get('state'), r.get('unavailable_reason')) for r in recs]}, "
                           f"forecast_shadow {rows} (forecast/service.py:139-229)"[:400])
    ctx.step = "contract"
    out["contract"] = ctx.contract_step(recs)
    return out


# ---------------------------------------------------------------------------------------------------------------- Double Retest v2
def _double_retest(ctx) -> dict:
    early, tr = _common(ctx, ("predict", "contract"))
    if early:
        return early
    out = {"env": ok(f"{VENV}: {tr['py']} (flagi świec liczy worker gold_candles.patterns)")}
    ctx.step = "predict"
    lv = _live(ctx)
    from ...forecast import double_retest as DR
    su = lv["state"].get("setup_v2") or {}
    states = {k: (v or {}).get("state") for k, v in (su.get("states") or {}).items()}
    okp = (lv["state"].get("status") in ("SHADOW", "NO_MODEL", "WARMUP") and su.get("FLAGS_STATE") != "UNAVAILABLE" and sorted(states) == ["BUY", "SELL"]
           and all(s in DR.STATE_PL for s in states.values()))
    out["predict"] = check(okp, f"ForecastService.tick (flags_tail={lv['state'].get('bars', {}).get('m5')} M5 z workera {VENV}) -> DoubleRetest.update: "
                                f"{states}, EXECUTION_STATE {su.get('EXECUTION_STATE')}, can_submit_order {su.get('can_submit_order')} (bramka: brak backtestu "
                                f"-> BLOCKED zgodnie z założeniem)",
                           f"setup_v2 {json.dumps(su, default=str)[:300]} (forecast/service.py:181-205, forecast/double_retest.py:277)")
    ctx.step = "contract"
    need = {"version", "strategy", "states", "DATA_STATE", "VALIDATION_STATE", "EXECUTION_STATE", "can_submit_order", "block_reasons"}
    miss = sorted(need - set(su))
    out["contract"] = check(not miss and su.get("version") == DR.VERSION and su.get("EXECUTION_STATE") == "BLOCKED" and su.get("can_submit_order") is False
                            and str(su.get("VALIDATION_STATE", "")).startswith("NOT_VALIDATED"),
                            f"własny słownik {DR.VERSION}: klucze {sorted(need)}, VALIDATION_STATE NOT_VALIDATED, EXECUTION_STATE BLOCKED, can_submit_order False",
                            f"brak kluczy {miss} albo stan wykonania inny niż BLOCKED: {json.dumps(su, default=str)[:300]}")
    return out


# ---------------------------------------------------------------------------------------------------------------- scalp C
def _scalp_c(ctx) -> dict:
    early, tr = _common(ctx, ("predict", "contract"))
    if early:
        return early
    out = {"env": ok(f"{VENV}: {tr['py']}")}
    if tr.get("scalp_error"):
        out["predict"] = fail(f"_train_scalp w {VENV}: {tr['scalp_error']}")
        return out
    c = tr["scalp"]["C"]
    ctx.step = "predict"
    lv = _live(ctx)
    hv = lv["sc"].statuses().get("HEDGE_VALID") or {}
    entry = (lv["sc"].registry().get("runs") or {}).get(tr["scalp"]["run_id"]) or {}
    allowed = ("INSUFFICIENT_DATA", "HEDGE_BETTER_THAN_REDUCE_SHADOW", "HEDGE_NOT_BETTER_THAN_REDUCE")
    out["predict"] = check(c["status"] in allowed and entry.get("task_c_status") == c["status"] and hv.get("value") is False,
                           f"scalp_train.task_bc na {tr['scalp']['rows_m1']} M1 syntetycznych ({c['replay'].replace('REPLAY: ', 'replay: ')}) -> "
                           f"hedge_summary dev/holdout {c['hedge_dev']}/{c['hedge_hold']} -> {c['status']} (poprawnie: za mało cykli); wpis rejestru "
                           f"task_c_status {entry.get('task_c_status')}; ScalpService.statuses HEDGE_VALID {hv.get('value')} (ocena polityki, nie sieć)",
                           f"C {c}, rejestr {entry.get('task_c_status')}, HEDGE_VALID {hv} (gold_candles_runtime/scalp_train.py:479-502)"[:400])
    ctx.step = "contract"
    need = {"policy_eval_development", "policy_eval_holdout", "margin_mode_assumed", "status"}
    miss = sorted(need - set(c["keys"]))
    out["contract"] = check(not miss, f"własny słownik task_C: klucze {sorted(need)}, margin_mode_assumed {c.get('margin_mode_assumed')}, "
                                      f"status ∈ {list(allowed)}", f"brak kluczy {miss} w task_C")
    return out


SMOKES = {
    "scalp:A_direction": _scalp_a,
    "scalp:B_setup_quality": _scalp_b,
    "forecast:gold_candles": _gold,
    "forecast:double_retest_v2": _double_retest,
    "scalp:C_policy": _scalp_c,
}


# ---------------------------------------------------------------------------------------------------------------- .venv_candles side
def _train_scalp(hist: Path, out: Path) -> int:
    """Runs in .venv_candles. The trainer's own functions on the last SCALP_DAYS of the synthetic export (the code path of
    scalp_train.main without its walk-forward HGB/MLP/quantiles) + the registry entry main() writes (not active)."""
    from datetime import UTC, datetime

    import numpy as np
    from gold_candles_runtime import scalp_features as SF
    from gold_candles_runtime import scalp_infer as SI
    from gold_candles_runtime import scalp_train as T
    from gold_candles_runtime.common import sha256_file, write_json_atomic

    from masterquo.scalp.strategy import SETUP_FEATURES
    t_start = time.monotonic()
    d = T.load(hist, "SYNTHETIC_TEST")
    n = SCALP_DAYS * 1440
    for k in ("t", "o", "h", "l", "c", "tv", "sp"):
        d[k] = d[k][-n:]
    tick = float(d["meta"]["tick_size"])
    com, conv = T.commission_price(0.5, d["meta"])
    costs = {"commission_per_lot_side": 0.5, "commission_price_side": com, "slippage_ticks": 2.0, "slippage_price": 2.0 * tick, "conversion": conv}
    plan = T.make_plan(d["t"], d, costs, True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + d["dataset_sha"][:8] + "_SYN_SMOKE"
    rd = SI.scalp_dir() / "runs" / run_id
    rd.mkdir(parents=True, exist_ok=True)
    b = plan["boundaries_utc"]
    cal0, hold0 = T._ts(b["calibration"][0]), T._ts(b["holdout"][0])
    X, atr = SF.build(d["t"], d["o"], d["h"], d["l"], d["c"], d["tv"], d["sp"])
    Y, _Q, END = SF.labels(d["t"], d["c"], atr, d["sp"], costs["commission_price_side"], costs["slippage_price"])
    t = np.asarray(d["t"])
    ok_x = ~np.isnan(X).any(axis=1)
    models, arts, hz_rep, checks = {}, {}, {}, {}
    for hz in SF.HORIZONS:
        y, e = Y[hz], END[hz]
        valid = ok_x & (y >= 0)
        dev = valid & (e <= cal0 - T.EMBARGO_S)
        cal = valid & (t >= cal0) & (e <= hold0 - T.EMBARGO_S)
        hold = valid & (t >= hold0)
        prior = np.bincount(y[dev], minlength=3) / max(1, dev.sum())
        m = T.fit_lr(X[dev], y[dev])
        cb = T.fit_calibrator(T.proba(m, X[cal]), y[cal])
        Xh, yh = X[hold], y[hold]
        ph = cb.predict_proba(np.log(np.clip(T.proba(m, Xh), 1e-6, 1)))
        P = np.full((len(yh), 3), 1e-6)
        for j, cl in enumerate(cb.classes_):
            P[:, int(cl)] = ph[:, j]
        hm, bm = T.metrics(P, yh), T.metrics(np.tile(prior, (len(yh), 1)), yh)
        status = "REJECTED" if hm["log_loss"] >= bm["log_loss"] or hm["brier"] >= bm["brier"] else "SHADOW_UNVALIDATED"   # < 30 holdout days
        f = f"model_h{hz}_LR.json"
        write_json_atomic(rd / f, SI.lr_to_json(m[1], m[2]))
        arts[f] = sha256_file(rd / f)
        models[str(hz)] = {"selected": "LR", "prior": prior.tolist(), "file": f, "calibrator": SI.calib_to_json(cb)}
        checks[str(hz)] = (Xh[:50], P[:50])
        hz_rep[str(hz)] = {"rows": {"dev": int(dev.sum()), "cal": int(cal.sum()), "hold": int(hold.sum())}, "status": status, "selected": "LR",
                           "holdout_log_loss": hm["log_loss"], "baseline_log_loss": bm["log_loss"]}
    sts = [v["status"] for v in hz_rep.values()]
    overall = "SHADOW_UNVALIDATED" if "SHADOW_UNVALIDATED" in sts else "REJECTED"
    entry = {"run_id": run_id, "created_at_utc": T._now(), "run_dir": str(rd), "data_kind": "SYNTHETIC_TEST", "symbol": d["meta"]["symbol"],
             "instrument": INST, "dataset_id": d["meta"].get("dataset_id"), "costs": costs, "tick_size": tick, "feature_contract": SF.VERSION,
             "features": list(SF.FEATURES), "contract_hash": plan["contract_hash"], "dataset_sha256": d["dataset_sha"], "boundaries_utc": b,
             "task_a_status": overall, "horizon_status": {k: v["status"] for k, v in hz_rep.items()}, "artifacts": arts, "models": models,
             "small_test": True, "smoke": "modelhub/smoke/scalp_gold.py (najmniejsze wywołanie funkcji trenera)"}
    sm = SI.ScalpModel(entry)
    for k, v in hz_rep.items():
        Xc, Pc = checks[k]
        v["roundtrip_max_abs_diff"] = float(np.max(np.abs(sm.predict(Xc)[k]["P"] - Pc))) if len(Xc) else 1.0
    # task B: generated cycles (the replay of a synthetic series has no Range->Sweep->Retest cycles) through the real trainer function
    rng = np.random.default_rng(1)

    def cycles(nc: int, a: int, z: int) -> list[dict]:
        outc = []
        for k in range(nc):
            fe = {x: float(rng.normal()) for x in SETUP_FEATURES}
            good = bool(rng.random() < 1 / (1 + np.exp(-2.5 * fe["sweep_depth_atr5"])))
            tt = T._iso(a + (z - a) * k // nc)
            outc.append({"features": fe, "tp1_before_sl": good, "net_r": 1.2 if good else -1.0, "fill_time": tt, "exits": [{"time": tt}],
                         "ambiguous": False, "hold_min": 10, "direction": "BUY" if k % 2 else "SELL"})
        return outc
    t0, t1 = int(t.min()), int(t.max())
    dev_c, cal_c, hold_c = cycles(320, t0, cal0 - T.EMBARGO_S), cycles(120, cal0, hold0 - T.EMBARGO_S), cycles(150, hold0, t1)
    B, spec, b_arts = T.train_setup_model(dev_c, cal_c, hold_c, T.MIN, lambda *a, **k: None, rd)
    arts.update(b_arts)
    entry["setup_model"] = spec
    brep = {"status": B["status"], "selected": B.get("selected"), "threshold": B.get("threshold"), "reason": B.get("reason"),
            "cycles": B["cycles"], "spec_file": (spec or {}).get("file"), "roundtrip_max_abs_diff": 1.0, "probe_rows": 0}
    if spec:
        feats = spec["features"]
        Xd, yd, _r = T._xy(sorted(dev_c, key=lambda c: c["fill_time"]), feats)
        Xp = np.asarray([[c["features"][k] for k in feats] for c in hold_c[:30]])
        p_mem = SI.platt(spec["calibrator"], T._p1(T._fit_bin(spec["selected"], Xd, yd), Xp))
        p_file = SI.SetupModel(entry).predict(Xp)
        brep.update(roundtrip_max_abs_diff=float(np.max(np.abs(p_file - p_mem))), probe_rows=len(Xp), probe_features=hold_c[0]["features"],
                    probe_p_file=float(p_file[0]))
    # task C (and B on the replay cycles): the trainer's task_bc on the same M1 slice
    logs: list[str] = []
    Br, C, _s, _a = T.task_bc(d, plan, costs, lambda step, msg, **k: logs.append(f"{step}: {msg}"), X, plan["minimums"], None)
    replay = next((x for x in logs if x.startswith("REPLAY")), "REPLAY: ?")
    brep.update(replay=replay, replay_status=Br["status"])
    entry.update(task_b_status=B["status"], task_c_status=C["status"], activation="NOT_ACTIVATED:SMALL_TEST")
    reg = T._registry_for_update()
    reg["runs"][run_id] = entry
    write_json_atomic(SI.registry_path(), reg)
    crep = {"status": C["status"], "reason": C.get("reason"), "margin_mode_assumed": C.get("margin_mode_assumed"), "keys": sorted(C), "replay": replay,
            "hedge_dev": (C.get("policy_eval_development") or {}).get("status"), "hedge_hold": (C.get("policy_eval_holdout") or {}).get("status")}
    out.write_text(json.dumps({"run_id": run_id, "rows_m1": len(d["t"]), "seconds": round(time.monotonic() - t_start, 1),
                               "A": {"overall": overall, "horizons": hz_rep}, "B": brep, "C": crep}, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["_train_scalp"]:
        raise SystemExit(_train_scalp(Path(sys.argv[2]), Path(sys.argv[3])))
    raise SystemExit("użycie: python -m masterquo.modelhub.smoke.scalp_gold _train_scalp <eksport> <wynik.json>")
