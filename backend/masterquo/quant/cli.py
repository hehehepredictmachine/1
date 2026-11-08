"""python -m masterquo quant <command>   (PMW Quant Core)

  status      [--instrument X]              mode, ledger evidence, meta-model artifacts (+ live state when the bot is running)
  inventory   [--out DIR] [--instrument X]  docs/quant/INVENTORY.md + INVENTORY.json (live states when the bot is running: --live)
  train       [--instrument X] [--task H]   train the meta-model from the Quant ledger (never activates)
  list        [--instrument X]              trained versions with status and test metrics
  activate    --task H --version V          activate a VALIDATED_SHADOW version (SHADOW; ASSIST is a separate, explicit step)
  rollback    --task H                      previous active version (or none)
  mode        OFF|SHADOW|ASSIST [--confirm] Quant mode; ASSIST needs a validated active model AND --confirm
  bench       [--n 200] [--api-n 50]        component timings p50/p95/p99 (+ API and live cycle timings when the bot is running)
Exit codes: 0 ok, 1 error, 2 insufficient data / bad arguments, 3 refused.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def _p(o) -> None:
    print(json.dumps(o, indent=1, ensure_ascii=False, default=str))


def _server(path: str, timeout: float = 5.0):
    try:
        from ..config import ConfigStore
        port = ConfigStore().get().server.port
    except Exception:  # noqa: BLE001
        port = 8765
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": f"127.0.0.1:{port}"}), timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="masterquo quant", description="PMW Quant Core – inwentaryzacja, meta-model, tryb SHADOW/ASSIST, pomiary")
    ap.add_argument("cmd", choices=["status", "inventory", "train", "list", "activate", "rollback", "mode", "bench"])
    ap.add_argument("value", nargs="?", help="mode: OFF|SHADOW|ASSIST")
    ap.add_argument("--instrument", default="XAUUSD", type=str.upper, choices=["XAUUSD", "BTC"])
    ap.add_argument("--task", default=None)
    ap.add_argument("--version", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true", help="inventory: stany z działającego bota (API)")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--api-n", type=int, default=50)
    a = ap.parse_args(argv)
    from . import metamodel as M
    from . import service as SV
    from .ledger import QuantLedger
    inst = a.instrument
    if a.cmd == "inventory":
        from . import inventory as I
        out = Path(a.out) if a.out else Path(__file__).resolve().parents[3] / "docs" / "quant"
        if a.live:
            live = _server("/api/v1/quant/inventory", 60)
            if live is None:
                print("[BŁĄD] --live: bot nie odpowiada na /api/v1/quant/inventory")
                return 1
            inv = {"version": I.VERSION, "generated_at": live["generated_at"], "instrument": inst, "runtime": "LIVE (API działającego bota)",
                   "entries": live["entries"], "coverage": live["coverage"]}
            out.mkdir(parents=True, exist_ok=True)
            (out / "INVENTORY.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
            (out / "INVENTORY.md").write_text(I.to_markdown(inv), encoding="utf-8")
        else:
            inv = I.write(out, None, inst)
        c = inv["coverage"]
        print(f"[QUANT] inwentaryzacja: {c['inventory']['recognised']} komponentów, sklasyfikowano {c['inventory']['classified']}, "
              f"z adapterem {c['adapters']['with_adapter']}, NOT_APPLICABLE uzasadnione {c['adapters']['not_applicable_justified']}, "
              f"brakujące {len(c['adapters']['missing'])}; operacyjnie gotowe {c['operational']['ready_with_live_output']}; "
              f"zwalidowane {c['analytical']['validated_for_role']} -> {out}")
        return 0 if not c["adapters"]["missing"] else 1
    led = QuantLedger(SV.qdir() / "ledger.sqlite")
    if a.cmd == "status":
        st = SV.Settings(SV.qdir() / "settings.json").get()
        live = _server("/api/v1/quant/status")
        _p({"mode": st["mode"], "assist": st.get("assist"), "ledger": led.counts(inst), "active": M.pointer(inst).get("active"),
            "versions": M.list_versions(inst)[-10:], "bot": "działa" if live else "nie działa (stan offline z plików)",
            "live": {k: (live or {}).get(k) for k in ("generation", "complete", "models", "snapshot", "timings")} if live else None})
        return 0
    if a.cmd == "train":
        res = SV.train_from_ledger(led, inst, a.task)
        _p(res)
        return 2 if all(r["status"] == "INSUFFICIENT_EVIDENCE" for r in res) else 0
    if a.cmd == "list":
        _p({"active": M.pointer(inst).get("active"), "versions": M.list_versions(inst)})
        return 0
    if a.cmd == "activate":
        if not (a.task and a.version):
            print("[BŁĄD] wymagane --task i --version")
            return 2
        try:
            _p(M.activate(inst, a.task, a.version))
        except (M.MetaError, OSError, ValueError) as exc:
            print(f"[ODMOWA] {exc}")
            return 3
        return 0
    if a.cmd == "rollback":
        if not a.task:
            print("[BŁĄD] wymagane --task")
            return 2
        _p(M.rollback(inst, a.task))
        return 0
    if a.cmd == "mode":
        if (a.value or "").upper() not in SV.MODES:
            print("[BŁĄD] tryb: OFF | SHADOW | ASSIST")
            return 2

        class _Rt:                                    # offline: instrument from the argument, no runtime needed to switch the file
            class sh:
                @staticmethod
                def instrument():
                    return inst
        q = SV.QuantService.__new__(SV.QuantService)
        q.rt, q.clock, q.settings = _Rt(), time.time, SV.Settings(SV.qdir() / "settings.json")
        r = q.set_mode(a.value, confirm=a.confirm, by="CLI")
        _p(r)
        return 0 if r["ok"] else 3
    if a.cmd == "bench":
        _p(bench(a.n, a.api_n))
        return 0
    return 1


def bench(n: int = 200, api_n: int = 50) -> dict:
    """Component micro-benchmarks on synthetic inputs (CPU only) + API latency and live cycle percentiles when the bot is running."""
    import os
    import platform

    import numpy as np

    from . import checks as CK
    from . import events as EV
    from . import metamodel as M
    from . import snapshot as S
    from .service import percentiles
    from ..modelhub import contract as C
    rng = np.random.default_rng(3)
    tim: dict[str, list[float]] = {}

    def t(name, fn):
        t0 = time.perf_counter()
        fn()
        tim.setdefault(name, []).append((time.perf_counter() - t0) * 1000)
    now = time.time()
    bars = []
    p = 2000.0
    for i in range(600):
        o = p
        p += float(rng.normal(0, 0.5))
        bars.append({"open_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - (600 - i) * 60)), "o": o, "h": max(o, p) + 0.2, "l": min(o, p) - 0.2,
                     "c": p, "tv": 10, "spread": 20, "closed": True})
    preds = [C.make(instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", model_name=f"TH_LOGREG_M5_H{k}", model_version="v1", task_type="CLASS_PROBABILITIES",
                    task=f"DIRECTION_H{k}_M5", horizon_bars=k, unit="probability", state="READY", result={"DOWN": 0.3, "FLAT": 0.3, "UP": 0.4},
                    data_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 300))) for k in range(1, 41)]
    rows = []
    for i in range(400):
        x = float(rng.normal())
        rows.append({"row_id": f"b{i}", "decision_ts": 1e9 + i * 600, "resolve_ts": 1e9 + i * 600 + 1200, "y": int(rng.random() < 1 / (1 + np.exp(-x))),
                     "net_r": x, "data_kind": "SYNTHETIC", "features": {"fc:a:edge": x, "plan:gain_r": 1.5}})
    res = M.train(rows, task={"task_hash": "bench", "event_id": "TP1_BEFORE_STOP"}, crit={"min_dev": 100, "min_cal": 40, "min_test": 40})
    model = res.get("model")
    spec = EV.EventSpec(instrument="XAUUSD", strategy="bench", direction="LONG", entry=2000.0, sl=1998.0, targets=((2002.5, 0.5), (2003.0, 0.3), (2005.0, 0.2)),
                        horizon_s=3600, cost_price=0.1)
    nb = S.normalise(bars, "M1")
    for _ in range(n):
        t("snapshot_qc_600_bars", lambda: S.qc(S.normalise(bars, "M1"), "M1"))
        t("contract_checks_40_preds", lambda: CK.screen(preds, now=now))
        t("event_simulate_60_bars", lambda: EV.simulate(spec, nb, nb[0]["t"]))
        if model:
            t("metamodel_predict", lambda: M.predict(model, rows[0]["features"]))
    out = {"hardware": {"platform": platform.platform(), "cpu_count": os.cpu_count(), "python": platform.python_version(), "numpy": np.__version__},
           "n": n, "components": percentiles(tim), "metamodel_train_400_rows_s": res["report"].get("train_s")}
    live = _server("/api/v1/quant/status")
    if live:
        lat = []
        for _ in range(api_n):
            t0 = time.perf_counter()
            _server("/api/v1/quant/status")
            lat.append((time.perf_counter() - t0) * 1000)
        out["api_quant_status"] = percentiles({"GET /api/v1/quant/status": lat})
        out["live_cycle"] = live.get("timings")
        out["live_models"] = live.get("models")
    else:
        out["api_quant_status"] = "NOT_RUN (bot nie działa)"
    return out
