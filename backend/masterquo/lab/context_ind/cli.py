"""python -m masterquo context-indicators ... (PMW-UPD-14 section 12). Offline commands never open MT5 and never trade.
  audit            data origin / completeness / gaps of the latest M5 export (or --dataset)
  calibrate        deterministic VAMD / FD / SMC calibration on DEV only (<= 24 pre-declared configs, all trials in the ledger)
  replay           run the engines causally over DEV and report coverage, events, zones and SHADOW would_block shares
  dataset / train  FS_VS_CONTEXT_v1 / CONTEXT_MOVE_M5_V1 (ablation core -> +VAMD -> +FD -> +SMC); synthetic only with --allow-synthetic-fixture
  buffers-verify   import a PWM_BufferInspector report and print hypotheses + mapping validation
  export-fixture   write frozen OHLC CSV + golden.json for the native self-test (PWM_ContextSelfTest)
  native-parity    compare a native export with the Python cores (status axes separate)"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

INSTR = ("XAUUSD", "BTC")
FIX = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "context_ind"


def _print(x) -> None:
    print(json.dumps(x, indent=1, ensure_ascii=False, default=str))


def _raw(asset: str, path: str | None, allow_syn: bool):
    from ...extind.cli import _latest_real
    ds = Path(path) if path else _latest_real(asset)
    if ds is None or not (ds / "source_metadata.json").exists():
        return None, None, "BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA – podaj --dataset"
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("data_kind") != "REAL_USER_DATA" and not allow_syn:
        return None, None, f"BLOCKED_SYNTHETIC: {meta.get('data_kind')} – tylko z --allow-synthetic-fixture (TEST_ONLY)"
    return ds, meta, None


def audit(ds: Path, meta: dict) -> dict:
    from ...extind.trainer import _bars
    from .task import _ts
    m5 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M5")
    t = [_ts(b["open_utc"]) for b in m5]
    gaps = [(t[i - 1], t[i]) for i in range(1, len(t)) if t[i] - t[i - 1] != 300]
    big = [g for g in gaps if g[1] - g[0] > 3 * 3600]
    return {"dataset": str(ds), "data_kind": meta.get("data_kind"), "tick_size": meta.get("tick_size"), "bars_m5": len(m5),
            "from": m5[0]["open_utc"] if m5 else None, "to": m5[-1]["open_utc"] if m5 else None, "gaps": len(gaps), "gaps_over_3h": len(big),
            "clock_basis": meta.get("clock_basis", "UNKNOWN"), "costs": meta.get("costs") or "UNKNOWN (bez kosztów nie ma netto edge)",
            "status": "OK" if m5 else "NO_M5"}


def replay(bars: list[dict], tick: float, prof: dict) -> dict:
    from .service import ContextSections
    from . import smc as SM
    from .task import _ts
    from . import fractal as FD
    from . import vamd as VM
    zones, wb, ready = {}, {"BUY": 0, "SELL": 0}, 0
    for r in FD.series(bars, prof.get("fd")):
        zones[r.get("zone") or "WARMUP"] = zones.get(r.get("zone") or "WARMUP", 0) + 1
    vs = VM.series(bars, prof.get("vamd"))
    fs = FD.series(bars, prof.get("fd"))
    s = SM.SMC(tick=tick, **(prof.get("smc") or {}))
    for b, v, f in zip(bars, vs, fs):
        sr = s.update(b, _ts(b["open_utc"]) + 300)
        if v.get("status") == "READY" and f.get("zone"):
            ready += 1
            w = ContextSections.would_block({"vamd": v, "fd": f, "smc": {"trend": sr["trend"]}})
            for side in wb:
                wb[side] += w[side]["status"] == "WOULD_BLOCK"
    kinds = {}
    for e in s.events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    return {"bars": len(bars), "fd_zones": zones, "smc_events": kinds, "pullback_swings": len(s.pb.ledger), "state_hash": s.state_hash(),
            "would_block_share": {k: (v / ready if ready else None) for k, v in wb.items()}, "ready_bars": ready,
            "note": "replay opisowy (SHADOW); bez kosztów i triggera nie jest wynikiem ekonomicznym"}


def main(argv: list[str]) -> int:
    from . import buffers as BF
    from . import native as NV
    from . import task as CT
    ap = argparse.ArgumentParser(prog="masterquo context-indicators", description="VAMD / bounded Katz FD / Pullback+SMC / Buffer Inspector")
    sub = ap.add_subparsers(dest="c", required=True)

    def common(s):
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        s.add_argument("--dataset")
        s.add_argument("--allow-synthetic-fixture", action="store_true")
    for name in ("audit", "calibrate", "replay", "dataset"):
        common(sub.add_parser(name))
    s = sub.add_parser("train")
    common(s)
    s.add_argument("--families", default="LOGREG,XGB")
    s.add_argument("--profile", choices=("standard", "quick"), default="standard")
    s = sub.add_parser("buffers-verify")
    s.add_argument("--report", required=True)
    s.add_argument("--mapping")
    s = sub.add_parser("export-fixture")
    s.add_argument("--out", default=str(FIX))
    s.add_argument("--files-dir")
    s = sub.add_parser("native-parity")
    s.add_argument("--fixtures", default=str(FIX))
    s.add_argument("--native-status-file")
    s.add_argument("--export", help="MQL5/Files/PMW/PWM_CONTEXT_EXPORT.txt z PWM_ContextSelfTest")
    a = ap.parse_args(argv)

    if a.c in ("audit", "calibrate", "replay", "dataset", "train"):
        ds, meta, err = _raw(a.asset, a.dataset, a.allow_synthetic_fixture)
        if err:
            print(err)
            return 2
        from ...extind.trainer import _bars
        if a.c == "audit":
            _print(audit(ds, meta))
            return 0
        m5 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M5")
        tick = float(meta["tick_size"])
        if a.c == "calibrate":
            r = CT.calibrate(a.asset, m5, tick, meta)
            _print({"chosen": r["chosen"], "grid_size": r["grid_size"], "holdout_read": r["holdout_read"], "profile_hash": r["profile"]["hash"]})
        elif a.c == "replay":
            _print(replay(m5[: int(0.8 * len(m5))], tick, CT.profile(a.asset)))
        elif a.c == "dataset":
            _print(CT.build_dataset(a.asset, ds))
        else:
            d = CT.latest(a.asset)
            if d is None:
                print("BLOCKED_NO_DATASET: najpierw `context-indicators dataset`")
                return 2
            r = CT.train(a.asset, d, tuple(a.families.split(",")), a.profile)
            _print({k: r.get(k) for k in ("run_id", "status", "role", "candidates", "edge_status", "reason", "run_dir")})
        return 0
    if a.c == "buffers-verify":
        try:
            d = BF.import_report(Path(a.report).read_bytes())
        except (OSError, ValueError) as exc:
            print(f"REJECTED: {exc}")
            return 2
        out = {"report_id": d["report_id"], "coverage": d["coverage"], "capability": d.get("capability"),
               "buffers": [{"instance": i.get("short_name"), "ambiguous": i["ambiguous"], "index": b.get("index"), "status": b.get("status"),
                            "hypothesis": (b.get("hypothesis") or {}).get("type")} for i in d.get("instances") or [] for b in i.get("buffers") or []]}
        if a.mapping:
            out["mapping"] = BF.validate_mapping(json.loads(Path(a.mapping).read_text(encoding="utf-8")))
        _print(out)
        return 0
    if a.c == "export-fixture":
        g = NV.make_golden(Path(a.out) / "golden.json")
        if a.files_dir:
            p = Path(a.files_dir) / "PMW" / "ctx_fixture_bars.csv"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("time,open,high,low,close\n" + "".join(f"{int(b['open_utc'])},{b['o']},{b['h']},{b['l']},{b['c']}\n" for b in g["bars"]),
                         encoding="utf-8")
        _print({"golden": str(Path(a.out) / "golden.json"), "bars": len(g["bars"])})
        return 0
    if a.c == "native-parity":
        files = __import__("os").environ.get("MQ_MT5_FILES_DIR")
        exp = Path(a.export) if a.export else (Path(files) / "PMW" / "PWM_CONTEXT_EXPORT.txt" if files else None)
        st = Path(a.native_status_file) if a.native_status_file else (Path(files) / "PMW" / "ctx_native_status.json" if files else None)
        _print(NV.parity(Path(a.fixtures), st, exp if exp and exp.exists() else None))
        return 0
    return 1
