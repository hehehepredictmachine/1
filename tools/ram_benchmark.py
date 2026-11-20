"""1.40 RAM / latency benchmark of the AI model processes - the SAME worker programs and JSON protocol the bot uses (tsfm_runtime.worker,
kronos_runtime.worker), real weights, real closed bars of a CSV/JSON history. Nothing is simulated: every number is read from the OS
(/proc on Linux, WinAPI on Windows) through masterquo.resources.governor._proc_mem / sysres.memory.

  python tools/ram_benchmark.py --bars XAUUSD_M5.json [--bars15 XAUUSD_M15.json] --tsfm-weights DIR --kronos-weights DIR
                                [--granite-python EXE] [--chronos-python EXE] [--kronos-python EXE] [--cycles 100] [--out report.json]
                                [--backend-pid PID]

Phases: baseline -> each model loaded alone (load time, RSS, peak) -> single inference p50 / p95 -> sequential inference of all three on
M5 and M15 (one heavy model at a time, as the governor slot does) for --cycles closed bars of the history (replay) -> totals: system RAM
used %, available, sum of the model processes, peaks, OOM / errors. A model that is not installed is reported NOT RUN with the reason.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from masterquo import sysres  # noqa: E402
from masterquo.resources.governor import _proc_mem  # noqa: E402


class Worker:
    def __init__(self, name, argv, env):
        self.name = name
        self.p = subprocess.Popen(argv, cwd=str(ROOT / "backend"), env=env, text=True, encoding="utf-8", stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1)
        self.n = 0

    def ask(self, req, timeout=600):
        self.n += 1
        req = {**req, "id": f"r{self.n}"}
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        box = {}

        def rd():
            while True:
                line = self.p.stdout.readline()
                if not line:
                    return
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("id") == req["id"]:
                    box["m"] = m
                    return
        th = threading.Thread(target=rd, daemon=True)
        th.start()
        th.join(timeout)
        if "m" not in box:
            raise TimeoutError(f"{self.name}: brak odpowiedzi w {timeout} s")
        return box["m"]

    def mem(self):
        return _proc_mem(self.p.pid)

    def close(self):
        try:
            self.ask({"cmd": "quit"}, 20)
        except Exception:  # noqa: BLE001
            pass
        if self.p.poll() is None:
            self.p.kill()


def pct(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    pick = lambda q: round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)  # noqa: E731
    return {"n": len(xs), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": round(xs[-1], 1)}


def load_bars(p):
    b = json.loads(Path(p).read_text(encoding="utf-8"))
    if isinstance(b, dict):
        return [[t, o, h, l, c] for t, o, h, l, c in zip(b["times"], b["open"], b["high"], b["low"], b["close"])]
    return b


def sysmem():
    m = sysres.memory()
    return {"used_pct": m.get("used_pct"), "total_mb": m.get("total_mb"),
            "available_mb": round(m["total_mb"] * (100 - m["used_pct"]) / 100) if m.get("total_mb") and m.get("used_pct") is not None else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--bars15")
    ap.add_argument("--tsfm-weights", required=True)
    ap.add_argument("--kronos-weights")
    ap.add_argument("--granite-python", default=str(ROOT / ".venv_granite" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")))
    ap.add_argument("--chronos-python", default=str(ROOT / ".venv_chronos2" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")))
    ap.add_argument("--kronos-python", default=str(ROOT / ".venv_kronos" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")))
    ap.add_argument("--threads-heavy", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    ap.add_argument("--threads-light", type=int, default=max(1, min(2, (os.cpu_count() or 2) // 4 or 1)))
    ap.add_argument("--cycles", type=int, default=100)
    ap.add_argument("--single", type=int, default=50)
    ap.add_argument("--backend-pid", type=int)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
    rep = {"schema": "PMW-RAM-BENCH-1", "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cpu_count": os.cpu_count(),
           "platform": sys.platform, "baseline": sysmem(), "models": {}, "not_run": {}}
    if a.backend_pid:
        rss, peak = _proc_mem(a.backend_pid)
        rep["backend"] = {"rss_mb": rss, "peak_mb": peak, "note": "proces backendu bota (FastAPI + silnik + bridge) w chwili pomiaru"}
    b5 = load_bars(a.bars)
    b15 = load_bars(a.bars15) if a.bars15 else None
    workers = {}
    specs = [("granite_ttm", a.granite_python, ["-m", "tsfm_runtime.worker", "--model", "granite_ttm"],
              {"cmd": "load", "weights_root": a.tsfm_weights, "device": "CPU", "threads": a.threads_light, "verify_files": True}),
             ("chronos2", a.chronos_python, ["-m", "tsfm_runtime.worker", "--model", "chronos2"],
              {"cmd": "load", "weights_root": a.tsfm_weights, "device": "CPU", "threads": a.threads_heavy, "verify_files": True})]
    if a.kronos_weights:
        specs.append(("kronos", a.kronos_python, ["-m", "kronos_runtime.worker"],
                      {"cmd": "load", "weights_dir": a.kronos_weights, "device": "CPU", "max_context": 512, "threads": a.threads_heavy, "verify_files": True}))
    else:
        rep["not_run"]["kronos"] = "brak --kronos-weights"
    for name, py, args, load in specs:
        py = os.path.abspath(py)
        if not Path(py).is_file():
            rep["not_run"][name] = f"brak interpretera {py}"
            continue
        before = sysmem()
        w = Worker(name, [py, *args], env)
        try:
            hello = w.ask({"cmd": "hello"}, 300)
            if not hello.get("ok"):
                rep["not_run"][name] = f"hello: {hello.get('error')}"
                w.close()
                continue
            rss0, _ = w.mem()
            t0 = time.perf_counter()
            r = w.ask(load, 1800)
            load_s = time.perf_counter() - t0
            if not r.get("ok"):
                rep["not_run"][name] = f"{r.get('code')}: {r.get('error')}"
                w.close()
                continue
            rss, peak = w.mem()
            rep["models"][name] = {"rss_after_start_mb": rss0, "rss_loaded_mb": rss, "peak_load_mb": peak, "load_s": round(load_s, 2),
                                   "params": r["info"].get("params"), "device": r["info"].get("device"), "threads": r["info"].get("threads"),
                                   "system_before": before, "system_after": sysmem()}
            workers[name] = w
        except Exception as exc:  # noqa: BLE001
            rep["not_run"][name] = f"{type(exc).__name__}: {exc}"[:300]
            w.close()

    def req(name, bars, i, H, tf_min):
        ctx = bars[i - 511:i + 1]
        if name == "kronos":
            last = datetime.fromisoformat(ctx[-1][0])
            return {"cmd": "predict", "candles": {"t": [x[0].replace("T", " ") for x in ctx], "open": [x[1] for x in ctx], "high": [x[2] for x in ctx],
                                                  "low": [x[3] for x in ctx], "close": [x[4] for x in ctx], "volume": None},
                    "y_t": [(last + timedelta(minutes=tf_min * (k + 1))).strftime("%Y-%m-%d %H:%M:%S") for k in range(H)], "pred_len": H,
                    "T": 1.0, "top_k": 0, "top_p": 0.9, "seed": i, "paths": 0}
        return {"cmd": "predict", "close": [x[4] for x in ctx], "pred_len": H, "context_len": 512, "profile": "CLOSE_V1",
                "quantiles": [0.1, 0.5, 0.9], "freq_tf": "M5" if tf_min == 5 else "M15"}

    # single inference latency per model (M5, H = 12)
    start = len(b5) - a.single - a.cycles - 20
    for name, w in workers.items():
        ms, errs = [], 0
        for k in range(a.single):
            t0 = time.perf_counter()
            r = w.ask(req(name, b5, start + k, 12, 5), 600)
            if r.get("ok"):
                ms.append((time.perf_counter() - t0) * 1000)
            else:
                errs += 1
        rss, peak = w.mem()
        rep["models"][name]["single_m5"] = {**pct(ms), "errors": errs, "rss_mb": rss, "peak_mb": peak,
                                            "note": "czas obejmuje komunikację JSON z procesem modelu (jak w bocie)"}
    # sequential cycles: every closed bar -> all models on M5 (and M15 every 3rd bar), one at a time
    cyc = {n: [] for n in workers}
    peak_sys, peak_sum, errors = 0.0, 0.0, 0
    t_start = time.perf_counter()
    for c in range(a.cycles):
        i = len(b5) - a.cycles + c - 1
        jobs = [(n, b5, i, 12, 5) for n in workers]
        if b15 and c % 3 == 0:
            j15 = len(b15) - a.cycles // 3 + c // 3 - 1
            jobs += [(n, b15, j15, 8, 15) for n in workers]
        for n, bars, idx, H, tfm in jobs:
            t0 = time.perf_counter()
            try:
                r = workers[n].ask(req(n, bars, idx, H, tfm), 600)
                if r.get("ok"):
                    cyc[n].append((time.perf_counter() - t0) * 1000)
                else:
                    errors += 1
            except Exception:  # noqa: BLE001
                errors += 1
        sm = sysmem()
        peak_sys = max(peak_sys, sm["used_pct"] or 0)
        peak_sum = max(peak_sum, sum((w.mem()[0] or 0) for w in workers.values()))
    rep["sequential"] = {"cycles": a.cycles, "with_m15": bool(b15), "seconds": round(time.perf_counter() - t_start, 1),
                         "latency": {n: pct(v) for n, v in cyc.items()}, "errors": errors, "peak_system_used_pct": peak_sys,
                         "peak_sum_models_rss_mb": round(peak_sum, 1),
                         "final": {n: dict(zip(("rss_mb", "peak_mb"), w.mem())) for n, w in workers.items()}, "system_end": sysmem()}
    for w in workers.values():
        w.close()
    rep["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    txt = json.dumps(rep, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
