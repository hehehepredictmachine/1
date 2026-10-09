"""Chronological validation with purging, embargo and grouping (MQ-VALIDATION-1.0.0).

Blocks in time order:  FIT (50%) | TUNE (15%, early stopping / model choice) | CALIBRATION (15%) | TEST (20%, final)
* all samples of one market event (event_id) - and therefore all versions of one setup - go to ONE block
  (the block of the event's first sample); correlated signals are never split between train and test;
* PURGING: a sample of an earlier block whose label window ends after (next block start - embargo) is removed;
  the actual label_end_utc is used, not the row number (labels have different lengths, events are irregular);
* the final TEST block must start after the end of every previously used test block (a used test becomes history);
* each block needs `min_block_samples` and `min_block_per_class` of BOTH classes - otherwise NOT_READY with the exact gap.
Rows are never shuffled. Hyper-parameters are chosen on walk-forward folds inside FIT+TUNE only; calibration and the
trading threshold are fitted on CALIBRATION; TEST is evaluated once.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

VERSION = "MQ-VALIDATION-1.0.0"
FRACTIONS = (0.50, 0.15, 0.15, 0.20)
BLOCKS = ("fit", "tune", "calib", "test")


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def split(rows: list[dict], *, embargo_minutes: int, min_block: int, min_class: int, test_after: str | None = None) -> tuple[dict | None, list[str]]:
    rows = sorted(rows, key=lambda r: (r["asof_utc"], r["sample_id"]))
    if not rows:
        return None, ["NO_LABELED_SAMPLES"]
    # event grouping: an event goes where its first sample lands
    first_of_event: dict[str, int] = {}
    for i, r in enumerate(rows):
        first_of_event.setdefault(r.get("event_id") or r["group_id"], i)
    n = len(rows)
    bounds, acc = [], 0.0
    for f in FRACTIONS[:-1]:
        acc += f
        bounds.append(int(round(acc * n)))
    if test_after:
        # the test block may only contain samples after the previously used test window
        k = next((i for i, r in enumerate(rows) if r["asof_utc"] > test_after), n)
        bounds[-1] = max(bounds[-1], k)
    blocks = {b: [] for b in BLOCKS}
    for i, r in enumerate(rows):
        j = first_of_event[r.get("event_id") or r["group_id"]]
        bi = sum(1 for b in bounds if j >= b)
        blocks[BLOCKS[bi]].append(r)
    emb = timedelta(minutes=embargo_minutes)
    purged = {}
    for a, b in zip(BLOCKS[:-1], BLOCKS[1:]):
        if not blocks[b]:
            continue
        start = _t(blocks[b][0]["asof_utc"])
        keep = [r for r in blocks[a] if _t(r["label_end_utc"]) <= start - emb]
        purged[a] = len(blocks[a]) - len(keep)
        blocks[a] = keep
    reasons = []
    for b in BLOCKS:
        ys = [r["label"] for r in blocks[b]]
        pos, neg = sum(ys), len(ys) - sum(ys)
        if len(ys) < min_block:
            reasons.append(f"{b.upper()}_BLOCK_{len(ys)}/{min_block}_SAMPLES")
        if pos < min_class or neg < min_class:
            reasons.append(f"{b.upper()}_BLOCK_CLASSES_POS{pos}_NEG{neg}_NEED_{min_class}_EACH")
    info = {"blocks": blocks, "purged": purged, "counts": {b: len(v) for b, v in blocks.items()},
            "windows": {b: [v[0]["asof_utc"], v[-1]["asof_utc"]] if v else None for b, v in blocks.items()}, "version": VERSION}
    return (None if reasons else info), reasons


def walk_forward(rows: list[dict], k: int, embargo_minutes: int) -> list[tuple[list[dict], list[dict]]]:
    """Expanding-window folds inside the pre-test data, with purging (for hyper-parameter choice)."""
    rows = sorted(rows, key=lambda r: r["asof_utc"])
    n = len(rows)
    folds = []
    emb = timedelta(minutes=embargo_minutes)
    for i in range(1, k + 1):
        cut = int(n * (0.4 + 0.6 * i / (k + 1)))
        end = int(n * (0.4 + 0.6 * (i + 1) / (k + 1))) if i < k else n
        val = rows[cut:end]
        if not val:
            continue
        start = _t(val[0]["asof_utc"])
        val_events = {r.get("event_id") or r["group_id"] for r in val}
        tr = [r for r in rows[:cut] if _t(r["label_end_utc"]) <= start - emb and (r.get("event_id") or r["group_id"]) not in val_events]
        folds.append((tr, val))
    return folds


# ----------------------------------------------------------------------------- metrics
def classification_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, log_loss, precision_score, recall_score
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    out = {"n": int(len(y)), "pos": pos, "neg": neg, "threshold": round(float(threshold), 4)}
    pred = (p >= threshold).astype(int)
    one_class = pos == 0 or neg == 0
    out["precision"] = round(float(precision_score(y, pred, zero_division=0)), 4) if not one_class else "N/A"
    out["recall"] = round(float(recall_score(y, pred, zero_division=0)), 4) if not one_class else "N/A"
    out["confusion"] = confusion_matrix(y, pred, labels=[0, 1]).tolist()
    out["pr_auc"] = round(float(average_precision_score(y, p)), 4) if not one_class else "N/A"
    out["log_loss"] = round(float(log_loss(y, p, labels=[0, 1])), 4) if not one_class else "N/A"
    out["brier"] = round(float(brier_score_loss(y, p)), 4)
    out["calibration"], out["ece"] = calibration_bins(y, p)
    return out


def calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 10) -> tuple[list[dict], float]:
    edges = np.linspace(0, 1, bins + 1)
    out, ece = [], 0.0
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))
        if m.sum() == 0:
            continue
        mp, my = float(p[m].mean()), float(y[m].mean())
        out.append({"bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}", "n": int(m.sum()), "mean_pred": round(mp, 3), "observed": round(my, 3)})
        ece += m.sum() / len(p) * abs(mp - my)
    return out, round(float(ece), 4)


def policy_eval(rows: list[dict], take: np.ndarray) -> dict:
    """Trading policy on a block: take flagged setups in time order, ONE position at a time (no overlapping
    hypothetical trades beyond the available capital). Results in net R (costs already in the labels)."""
    busy_until = None
    rs, t_in = [], 0.0
    order = sorted(range(len(rows)), key=lambda i: rows[i]["asof_utc"])
    span = (_t(rows[order[-1]]["label_end_utc"]) - _t(rows[order[0]]["asof_utc"])).total_seconds() if rows else 0
    for i in order:
        if not take[i]:
            continue
        r = rows[i]
        if busy_until and _t(r["asof_utc"]) < busy_until:
            continue
        rs.append(float(r["outcome_r"]))
        busy_until = _t(r["label_end_utc"])
        t_in += (busy_until - _t(r["asof_utc"])).total_seconds()
    if not rs:
        return {"trades": 0, "net_r": 0.0, "avg_r": "N/A", "max_dd_r": 0.0, "exposure": 0.0}
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(rs), "net_r": round(sum(rs), 3), "avg_r": round(sum(rs) / len(rs), 4), "max_dd_r": round(dd, 3),
            "exposure": round(t_in / span, 3) if span else 0.0, "values": rs}


def block_bootstrap(values: list[float], block: int = 10, reps: int = 1000, seed: int = 42) -> dict:
    """Moving-block bootstrap of the mean (keeps short-range time dependence)."""
    v = np.asarray(values, dtype=float)
    if len(v) < 10:
        return {"mean": "N/A", "ci95": "N/A", "note": "za mało transakcji"}
    rng = np.random.default_rng(seed)
    b = min(block, len(v))
    nb = int(np.ceil(len(v) / b))
    starts = len(v) - b + 1
    means = []
    for _ in range(reps):
        idx = np.concatenate([np.arange(s, s + b) for s in rng.integers(0, starts, nb)])[:len(v)]
        means.append(v[idx].mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": round(float(v.mean()), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)], "block": b, "reps": reps}


def breakdown(rows: list[dict], p: np.ndarray, key) -> dict:
    out = {}
    for i, r in enumerate(rows):
        k = key(r)
        d = out.setdefault(k, {"n": 0, "pos": 0, "p_sum": 0.0, "r_sum": 0.0})
        d["n"] += 1
        d["pos"] += int(r["label"])
        d["p_sum"] += float(p[i])
        d["r_sum"] += float(r["outcome_r"])
    return {k: {"n": d["n"], "win_rate": round(d["pos"] / d["n"], 3), "mean_pred": round(d["p_sum"] / d["n"], 3), "avg_r": round(d["r_sum"] / d["n"], 3),
                "small_sample": d["n"] < 30} for k, d in out.items()}
