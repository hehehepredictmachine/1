"""Hand-built OHLC helpers for deterministic structure fixtures (TEST_ONLY)."""
T0 = 1_700_000_000


def bar(i, h, lo, c=None, o=None, step=60):
    c = (h + lo) / 2 if c is None else c
    return {"open_utc": T0 + step * i, "o": c if o is None else o, "h": float(h), "l": float(lo), "c": float(c)}


def from_closes(cs, spread=0.2, step=60):
    return [bar(i, c + spread, c - spread, c, step=step) for i, c in enumerate(cs)]


def zigzag(points, per_leg=6, spread=0.1):
    cs = []
    for a, b in zip(points, points[1:]):
        cs += [a + (b - a) * k / per_leg for k in range(per_leg)]
    cs.append(points[-1])
    return from_closes(cs, spread)
