"""MT5 M1 CSV exports -> M5.json / M15.json / H1.json for the research evaluation (research only).

  python prep.py --csv m1_2025.csv m1_202601.csv --out <folder>
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def read_rows(files):
    rows = []
    for fn in files:
        with open(fn, encoding="utf-8") as f:
            for r in csv.reader(f):
                t = datetime.strptime(r[0] + " " + r[1], "%Y.%m.%d %H:%M")
                rows.append((t, float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    rows.sort()
    return rows


def agg(rows, mins):
    out, cur = [], None
    for t, o, h, low, c in rows:
        k = t.replace(minute=(t.minute // mins) * mins) if mins < 60 else t.replace(minute=0)
        if cur and cur[0] == k:
            cur[2] = max(cur[2], h)
            cur[3] = min(cur[3], low)
            cur[4] = c
        else:
            if cur:
                out.append(cur)
            cur = [k, o, h, low, c]
    out.append(cur)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", nargs="+", default=["m1_2025.csv", "m1_202601.csv"], help="eksporty M1 z MT5 (data, czas, O, H, L, C)")
    ap.add_argument("--out", default=".", help="folder wynikowy (M5.json, M15.json, H1.json)")
    a = ap.parse_args(argv)
    rows = read_rows(a.csv)
    dest = Path(a.out)
    dest.mkdir(parents=True, exist_ok=True)
    for name, m in (("M5", 5), ("M15", 15), ("H1", 60)):
        b = agg(rows, m)
        with open(dest / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump([[x[0].isoformat(), x[1], x[2], x[3], x[4]] for x in b], f)
        print(name, len(b), b[0][0], b[-1][0])


if __name__ == "__main__":
    main()
