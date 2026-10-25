"""Frozen fixtures + Python reference outputs for the native MQL5 self-test (mql5/MasterModels/Scripts/PMW_MM_SelfTest.mq5).

Files (ASCII CSV, '.' decimal, 17 significant digits):
  mm_fixture_bars.csv     t,o,h,l,c,tv          deterministic random walk (SYNTHETIC - for code parity only)
  mm_ref_kalman.csv       t,fast,slow,K_fast,K_slow,P_fast,P_slow,event   (CrossConfig defaults)
  mm_ref_gpr.csv          one line per probe: T,ell,signal_var,noise_var,mean,latent_var,observed_var,lml (fixed hyper-parameters, window 60, h 3)
  mm_ref_hdc.csv          D=256 vectors a,b (16 hex words each) + expected hamming(a,b), bind, permute(a,77), bundle(a,b,c) words
  mm_ref_breakout.csv     accepted breakout events (bar_ts,direction,zone_lower,zone_upper) with confirmation NONE
The MQL5 script writes PMW_MM_NATIVE.txt; `parity()` compares it with these references (status NATIVE_NOT_EXECUTED until it exists).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import breakout_zones as BZ
from . import gpr as G
from . import hdc as H
from . import kalman as K
from .data import Bars


def _fixture_bars(n: int = 1500) -> Bars:
    g = np.random.Generator(np.random.PCG64(20261025))
    c = 2300 + np.cumsum(g.normal(0, 0.8, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(g.normal(0, 0.3, n))
    lo = np.minimum(o, c) - np.abs(g.normal(0, 0.3, n))
    t = 1_790_000_000 + 300 * np.arange(n)
    return Bars("M5", t.astype(float), o, h, lo, c, np.round(np.abs(g.normal(120, 30, n))), np.full(n, 12.0))


def export(out: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    b = _fixture_bars()
    f = lambda x: f"{x:.17g}"  # noqa: E731
    (out / "mm_fixture_bars.csv").write_text("t,o,h,l,c,tv\n" + "\n".join(",".join([str(int(b.t[i]))] + [f(v[i]) for v in (b.o, b.h, b.l, b.c, b.tv)])
                                                                         for i in range(len(b))) + "\n", encoding="ascii")
    k, rows = K.run(b.t, b.c, K.CrossConfig())
    ev = {e["bar_time"]: e["direction"] for e in k.events}
    (out / "mm_ref_kalman.csv").write_text("t,fast,slow,K_fast,K_slow,P_fast,P_slow,event\n" + "\n".join(
        f"{int(r['bar_time'])},{f(r['fast'])},{f(r['slow'])},{f(r['K_fast'] if r['K_fast'] is not None else math.nan)},"
        f"{f(r['K_slow'] if r['K_slow'] is not None else math.nan)},{f(r['P_fast'])},{f(r['P_slow'])},{ev.get(r['bar_time'], '')}" for r in rows) + "\n",
        encoding="ascii")
    cfg = G.GPRConfig(window=60, horizon=3, auto_tune=False, ell=4.0, signal_var=0.1, noise_var=0.5)
    lines = ["T,ell,signal_var,noise_var,mean,latent_var,observed_var,lml"]
    for T in (300, 700, 1200, 1499):
        m = G.GPModel(cfg)
        r = m.refit(b.c, T, False)
        p = m.predict(math.log(b.c[T] / b.c[T - 1]), b.c[T])
        lines.append(",".join([str(T), f(cfg.ell), f(cfg.signal_var), f(cfg.noise_var), f(p["mean_logret"]), f(p["latent_var"]), f(p["observed_var"]), f(r["lml"])]))
    (out / "mm_ref_gpr.csv").write_text("\n".join(lines) + "\n", encoding="ascii")
    sp = H.Space(256, seed=7)
    a, bb, c = sp.random(1), sp.random(2), sp.random(3)
    hexw = lambda v: " ".join(f"{int(w):016x}" for w in v)  # noqa: E731
    (out / "mm_ref_hdc.csv").write_text("\n".join([f"D,{sp.D}", f"a,{hexw(a)}", f"b,{hexw(bb)}", f"c,{hexw(c)}", f"tie,{hexw(sp.tie)}",
                                                   f"hamming_ab,{sp.hamming(a, bb)}", f"bind_ab,{hexw(sp.bind(a, bb))}", f"perm_a_77,{hexw(sp.permute(a, 77))}",
                                                   f"bundle_abc,{hexw(sp.bundle([a, bb, c]))}", f"bundle_ab_tie,{hexw(sp.bundle([a, bb]))}"]) + "\n", encoding="ascii")
    e = BZ.run(b, BZ.BreakoutConfig(confirmation="NONE"), 0.01, 300)
    (out / "mm_ref_breakout.csv").write_text("bar_ts,direction,zone_lower,zone_upper\n" + "\n".join(
        f"{int(x['bar_ts'])},{x['direction']},{f(x['zone_lower'])},{f(x['zone_upper'])}" for x in e.events) + "\n", encoding="ascii")
    return {"files": sorted(p.name for p in out.iterdir()), "bars": len(b), "kalman_events": len(k.events), "breakout_events": len(e.events),
            "note": "dane syntetyczne do porównania implementacji natywnej z referencją Python"}


def parity(native_file: Path, ref_dir: Path, tol: float = 1e-9) -> dict:
    """Compare PMW_MM_NATIVE.txt (JSON written by PMW_MM_SelfTest.mq5) with the references:
    kalman rows [t,fast,slow,K_fast,K_slow,P_fast,P_slow,event], gpr rows [T,ell,sv,nv,mean,latent,observed,lml], hdc checks, breakout
    events [bar_ts,direction,lower,upper]. Status NATIVE_NOT_EXECUTED until the file exists (the script must run inside MT5)."""
    p = Path(native_file)
    if not p.exists():
        return {"status": "NATIVE_NOT_EXECUTED", "reason": f"brak {p.name} - uruchom PMW_MM_SelfTest.mq5 w terminalu MT5"}
    try:
        nat = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as e:
        return {"status": "NATIVE_OUTPUT_INVALID", "reason": str(e)[:200]}
    ref_dir = Path(ref_dir)
    num = lambda x: math.nan if x in (None, "", "nan", "null") else float(x)  # noqa: E731

    def maxdiff(ref_rows, nat_rows, cols):
        if not nat_rows or len(ref_rows) != len(nat_rows):
            return None
        d = 0.0
        for r, n in zip(ref_rows, nat_rows):
            for c in cols:
                a, b = num(r[c]), num(n[c])
                if math.isnan(a) and math.isnan(b):
                    continue
                if math.isnan(a) or math.isnan(b):
                    return math.inf
                d = max(d, abs(a - b))
        return d

    out: dict = {}
    rk = [ln.split(",") for ln in (ref_dir / "mm_ref_kalman.csv").read_text().splitlines()[1:] if ln]
    nk = nat.get("kalman") or []
    out["kalman_rows"] = [len(rk), len(nk)]
    out["kalman_max_abs_diff"] = maxdiff(rk, nk, (1, 2, 5, 6))
    out["kalman_events_equal"] = bool(nk) and [r[7] for r in rk] == [str(n[7]) for n in nk]
    rg = [ln.split(",") for ln in (ref_dir / "mm_ref_gpr.csv").read_text().splitlines()[1:] if ln]
    ng = nat.get("gpr") or []
    out["gpr_max_abs_mean_diff"] = maxdiff(rg, ng, (4,))
    out["gpr_max_abs_var_diff"] = maxdiff(rg, ng, (5, 6))
    out["gpr_max_abs_lml_diff"] = maxdiff(rg, ng, (7,))
    out["hdc"] = nat.get("hdc")
    rb = [ln.split(",") for ln in (ref_dir / "mm_ref_breakout.csv").read_text().splitlines()[1:] if ln]
    nb = nat.get("breakout")
    out["breakout_events"] = [len(rb), None if nb is None else len(nb)]
    out["breakout_equal"] = nb is not None and len(rb) == len(nb) and all(
        int(r[0]) == int(n[0]) and r[1] == n[1] for r, n in zip(rb, nb)) and (maxdiff(rb, nb, (2, 3)) or 0.0) <= tol
    gates = {"kalman": out["kalman_max_abs_diff"] is not None and out["kalman_max_abs_diff"] <= tol and out["kalman_events_equal"],
             "gpr": out["gpr_max_abs_mean_diff"] is not None and out["gpr_max_abs_mean_diff"] <= tol and (out["gpr_max_abs_var_diff"] or 0) <= tol,
             "hdc": (nat.get("hdc") or {}).get("all_pass") is True, "breakout": out["breakout_equal"]}
    out["gates"] = gates
    out["tolerance"] = tol
    out["terminal"] = nat.get("terminal")
    out["status"] = "NATIVE_PARITY_PASS" if all(gates.values()) else "NATIVE_PARITY_FAIL"
    return out
