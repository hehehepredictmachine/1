"""Fixture zgodności: silnik bota svp/engine.py liczy profile sesji na deterministycznych świecach; wynik zapisuje do JSON.
Uruchom z głównego folderu bota:  python update_charts/narzedzia/svp_zgodnosc/make_fixture.py  (tworzy fixture_svp.json obok skryptu)."""
import json, random, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "backend"))
from masterquo.svp import engine as EN
END = datetime(2026, 11, 17, 15, tzinfo=timezone.utc).timestamp()
TF_S = {"M1": 60, "M5": 300, "M15": 900}
rnd = random.Random(4101); p = 4012.4; m1 = []
t0 = END - 4 * 86400
for i in range(4 * 1440):
    t = t0 + i * 60; o = p; c = o; hi = lo = o
    for _ in range(4):
        c += (rnd.random() - .5) * .62; hi = max(hi, c); lo = min(lo, c)
    hi += rnd.random() * .2; lo -= rnd.random() * .2
    q = lambda x: round(round(x / .01) * .01, 2)
    m1.append({"t": t, "o": q(o), "h": q(hi), "l": q(lo), "c": q(c), "v": 40 + int(rnd.random() * 160)}); p = c
def agg(k):
    out = []
    for b in m1:
        s = b["t"] - b["t"] % (k * 60)
        if not out or out[-1]["t"] != s: out.append(dict(b, t=s))
        else:
            x = out[-1]; x["h"] = max(x["h"], b["h"]); x["l"] = min(x["l"], b["l"]); x["c"] = b["c"]; x["v"] += b["v"]
    return out
iso = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")
cases = []
for tf, bt in (("M1", 20), ("M5", 50), ("M15", 100)):
    bars = m1 if tf == "M1" else agg(TF_S[tf] // 60)
    B = [{"open_utc": iso(b["t"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "tv": b["v"], "closed": True} for b in bars]
    for d in range(3):
        day = (datetime.fromtimestamp(END, tz=timezone.utc) - timedelta(days=d)).date().isoformat()
        for sess in ("ASIA", "LONDON", "NEW_YORK"):
            a, b = EN.session_window("LAB_XAU_REFERENCE_V1", sess, day)
            r = EN.compute(B, tf, a, b, as_of=END, tick=0.01, bin_ticks=bt, value_area_pct=0.70, instrument="XAUUSD", mode="SESSION")
            cases.append({"tf": tf, "bin_ticks": bt, "session": sess, "local_date": day, "start": a * 1000, "end": b * 1000,
                          "expect": {k: r.get(k) for k in ("status", "poc", "vah", "val", "hvn", "lvn", "bars")}})
    cases[-1]["_bars_key"] = tf
json.dump({"as_of": END * 1000, "bars": {tf: [dict(b, t=b["t"] * 1000) for b in (m1 if tf == "M1" else agg(TF_S[tf] // 60))] for tf in TF_S}, "cases": cases},
          open(Path(__file__).with_name("fixture_svp.json"), "w"))
print("przypadki:", len(cases))
