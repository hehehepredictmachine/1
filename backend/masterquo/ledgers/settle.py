"""Settlement of one price-path forecast against the REAL closed bars (1.46 arch I0036): Kronos.settle and TSFM.settle were copies of
this algorithm. Byte-identical to both: the outcome dict keeps the key order of each ledger (TSFM adds pinball_h / covered_80 before
direction_hit). A missing target bar is NO_DATA (never interpolated); a forecast whose last input bar left the buffer is OUT_OF_BUFFER."""
from __future__ import annotations

import json


def settle_close_path(r: dict, closes: dict, first_open: str, last_open: str, *, quantiles: bool = False) -> tuple[str, dict] | None:
    """r: a PENDING ledger row (path_json, last_bar_open_utc, neutral_band, last_close, pred_close_h, direction[, quantiles_json]);
    closes: {open_utc: close} of the closed bars. -> None while the last target bar is not closed yet, else (status, outcome)."""
    path = json.loads(r["path_json"])
    if path[-1]["t_utc"] > last_open:
        return None
    if r["last_bar_open_utc"] < first_open:
        return "OUT_OF_BUFFER", {}
    act = [closes.get(x["t_utc"]) for x in path]
    if act[-1] is None:
        return "NO_DATA", {"missing_steps": sum(1 for a in act if a is None)}
    band = r["neutral_band"] or 0.0
    d = act[-1] - r["last_close"]
    dir_act = "UP" if d > band else "DOWN" if d < -band else "FLAT"
    errs = [abs(x["c"] - a) for x, a in zip(path, act) if a is not None]
    out = {"actual_close_h": act[-1], "abs_err_h": abs(r["pred_close_h"] - act[-1]), "naive_abs_err_h": abs(r["last_close"] - act[-1]),
           "path_mae": sum(errs) / len(errs), "steps_with_data": len(errs), "direction_actual": dir_act}
    if quantiles:                                     # TSFM: pinball loss of the model quantiles at H and the 80 % coverage
        qj = json.loads(r["quantiles_json"] or "null") or {}
        qh = (qj.get("path") or [{}])[-1]
        pin = None
        if qh:
            y = act[-1]
            pin = sum(max(float(lv) * (y - v), (float(lv) - 1) * (y - v)) for lv, v in ((k[1:], v) for k, v in qh.items())) / len(qh)
        cov = None
        if "q0.1" in qh and "q0.9" in qh:
            cov = int(qh["q0.1"] <= act[-1] <= qh["q0.9"])
        out.update(pinball_h=pin, covered_80=cov)
    out["direction_hit"] = None if (r["direction"] == "FLAT" or dir_act == "FLAT") else int(r["direction"] == dir_act)
    return "SETTLED", out
