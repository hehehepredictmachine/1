"""Frozen fixtures + Python reference outputs for the native MQL5 self-test (mql5/MasterModels/Scripts/PMW_MM_SelfTest.mq5).

Files (ASCII CSV, '.' decimal, 17 significant digits; "key,value" files hold one value per key, the value is everything after the first comma):
  mm_fixture_bars.csv     t,o,h,l,c,tv          deterministic random walk (SYNTHETIC - for code parity only)
  mm_ref_kalman.csv       t,fast,slow,K_fast,K_slow,P_fast,P_slow,event   (CrossConfig defaults)
  mm_ref_gpr.csv          one line per probe: T,ell,signal_var,noise_var,mean,latent_var,observed_var,lml (fixed hyper-parameters, window 60, h 3)
  mm_ref_gpr_tune.csv     same columns with the hyper-parameters chosen by the LML grid search (auto-tune, default 7x5x9 grid - the indicator
                          default InpAutoTune=true)
  mm_ref_hdc.csv          D=256 vectors a,b (16 hex words each) + expected hamming(a,b), bind, permute(a,77), bundle(a,b,c) words
  mm_ref_hdc_acc.csv      key,value: class accumulators (CPmwHDCAcc vs hdc.Classifier): updates u<i>_y/u<i>_v, prototypes proto<k>, queries
                          q<j> with the expected class q<j>_pred, margin q<j>_margin and similarities q<j>_sims
  mm_ref_breakout.csv     accepted breakout events (bar_ts,direction,zone_lower,zone_upper) with confirmation NONE (kept for compatibility)
  mm_ref_breakout_<MODE>.csv  the same for every confirmation mode SESSION_VWAP (indicator default) / SMA / SMMA / NONE
  mm_fixture_ticks.csv    read,read_until,time_msc,bid,ask,last,volume,volume_real,flags - overlapping inclusive range reads (read_until -1 =
                          the newest millisecond stays open, like the indicator's Poll)
  mm_ref_tsvp.csv         key,value: session + tick size, per configuration (proxy / actual / atr) its Setup inputs and <name>_expected = JSON
                          {reads [[added, state before the render pass, buckets drawn, status]], buckets [[key, value, count]], poc, max, total,
                          counted, ignored [outside, not_eligible, invalid, duplicate], rehashes, size, status} of tsvp.Profile
  mm_ref_stack.csv        key,value: S, D, descriptors p<i>, query q, checkpoints and c<n>_raw / c<n>_l2 / c<n>_valid of event_engine.StateStack
The MQL5 script writes PMW_MM_NATIVE.txt; `parity()` compares it with these references (status NATIVE_NOT_EXECUTED until it exists). Every
gate is computed here in Python from the raw native values - a self-check flag written by the script is informational only.
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
from . import tsvp as TV
from .data import Bars

GPR_PROBES = (300, 700, 1200, 1499)
GPR_TUNE_PROBES = (300, 700, 900, 1200, 1499)
TSVP_START_MS = 1_790_000_000_000
TSVP_END_MS = TSVP_START_MS + 600_000
TSVP_TICK = 0.01
# name -> (source 0 proxy / 1 actual, bucket mode 0 manual / 1 atr, bucket ticks, atr mult, atr, any quote)
TSVP_CONFIGS = {"proxy": (0, 0, 2, 0.25, 0.0, 0), "actual": (1, 0, 10, 0.25, 0.0, 0), "atr": (0, 1, 50, 0.25, 1.37, 1)}
STACK_S, STACK_D, STACK_PUSH, STACK_CHECKS = 8, 16, 20, (5, 20)
STACK_TOL = 1e-5                     # float32 natively (relative to max(1, |ref|)); the Python reference is float64 on float32 inputs
REF_FILES = ("mm_fixture_bars.csv", "mm_ref_kalman.csv", "mm_ref_gpr.csv", "mm_ref_gpr_tune.csv", "mm_ref_hdc.csv", "mm_ref_hdc_acc.csv",
             "mm_ref_breakout.csv", *(f"mm_ref_breakout_{m}.csv" for m in BZ.FILTERS), "mm_fixture_ticks.csv", "mm_ref_tsvp.csv",
             "mm_ref_stack.csv")


def _fixture_bars(n: int = 1500) -> Bars:
    g = np.random.Generator(np.random.PCG64(20261025))
    c = 2300 + np.cumsum(g.normal(0, 0.8, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(g.normal(0, 0.3, n))
    lo = np.minimum(o, c) - np.abs(g.normal(0, 0.3, n))
    t = 1_790_000_000 + 300 * np.arange(n)
    return Bars("M5", t.astype(float), o, h, lo, c, np.round(np.abs(g.normal(120, 30, n))), np.full(n, 12.0))


def _f(x) -> str:
    return f"{x:.17g}"


def _hexw(v) -> str:
    return " ".join(f"{int(w):016x}" for w in v)


def _gpr_lines(c: np.ndarray, cfg: G.GPRConfig, probes, tune: bool) -> list[str]:
    lines = ["T,ell,signal_var,noise_var,mean,latent_var,observed_var,lml"]
    for T in probes:
        m = G.GPModel(cfg)
        r = m.refit(c, T, tune)
        p = m.predict(math.log(c[T] / c[T - 1]), c[T])
        hp = r["hp"]
        lines.append(",".join([str(T), _f(hp["ell"]), _f(hp["signal_var"]), _f(hp["noise_var"]), _f(p["mean_logret"]), _f(p["latent_var"]),
                               _f(p["observed_var"]), _f(r["lml"])]))
    return lines


# ---------------------------------------------------------------------------------------------------------------- HDC accumulators
def _hdc_acc_lines() -> list[str]:
    sp = H.Space(256, seed=7)
    labels = (0, 1, 2, 0, 1, 2, 0, 1)                                     # class 2 gets two votes -> acc == 0 bits -> tie vector
    U = [sp.random(100 + i) for i in range(len(labels))]
    clf = H.Classifier(sp, 3)
    for v, y in zip(U, labels):
        clf.update(v, y)
    protos = clf.finalize()
    Q = [sp.random(1), U[1], sp.random(200), sp.random(201)]
    lines = [f"D,{sp.D}", "C,3", f"tie,{_hexw(sp.tie)}", f"n_updates,{len(U)}"]
    for i, (v, y) in enumerate(zip(U, labels)):
        lines += [f"u{i}_y,{y}", f"u{i}_v,{_hexw(v)}"]
    lines += [f"proto{k},{_hexw(p)}" for k, p in enumerate(protos)]
    lines.append(f"n_queries,{len(Q)}")
    for j, q in enumerate(Q):
        c, m, s = clf.predict(q)
        lines += [f"q{j},{_hexw(q)}", f"q{j}_pred,{c}", f"q{j}_margin,{_f(m)}", f"q{j}_sims," + " ".join(_f(x) for x in s)]
    return lines


# ---------------------------------------------------------------------------------------------------------------- TSVP
def _fixture_ticks() -> list[dict]:
    """Synthetic MT5 ticks around the session [TSVP_START_MS, TSVP_END_MS]: bid changes (BID|ASK), ask-only quotes, quotes without flags at
    an unchanged bid, trades (LAST|VOLUME|BUY/SELL) and genuinely identical ticks in the same millisecond."""
    g = np.random.Generator(np.random.PCG64(20261026))
    ms, bid, ask = TSVP_START_MS - 2_000, 2300.0, 2300.25
    out: list[dict] = []
    for i in range(900):
        u = float(g.random())
        if out and u >= 0.93:                                              # genuinely identical tick, same millisecond
            out.append(dict(out[-1]))
            continue
        ms += int(g.integers(0, 4)) * 700 if out else 0                    # 0 -> another tick in the same millisecond
        last, vol, vreal = 0.0, 0, 0.0
        if u < 0.55:
            bid = round(bid + 0.01 * int(g.choice([k for k in range(-12, 13) if k])), 2)
            ask, flags = round(bid + 0.25, 2), 2 | 4
        elif u < 0.70:
            ask, flags = round(bid + 0.25 + 0.01 * int(g.integers(-3, 4)), 2), 4
        elif u < 0.80:
            flags = 0
        else:
            last = round(bid + 0.01 * int(g.integers(0, 26)), 2)
            vreal = round(float(g.uniform(0.1, 3.0)), 2)
            vol, flags = max(1, int(vreal)), 8 | 16 | (32 if g.random() < 0.5 else 64)
        out.append({"time_msc": ms, "bid": bid, "ask": ask, "last": last, "volume": vol, "volume_real": vreal, "flags": flags})
    return out


def _tick_reads(ticks: list[dict]) -> list[tuple[int, list[dict]]]:
    """Overlapping inclusive reads like the indicator (Rebuild chunks + Poll from tail_ms): each read ends inside a millisecond that has
    several ticks (only its first tick visible yet), the next read starts at that millisecond; then a final read (read_until past the
    last tick) and a full re-read of the same range (adds nothing)."""
    ms = [t["time_msc"] for t in ticks]
    groups = sorted({m for m in ms if ms.count(m) >= 2})
    cuts = [groups[int(len(groups) * f)] for f in (0.2, 0.4, 0.55, 0.7, 0.85)]
    reads: list[tuple[int, list[dict]]] = []
    lo = ms[0]
    for cut in cuts:
        first = ms.index(cut)
        reads.append((-1, [t for t in ticks if lo <= t["time_msc"] < cut] + [ticks[first]]))
        lo = cut
    reads.append((ms[-1] + 1, [t for t in ticks if t["time_msc"] >= lo]))
    reads.append((ms[-1] + 1, [t for t in ticks if t["time_msc"] >= cuts[0]]))
    return reads


def _tsvp_expected(name: str, reads) -> dict:
    src, bmode, bt, am, atr, anyq = TSVP_CONFIGS[name]
    cfg = TV.TSVPConfig(source=("TICK_ACTIVITY_PROXY", "ACTUAL_TRADE_VOLUME")[src], bucket_mode=("MANUAL", "ATR")[bmode], bucket_ticks=bt,
                        atr_mult=am, tick=TSVP_TICK, proxy_event="ANY_QUOTE" if anyq else "BID_CHANGE")
    p = TV.Profile(cfg, TSVP_START_MS, TSVP_END_MS, atr if bmode == 1 else None)
    rr = []
    for until, ticks in reads:
        r = p.ingest(ticks, None if until < 0 else until)
        rr.append([r["added"], r["state"], len(p.render_pass(10 ** 9)["draw"]), r["status"]])
    ig = p.ignored
    return {"reads": rr, "buckets": [[k, v, c] for k, v, c in p.map.items()], "poc": p.poc, "max": p.max_val, "total": p.total,
            "counted": p.counted, "ignored": [ig["outside_session"], ig["not_eligible"], ig["invalid"], ig["duplicate"]], "rehashes": p.map.rehashes,
            "size": p.size, "status": p.status}


# ---------------------------------------------------------------------------------------------------------------- state stack
def _stack_lines() -> list[str]:
    from .event_engine import StateStack
    g = np.random.Generator(np.random.PCG64(20261027))
    P = g.normal(0, 1, (STACK_PUSH, STACK_D)).astype(np.float32)
    q = g.normal(0, 1, STACK_D).astype(np.float32)
    f32 = lambda a: " ".join(f"{float(x):.9g}" for x in a)  # 9 significant digits round-trip a float32 exactly
    st = StateStack(STACK_S, STACK_D, backend="cpu")
    lines = [f"S,{STACK_S}", f"D,{STACK_D}", f"n_push,{STACK_PUSH}", "checks," + " ".join(str(c) for c in STACK_CHECKS), f"q,{f32(q)}"]
    lines += [f"p{i},{f32(P[i])}" for i in range(STACK_PUSH)]
    for i in range(STACK_PUSH):
        st.push(P[i])
        if i + 1 in STACK_CHECKS:
            lines += [f"c{i + 1}_raw," + " ".join(_f(x) for x in st.corr(q, False)), f"c{i + 1}_l2," + " ".join(_f(x) for x in st.corr(q, True)),
                      f"c{i + 1}_valid," + " ".join(str(int(v)) for v in st.snapshot()[1])]
    return lines


# ---------------------------------------------------------------------------------------------------------------- export
def export(out: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    b = _fixture_bars()
    f = _f
    (out / "mm_fixture_bars.csv").write_text("t,o,h,l,c,tv\n" + "\n".join(",".join([str(int(b.t[i]))] + [f(v[i]) for v in (b.o, b.h, b.l, b.c, b.tv)])
                                                                         for i in range(len(b))) + "\n", encoding="ascii")
    k, rows = K.run(b.t, b.c, K.CrossConfig())
    ev = {e["bar_time"]: e["direction"] for e in k.events}
    (out / "mm_ref_kalman.csv").write_text("t,fast,slow,K_fast,K_slow,P_fast,P_slow,event\n" + "\n".join(
        f"{int(r['bar_time'])},{f(r['fast'])},{f(r['slow'])},{f(r['K_fast'] if r['K_fast'] is not None else math.nan)},"
        f"{f(r['K_slow'] if r['K_slow'] is not None else math.nan)},{f(r['P_fast'])},{f(r['P_slow'])},{ev.get(r['bar_time'], '')}" for r in rows) + "\n",
        encoding="ascii")
    (out / "mm_ref_gpr.csv").write_text("\n".join(_gpr_lines(b.c, G.GPRConfig(window=60, horizon=3, auto_tune=False, ell=4.0, signal_var=0.1,
                                                                             noise_var=0.5), GPR_PROBES, False)) + "\n", encoding="ascii")
    # 1.46 arch (I0490): the grid search the indicator runs by default (InpAutoTune=true) - same default grid as GPRConfig
    (out / "mm_ref_gpr_tune.csv").write_text("\n".join(_gpr_lines(b.c, G.GPRConfig(window=60, horizon=3, auto_tune=True), GPR_TUNE_PROBES, True))
                                             + "\n", encoding="ascii")
    sp = H.Space(256, seed=7)
    a, bb, c = sp.random(1), sp.random(2), sp.random(3)
    (out / "mm_ref_hdc.csv").write_text("\n".join([f"D,{sp.D}", f"a,{_hexw(a)}", f"b,{_hexw(bb)}", f"c,{_hexw(c)}", f"tie,{_hexw(sp.tie)}",
                                                   f"hamming_ab,{sp.hamming(a, bb)}", f"bind_ab,{_hexw(sp.bind(a, bb))}", f"perm_a_77,{_hexw(sp.permute(a, 77))}",
                                                   f"bundle_abc,{_hexw(sp.bundle([a, bb, c]))}", f"bundle_ab_tie,{_hexw(sp.bundle([a, bb]))}"]) + "\n",
                                        encoding="ascii")
    (out / "mm_ref_hdc_acc.csv").write_text("\n".join(_hdc_acc_lines()) + "\n", encoding="ascii")          # 1.46 arch (I0505)
    n_events = {}
    for mode in BZ.FILTERS:                                                # 1.46 arch (I0497): every confirmation mode, not only NONE
        e = BZ.run(b, BZ.BreakoutConfig(confirmation=mode), 0.01, 300)
        txt = "bar_ts,direction,zone_lower,zone_upper\n" + "\n".join(
            f"{int(x['bar_ts'])},{x['direction']},{f(x['zone_lower'])},{f(x['zone_upper'])}" for x in e.events) + "\n"
        (out / f"mm_ref_breakout_{mode}.csv").write_text(txt, encoding="ascii")
        if mode == "NONE":
            (out / "mm_ref_breakout.csv").write_text(txt, encoding="ascii")
        n_events[mode] = len(e.events)
    reads = _tick_reads(_fixture_ticks())                                  # 1.46 arch (I0511): TSVP core
    (out / "mm_fixture_ticks.csv").write_text("read,read_until,time_msc,bid,ask,last,volume,volume_real,flags\n" + "\n".join(
        f"{i},{until},{t['time_msc']},{f(t['bid'])},{f(t['ask'])},{f(t['last'])},{t['volume']},{f(t['volume_real'])},{t['flags']}"
        for i, (until, ticks) in enumerate(reads) for t in ticks) + "\n", encoding="ascii")
    lines = [f"start_ms,{TSVP_START_MS}", f"end_ms,{TSVP_END_MS}", f"tick,{f(TSVP_TICK)}", f"n_reads,{len(reads)}", "configs," + " ".join(TSVP_CONFIGS)]
    for name, (src, bmode, bt, am, atr, anyq) in TSVP_CONFIGS.items():
        lines += [f"{name}_source,{src}", f"{name}_bucket_mode,{bmode}", f"{name}_bucket_ticks,{bt}", f"{name}_atr_mult,{f(am)}", f"{name}_atr,{f(atr)}",
                  f"{name}_any_quote,{anyq}", f"{name}_expected," + json.dumps(_tsvp_expected(name, reads), separators=(",", ":"))]
    (out / "mm_ref_tsvp.csv").write_text("\n".join(lines) + "\n", encoding="ascii")
    (out / "mm_ref_stack.csv").write_text("\n".join(_stack_lines()) + "\n", encoding="ascii")            # 1.46 arch (I0508)
    return {"files": sorted(p.name for p in out.iterdir()), "bars": len(b), "kalman_events": len(k.events), "breakout_events": n_events["NONE"],
            "breakout_events_by_mode": n_events, "tsvp_reads": len(reads),
            "note": "dane syntetyczne do porównania implementacji natywnej z referencją Python"}


# ---------------------------------------------------------------------------------------------------------------- reading
def _rows(p: Path) -> list[list[str]]:
    return [ln.split(",") for ln in p.read_text(encoding="ascii").splitlines()[1:] if ln]


def _kv(p: Path) -> dict:
    out = {}
    for ln in p.read_text(encoding="ascii").splitlines():
        if ln:
            k, _, v = ln.partition(",")
            out[k] = v
    return out


def _num(x) -> float:
    return math.nan if x in (None, "", "nan", "null") else float(x)


def _hexnorm(s) -> str | None:
    return " ".join(s.lower().split()) if isinstance(s, str) else None


def expected_native(ref_dir: Path) -> dict:
    """The PMW_MM_NATIVE.txt JSON a perfect native port writes on this fixture (format contract of PMW_MM_SelfTest.mq5; used by the
    tests). The terminal has no OpenCL GPU here, so the 'opencl' state stack run falls back to the CPU backend."""
    ref_dir = Path(ref_dir)
    fl = lambda x: None if x == "nan" else float(x)
    rk, rg, rt = (_rows(ref_dir / n) for n in ("mm_ref_kalman.csv", "mm_ref_gpr.csv", "mm_ref_gpr_tune.csv"))
    ev = lambda rows: [[int(r[0]), r[1], float(r[2]), float(r[3])] for r in rows]
    h = _kv(ref_dir / "mm_ref_hdc.csv")
    a = _kv(ref_dir / "mm_ref_hdc_acc.csv")
    nq = int(a["n_queries"])
    ts = _kv(ref_dir / "mm_ref_tsvp.csv")
    s = _kv(ref_dir / "mm_ref_stack.csv")
    checks = [int(x) for x in s["checks"].split(" ")]
    sf = lambda key: [float(x) for x in s[key].split(" ")]
    return {"version": "PMW-MM-NATIVE-1", "bars": len(rk),
            "kalman": [[int(r[0])] + [fl(x) for x in r[1:7]] + [r[7]] for r in rk], "gpr": [[int(r[0])] + [fl(x) for x in r[1:]] for r in rg],
            "gpr_tune": [[int(r[0])] + [fl(x) for x in r[1:]] for r in rt],
            "hdc": {"parsed": True, "hamming": True, "bind": True, "permute": True, "bundle3": True, "bundle2_tie": True, "all_pass": True,
                    "hamming_ab": int(h["hamming_ab"]), **{k: h[k] for k in ("bind_ab", "perm_a_77", "bundle_abc", "bundle_ab_tie")}},
            "hdc_acc": {"parsed": True, "updates": int(a["n_updates"]), "protos": [a[f"proto{k}"] for k in range(int(a["C"]))],
                        "queries": [[int(a[f"q{j}_pred"]), float(a[f"q{j}_margin"])] + [float(x) for x in a[f"q{j}_sims"].split(" ")] for j in range(nq)]},
            "breakout": ev(_rows(ref_dir / "mm_ref_breakout.csv")),
            "breakout_modes": {m: ev(_rows(ref_dir / f"mm_ref_breakout_{m}.csv")) for m in BZ.FILTERS},
            "tsvp": {name: json.loads(ts[f"{name}_expected"]) for name in ts["configs"].split(" ")},
            "stack": {k: {"backend": "CPU", "checks": [[n, sf(f"c{n}_raw"), sf(f"c{n}_l2"), [int(x) for x in s[f"c{n}_valid"].split(" ")]] for n in checks]}
                      for k in ("cpu", "opencl")},
            "terminal": {"build": None, "opencl": False}}


# ---------------------------------------------------------------------------------------------------------------- parity
def _maxdiff(ref_rows, nat_rows, cols, rel: bool = False):
    """Largest |ref - native| over the columns (relative to max(1, |ref|) with rel); None = missing / other row count; inf = NaN on one side."""
    if not nat_rows or not isinstance(nat_rows, list) or len(ref_rows) != len(nat_rows):
        return None
    d = 0.0
    try:
        for r, n in zip(ref_rows, nat_rows):
            for c in cols:
                a, b = _num(r[c]), _num(n[c])
                if math.isnan(a) and math.isnan(b):
                    continue
                if math.isnan(a) or math.isnan(b):
                    return math.inf
                d = max(d, abs(a - b) / (max(1.0, abs(a)) if rel else 1.0))
    except (IndexError, TypeError, ValueError):
        return None
    return d


def _close(ref, nat, tol: float) -> bool:
    try:
        a, b = float(ref), float(nat)
    except (TypeError, ValueError):
        return False
    return math.isfinite(b) and abs(a - b) <= tol * max(1.0, abs(a))


def _events_equal(rb, nb, tol: float) -> bool:
    try:
        return (isinstance(nb, list) and len(rb) == len(nb) and all(int(r[0]) == int(n[0]) and r[1] == n[1] for r, n in zip(rb, nb))
                and (_maxdiff(rb, nb, (2, 3)) or 0.0) <= tol)
    except (IndexError, TypeError, ValueError):
        return False


def _gpr_tune_gate(rt, nt, tol: float) -> bool:
    if not isinstance(nt, list) or len(nt) != len(rt):
        return False
    try:
        hp_same = all(int(r[0]) == int(n[0]) and all(_num(r[c]) == _num(n[c]) for c in (1, 2, 3)) for r, n in zip(rt, nt))
    except (IndexError, TypeError, ValueError):
        return False
    m, v, ll = _maxdiff(rt, nt, (4,)), _maxdiff(rt, nt, (5, 6)), _maxdiff(rt, nt, (7,), rel=True)
    return hp_same and None not in (m, v, ll) and m <= tol and v <= tol and ll <= tol


def _hdc_acc_gate(a: dict, na, tol: float) -> bool:
    if not isinstance(na, dict):
        return False
    protos = [a[f"proto{k}"] for k in range(int(a["C"]))]
    nq = na.get("queries")
    if [_hexnorm(x) for x in (na.get("protos") or [])] != protos or not isinstance(nq, list) or len(nq) != int(a["n_queries"]):
        return False
    for j, q in enumerate(nq):
        sims = a[f"q{j}_sims"].split(" ")
        if not isinstance(q, list) or len(q) != 2 + len(sims):
            return False
        try:
            if int(q[0]) != int(a[f"q{j}_pred"]):
                return False
        except (TypeError, ValueError):
            return False
        if not (_close(a[f"q{j}_margin"], q[1], tol) and all(_close(s, x, tol) for s, x in zip(sims, q[2:]))):
            return False
    return True


def _tsvp_checks(exp: dict, nc, tol: float) -> dict:
    if not isinstance(nc, dict):
        return {"section": False}
    nb = nc.get("buckets") if isinstance(nc.get("buckets"), list) else []
    eb = exp["buckets"]
    try:
        buckets = len(nb) == len(eb) and all(int(n[0]) == e[0] and int(n[2]) == e[2] and _close(e[1], n[1], tol) for e, n in zip(eb, nb))
        reads = [[int(r[0]), str(r[1]), int(r[2]), str(r[3])] for r in (nc.get("reads") or [])] == exp["reads"]
    except (IndexError, TypeError, ValueError):
        buckets = reads = False
    return {"reads": reads, "buckets": buckets, "poc": nc.get("poc") == exp["poc"], "counted": nc.get("counted") == exp["counted"],
            "ignored": nc.get("ignored") == exp["ignored"], "rehashes": nc.get("rehashes") == exp["rehashes"], "status": nc.get("status") == exp["status"],
            "max": _close(exp["max"], nc.get("max"), tol), "total": _close(exp["total"], nc.get("total"), tol), "size": _close(exp["size"], nc.get("size"), tol)}


def _stack_gate(s: dict, ns, with_valid: bool) -> bool:
    if not isinstance(ns, dict) or not isinstance(ns.get("checks"), list):
        return False
    checks = [int(x) for x in s["checks"].split(" ")]
    if len(ns["checks"]) != len(checks):
        return False
    for n, c in zip(checks, ns["checks"]):
        try:
            if int(c[0]) != n:
                return False
            for idx, key in ((1, "raw"), (2, "l2")):
                ref = s[f"c{n}_{key}"].split(" ")
                if len(c[idx]) != len(ref) or not all(_close(r, x, STACK_TOL) for r, x in zip(ref, c[idx])):
                    return False
            if with_valid and [int(x) for x in c[3]] != [int(x) for x in s[f"c{n}_valid"].split(" ")]:
                return False
        except (IndexError, TypeError, ValueError):
            return False
    return True


def parity(native_file: Path, ref_dir: Path, tol: float = 1e-9) -> dict:
    """Compare PMW_MM_NATIVE.txt (JSON written by PMW_MM_SelfTest.mq5) with the references: kalman rows [t,fast,slow,K_fast,K_slow,P_fast,
    P_slow,event], gpr / gpr_tune rows [T,ell,sv,nv,mean,latent,observed,lml], hdc raw words, hdc_acc prototypes + queries, breakout events
    [bar_ts,direction,lower,upper] per confirmation mode, tsvp per configuration, state stack (CPU; OpenCL only when the terminal ran it).
    A missing section is a FAIL. Status NATIVE_NOT_EXECUTED until the file exists (the script must run inside MT5)."""
    p = Path(native_file)
    if not p.exists():
        return {"status": "NATIVE_NOT_EXECUTED", "reason": f"brak {p.name} - uruchom PMW_MM_SelfTest.mq5 w terminalu MT5"}
    try:
        nat = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as e:
        return {"status": "NATIVE_OUTPUT_INVALID", "reason": str(e)[:200]}
    if not isinstance(nat, dict):
        return {"status": "NATIVE_OUTPUT_INVALID", "reason": "PMW_MM_NATIVE.txt nie jest obiektem JSON"}
    ref_dir = Path(ref_dir)
    missing = [f for f in REF_FILES if not (ref_dir / f).exists()]
    if missing:
        return {"status": "REFERENCE_INCOMPLETE", "missing": missing,
                "reason": "katalog referencji z innej wersji - uruchom ponownie `mm export-fixtures --out <dir>` i PMW_MM_SelfTest.mq5"}
    out: dict = {}
    gates: dict = {}
    rk = _rows(ref_dir / "mm_ref_kalman.csv")
    nk = nat.get("kalman") or []
    out["kalman_rows"] = [len(rk), len(nk) if isinstance(nk, list) else None]
    out["kalman_max_abs_diff"] = _maxdiff(rk, nk, (1, 2, 5, 6))
    try:
        out["kalman_events_equal"] = bool(nk) and [r[7] for r in rk] == [str(n[7]) for n in nk]
    except (IndexError, TypeError):
        out["kalman_events_equal"] = False
    gates["kalman"] = out["kalman_max_abs_diff"] is not None and out["kalman_max_abs_diff"] <= tol and out["kalman_events_equal"]
    rg = _rows(ref_dir / "mm_ref_gpr.csv")
    ng = nat.get("gpr") or []
    out["gpr_max_abs_mean_diff"] = _maxdiff(rg, ng, (4,))
    out["gpr_max_abs_var_diff"] = _maxdiff(rg, ng, (5, 6))
    out["gpr_max_abs_lml_diff"] = _maxdiff(rg, ng, (7,))
    out["gpr_max_rel_lml_diff"] = _maxdiff(rg, ng, (7,), rel=True)
    # 1.46 arch (I0490): the LML enters the gate (relative to max(1, |LML|)), and the grid search has its own gate
    gates["gpr"] = all(out[k] is not None and out[k] <= tol for k in ("gpr_max_abs_mean_diff", "gpr_max_abs_var_diff", "gpr_max_rel_lml_diff"))
    gates["gpr_tune"] = _gpr_tune_gate(_rows(ref_dir / "mm_ref_gpr_tune.csv"), nat.get("gpr_tune"), tol)
    # 1.46 arch (I0506): the words are compared here - the script's own all_pass is informational only
    h, nh = _kv(ref_dir / "mm_ref_hdc.csv"), nat.get("hdc") if isinstance(nat.get("hdc"), dict) else {}
    out["hdc_checks"] = {"hamming_ab": isinstance(nh.get("hamming_ab"), int) and nh.get("hamming_ab") == int(h["hamming_ab"]),
                         **{k: _hexnorm(nh.get(k)) == h[k] for k in ("bind_ab", "perm_a_77", "bundle_abc", "bundle_ab_tie")}}
    out["hdc_native_self_check"] = nh.get("all_pass")
    gates["hdc"] = all(out["hdc_checks"].values())
    gates["hdc_acc"] = _hdc_acc_gate(_kv(ref_dir / "mm_ref_hdc_acc.csv"), nat.get("hdc_acc"), tol)      # 1.46 arch (I0505)
    rb = _rows(ref_dir / "mm_ref_breakout.csv")
    nb = nat.get("breakout")
    out["breakout_events"] = [len(rb), len(nb) if isinstance(nb, list) else None]
    out["breakout_equal"] = _events_equal(rb, nb, tol)
    gates["breakout"] = out["breakout_equal"]
    nm = nat.get("breakout_modes") if isinstance(nat.get("breakout_modes"), dict) else {}
    for m in BZ.FILTERS:                                                     # 1.46 arch (I0497): every confirmation mode
        gates[f"breakout_{m}"] = _events_equal(_rows(ref_dir / f"mm_ref_breakout_{m}.csv"), nm.get(m), tol)
    ts = _kv(ref_dir / "mm_ref_tsvp.csv")                                    # 1.46 arch (I0511)
    nts = nat.get("tsvp") if isinstance(nat.get("tsvp"), dict) else {}
    out["tsvp_checks"] = {name: _tsvp_checks(json.loads(ts[f"{name}_expected"]), nts.get(name), tol) for name in ts["configs"].split(" ")}
    gates["tsvp"] = all(all(c.values()) for c in out["tsvp_checks"].values())
    s = _kv(ref_dir / "mm_ref_stack.csv")                                    # 1.46 arch (I0508)
    ns = nat.get("stack") if isinstance(nat.get("stack"), dict) else {}
    gates["stack"] = _stack_gate(s, ns.get("cpu"), True)
    oc = ns.get("opencl") if isinstance(ns.get("opencl"), dict) else None
    if oc is not None and oc.get("backend") == "OPENCL":
        gates["stack_opencl"] = _stack_gate(s, oc, False)
    else:
        out["stack_opencl"] = f"NOT_AVAILABLE (backend {oc.get('backend') if oc else None}) - OpenCL GPU w terminalu nie był użyty"
    out["gates"] = gates
    out["tolerance"] = tol
    out["terminal"] = nat.get("terminal")
    out["status"] = "NATIVE_PARITY_PASS" if all(gates.values()) else "NATIVE_PARITY_FAIL"
    return out
