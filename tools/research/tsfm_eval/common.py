"""Shared helpers of the TSFM / Kronos research evaluation (tools/research/tsfm_eval - research only, never in the release packages).

Data: a folder with M5.json / M15.json / H1.json made by prep.py ([[iso time, open, high, low, close], ...]), passed as --data.
Arch 1.46 I0127: no hard-coded paths of a development session (data, weights, output: arguments); the bot's backend is found
relative to this file.
"""
import argparse
import json
import math
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"


def parser(doc: str, weights_help: str | None = None) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=doc)
    ap.add_argument("--data", required=True, help="folder z M5.json / M15.json / H1.json (wynik prep.py)")
    if weights_help:
        ap.add_argument("--weights", required=True, help=weights_help)
    ap.add_argument("--out", help="plik wyników JSON (domyślnie obok skryptu)")
    return ap


def load(data_dir, tf):
    with open(Path(data_dir) / f"{tf}.json", encoding="utf-8") as f:
        b = json.load(f)
    return [x[0] for x in b], [x[1] for x in b], [x[2] for x in b], [x[3] for x in b], [x[4] for x in b]


def save(out, path, default_name):
    p = Path(path) if path else Path(__file__).resolve().parent / default_name
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return p


def atr14(h, l, c, i):
    trs = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(i - 13, i + 1)]
    return sum(trs) / 14


def origins(t, H, start="2025-10-01", ctx=1024, step=None, n=None):
    step = step or H
    idx = [i for i in range(ctx, len(t) - H, step) if t[i] >= start]
    return idx[:n] if n else idx


def score(name, preds, orig, h, l, c, H):
    ae, se, nae, hits, flat = [], [], [], [], 0
    for i, p in zip(orig, preds):
        y = c[i + H]
        last = c[i]
        band = 0.25 * atr14(h, l, c, i)
        ae.append(abs(p - y))
        se.append((p - y) ** 2)
        nae.append(abs(last - y))
        dp, da = p - last, y - last
        pd = "UP" if dp > band else "DOWN" if dp < -band else "FLAT"
        ad = "UP" if da > band else "DOWN" if da < -band else "FLAT"
        if pd == "FLAT":
            flat += 1
        if pd != "FLAT" and ad != "FLAT":
            hits.append(int(pd == ad))

    def m(x):
        return sum(x) / len(x)
    return {"model": name, "n": len(ae), "mae": round(m(ae), 3), "rmse": round(math.sqrt(m(se)), 3), "naive_mae": round(m(nae), 3),
            "skill_vs_naive": round(1 - m(ae) / m(nae), 4), "dir_n": len(hits), "dir_hit": round(m(hits), 3) if hits else None,
            "pred_flat": flat}
