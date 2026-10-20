"""`python -m masterquo structure-intelligence <cmd>` (26_STRUCTURE_INTELLIGENCE.bat) - PMW-UPD-07 R14.
Exit codes: 0 ok, 1 error, 2 blocked (no data / wrong task / stale dataset), 4 insufficient evidence. Never activates a model for
execution, never sends orders; the holdout is opened only by `evaluate-holdout` (once per candidate, logged)."""
from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path

INSTR = ("XAUUSD", "BTC")


def _print(x) -> None:
    print(json.dumps(x, indent=1, ensure_ascii=False, default=str))


def main(argv: list[str]) -> int:
    from . import structure_task as T
    ap = argparse.ArgumentParser(prog="masterquo structure-intelligence",
                                 description="Structure Intelligence: STRUCTURE_MOVE_M1_V1 (h=3/5/15 M1) i SCALP_STRUCTURE_CONTEXT_V1 – dane, kalibracja, trening, raport")
    sub = ap.add_subparsers(dest="c", required=True)
    s = sub.add_parser("audit", help="stan danych, eksportów, datasetów, profilu wskaźników i rejestru")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--symbol")
    s.add_argument("--source", choices=("bridge", "import"), default="bridge")
    s = sub.add_parser("export", help="eksport historii (wykonuje działający runtime/bridge) albo jawny import katalogu")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--symbol")
    s.add_argument("--months", type=int, default=12)
    s.add_argument("--source", choices=("bridge", "import"), default="bridge")
    s.add_argument("--path", help="katalog eksportu (tylko --source import)")
    s = sub.add_parser("dataset", help="zbuduj dataset zadania z najnowszego eksportu REAL_USER_DATA")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--latest", action="store_true")
    s.add_argument("--dataset", help="katalog eksportu (domyślnie najnowszy REAL_USER_DATA)")
    s.add_argument("--task", choices=(T.TASK_MOVE, T.TASK_SETUP), default=T.TASK_MOVE)
    s.add_argument("--commission", type=float)
    s.add_argument("--allow-synthetic-fixture", action="store_true")
    s = sub.add_parser("calibrate-indicators", help="wybór profilu STRUCTURE_CAUSAL_V2 / MITP tylko na części dev")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--latest", action="store_true")
    s.add_argument("--profiles", default="MQ_MITP_32_V1,STRUCTURE_CAUSAL_V2,MQ_REGIME_MULTI_V2,MQ_SMMA_HL3_V2,MQ_ZSCORE_V2")
    s.add_argument("--dataset")
    s = sub.add_parser("train", help="trening rodzin na zamrożonym protokole (holdout nieotwierany)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--latest", action="store_true")
    s.add_argument("--task", choices=(T.TASK_MOVE, T.TASK_SETUP), default=T.TASK_MOVE)
    s.add_argument("--families", default="LOGREG,XGB," + ",".join(T.SN.FAMILIES))
    s.add_argument("--profile", choices=tuple(T.PROFILES), default="standard")
    s.add_argument("--experiment", choices=T.EXPERIMENTS, help="MQ_NEUTRAL_REACTION_V1 / MQ_QUOTE_CONTEXT_REACTION_V1 (LOGREG/XGB)")
    s.add_argument("--sew-operators", help="np. ADD,AND,IAND – warianty rodzin SEW (nowa konfiguracja treningu)")
    s.add_argument("--encoder", choices=("BAR_EVENT_V1", "QUOTE_EVENT_V1"), help="profil wejścia MQ_SPIKE_BRAIN_FINANCE_V1")
    s.add_argument("--attention", choices=("LINEAR", "SLIDING", "HYBRID"), help="tryb uwagi MQ_SPIKE_BRAIN_FINANCE_V1")
    s.add_argument("--transform", help="MQ_MINIROCKET_UNIVARIATE_V2 dla MQ_MINIROCKET_RIDGE_V2")
    s.add_argument("--out")
    s = sub.add_parser("minirocket", help="MiniRocket V2: export-native / export-fixture / parity / native-status")
    s.add_argument("action", choices=("export-native", "export-fixture", "parity", "native-status"))
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--model-id", help="candidate_id MQ_MINIROCKET_RIDGE_V2 (export-native)")
    s.add_argument("--output", default="./exports/minirocket")
    s.add_argument("--fixtures", default=str(Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "minirocket"))
    s.add_argument("--reference-version", help="przypięta wersja referencji (np. sktime==1.2.0) – zapisywana w raporcie")
    s.add_argument("--reference-python", help="interpreter z przypiętym sktime (uruchomienie referencji na żywo)")
    s.add_argument("--native-scores", help="mr2_infer_scores.csv z terminala (HEAD_PARITY)")
    s.add_argument("--native-status-file", help="native_status.json z 27_MINIROCKET_NATIVE.bat")
    s = sub.add_parser("benchmark", help="pomiar CPU rodzin (Python); native mierzy skrypt MQL5 w terminalu")
    s.add_argument("--families", default="MQ_SPIKE_BRAIN_FINANCE_V1,MQ_MINIROCKET_RIDGE_V2")
    s.add_argument("--profile", choices=("cpu",), default="cpu")
    s.add_argument("--out")
    s = sub.add_parser("neutralize", help="rolling OLS neutralization surowego sygnału na najnowszym datasecie (diagnostyka)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--latest", action="store_true")
    s.add_argument("--signal", choices=("ROC20",), default="ROC20")
    s.add_argument("--profile", default="SIGNAL_NEUTRALIZATION_ROLLING_V1")
    s = sub.add_parser("tick-export", help="eksport ticków (wykonuje działający bot przez worker) albo import chunków")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--symbol")
    s.add_argument("--days", type=float, default=90)
    s.add_argument("--source", choices=("bridge", "import"), default="bridge")
    s.add_argument("--path")
    s = sub.add_parser("tick-replay", help="replay archiwum ticków: cechy kinematyczne M1 + scoreboard (nie trening)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--latest", action="store_true")
    s.add_argument("--profile", default="MQ_NEWTONIAN_QUOTES_V2")
    s.add_argument("--tick-size", type=float, default=0.01)
    s.add_argument("--point", type=float, default=0.01)
    for n in ("report", "replay"):
        s = sub.add_parser(n)
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        s.add_argument("--latest", action="store_true")
        s.add_argument("--run")
        if n == "replay":
            s.add_argument("--mode", choices=("shadow",), default="shadow")
    s = sub.add_parser("evaluate-holdout", help="jednorazowa ocena zamrożonego kandydata na holdoucie (log dostępu)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--candidate-id", required=True)
    s.add_argument("--protocol-id", required=True)
    s = sub.add_parser("select", help="ręczny wskaźnik SHADOW (nigdy wykonanie)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--candidate-id", required=True)
    s = sub.add_parser("rollback")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--task", default=T.TASK_MOVE)
    s = sub.add_parser("pipeline", help="train-all: dataset + trening obu zadań (bez aktywacji)")
    s.add_argument("--asset", choices=INSTR, default="XAUUSD")
    s.add_argument("--dataset")
    s.add_argument("--profile", choices=tuple(T.PROFILES), default="standard")
    s.add_argument("--commission", type=float)
    s.add_argument("--allow-synthetic-fixture", action="store_true")
    s.add_argument("--out")
    a = ap.parse_args(argv)
    from ..extind.cli import _latest_real

    def raw(path=None, allow_syn=False):
        ds = Path(path) if path else _latest_real(a.asset)
        if ds is None or not (ds / "source_metadata.json").exists():
            return None, "BLOCKED_NO_HISTORY: brak eksportu REAL_USER_DATA (00_TRENING_START.bat / export) – podaj --dataset"
        meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
        if meta.get("data_kind") != "REAL_USER_DATA" and not allow_syn:
            return None, f"BLOCKED_SYNTHETIC: {meta.get('data_kind')} – tylko z --allow-synthetic-fixture (artefakt TEST_ONLY)"
        return ds, None

    try:
        if a.c == "audit":
            ds = _latest_real(a.asset)
            reg = T._reg(a.asset)
            dsl = T.latest_dataset(a.asset, T.TASK_MOVE)
            _print({"instrument": a.asset, "latest_real_export": str(ds) if ds else None, "latest_dataset_move": str(dsl) if dsl else None,
                    "latest_dataset_setup": str(T.latest_dataset(a.asset, T.TASK_SETUP) or "") or None, "indicator_profile": T.indicator_profile(a.asset),
                    "shadow": reg.get("shadow"), "runs": len(reg.get("runs", {})), "families": list(T.FAMILIES_ALL), "evidence_minima": T.EVIDENCE,
                    "blocked": None if ds else "BLOCKED_NO_HISTORY"})
            return 0 if ds else 2
        if a.c == "export":
            if a.source == "bridge":
                print("[INFO] Eksport historii wykonuje działający bot/bridge MT5: 00_TRENING_START.bat (lub menu treningu → Eksport). "
                      "To polecenie nie łączy się z terminalem samo.")
                return 2
            if not a.path or not (Path(a.path) / "source_metadata.json").exists():
                print("[BLAD] --source import wymaga --path z source_metadata.json")
                return 2
            meta = json.loads((Path(a.path) / "source_metadata.json").read_text(encoding="utf-8"))
            if meta.get("instrument", "XAUUSD") != a.asset:
                print(f"[BLAD] INSTRUMENT_MISMATCH {meta.get('instrument')} != {a.asset}")
                return 2
            _print({"imported_source": a.path, "data_kind": meta.get("data_kind"), "note": "import offline – jawne źródło, bez łączenia z MT5"})
            return 0
        if a.c == "dataset":
            ds, err = raw(a.dataset, a.allow_synthetic_fixture)
            if err:
                print("[BLAD] " + err)
                return 2
            d = T.build_setup_dataset(a.asset, ds, a.commission) if a.task == T.TASK_SETUP else T.build_move_dataset(a.asset, ds)
            if d.get("status") == "NO_SETUP":
                print("[INFO] NO_SETUP: brak rzeczywistych setupów strategii w danych – dataset zapisany, trening setupu zostanie pominięty")
            man = T.save_dataset(a.asset, d)
            _print(man)
            return 0
        if a.c == "calibrate-indicators":
            ds, err = raw(a.dataset)
            if err:
                print("[BLAD] " + err)
                return 2
            profs = [x.strip() for x in a.profiles.split(",") if x.strip()]
            out = {}
            if {"MQ_MITP_32_V1", "STRUCTURE_CAUSAL_V2"} & set(profs):
                out["indicator_profile"] = T.calibrate_indicators(a.asset, ds)
            mk = [x for x in profs if x in ("MQ_REGIME_MULTI_V2", "MQ_SMMA_HL3_V2", "MQ_ZSCORE_V2", "STRUCTURE_CAUSAL_V2")]
            if mk:
                from . import market_v2 as MV
                from ..extind.trainer import _bars
                meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
                m1 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M1")
                rep = MV.calibrate_profiles(m1, float(meta["tick_size"]), mk)
                rep.update(data_kind=meta.get("data_kind"), raw_dataset=str(ds), created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                pth = T.root(a.asset) / "market_profiles.json"
                if pth.exists():
                    hist = T.root(a.asset) / "market_profiles_history"
                    hist.mkdir(exist_ok=True)
                    (hist / f"{int(time.time())}.json").write_text(pth.read_text(encoding="utf-8"), encoding="utf-8")
                pth.write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
                out["market_profiles"] = {k: (v.get("chosen") or v.get("note")) for k, v in rep.get("profiles", {}).items()}
                out["market_profiles_status"] = rep["status"]
            _print(out)
            print("[INFO] Nowy profil – zbuduj ponownie dataset: python -m masterquo structure-intelligence dataset --asset " + a.asset)
            return 0
        if a.c == "train":
            d = T.latest_dataset(a.asset, a.task)
            if d is None:
                print(f"[BLAD] BLOCKED_NO_DATASET dla {a.task}: python -m masterquo structure-intelligence dataset --asset {a.asset} --task {a.task}")
                return 2
            print(f"Dataset: {d.name} · zadanie {a.task} · profil {a.profile}{' · eksperyment ' + a.experiment if a.experiment else ''}")
            from ..db.database import Database
            fams = [f.strip() for f in a.families.split(",") if f.strip()]
            if a.experiment:
                rep = T.train_experiment(a.asset, d, a.experiment, fams, a.profile, db=Database())
                if a.out:
                    Path(a.out).write_text(json.dumps(rep, indent=1, default=T._jd), encoding="utf-8")
                if rep.get("status") == "BLOCKED_NO_TICK_HISTORY":
                    print(f"[BLAD] BLOCKED_NO_TICK_HISTORY: {rep.get('reason')}")
                    return 2
                _print({k: rep.get(k) for k in ("run_id", "experiment_id", "status", "rows", "rows_rejected_warmup_or_failure", "variants")})
                return 4 if rep["status"] == "INSUFFICIENT_EVIDENCE" else 0
            ops = [o.strip().upper() for o in (a.sew_operators or "").split(",") if o.strip()] or None
            if ops and any(o not in T.SN.CONNECT_F for o in ops):
                print("[BLAD] CONNECT_F_INVALID (ADD|AND|IAND)")
                return 2
            spike = {k: v for k, v in (("encoder", a.encoder), ("attention", a.attention)) if v}
            rep = T.train(a.asset, d, a.task, fams, a.profile, db=Database(), sew_operators=ops, spike_cfg=spike, transform=a.transform)
            if rep.get("status") == "INCOMPATIBLE":
                print(f"[BLAD] INCOMPATIBLE: {rep.get('reason')}")
                return 2
            if a.out:
                Path(a.out).write_text(json.dumps(rep, indent=1, default=T._jd), encoding="utf-8")
            if rep["status"] in ("STALE_DATASET", "NO_SETUP"):
                print(f"[BLAD] {rep['status']}: {rep.get('reason')} {rep.get('rebuild', '')}")
                return 2
            _print({k: rep.get(k) for k in ("run_id", "status", "evidence", "comparison", "candidates", "run_dir")})
            return 4 if rep["status"] == "INSUFFICIENT_EVIDENCE" else 0
        if a.c in ("report", "replay"):
            reg = T._reg(a.asset)
            rid = a.run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
            if not rid:
                print("[BLAD] brak runów")
                return 2
            rep = json.loads((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
            if a.c == "report":
                _print({k: rep.get(k) for k in ("run_id", "task_id", "status", "evidence", "comparison", "candidates", "holdout_from", "role", "profile")})
                return 0
            s = reg.get("shadow", {}).get(T.TASK_MOVE)
            if not s:
                print("[INFO] brak wybranego modelu SHADOW – replay nie ma czego odtwarzać (select --candidate-id …)")
                return 2
            meta, model = T.load_candidate(Path(s["dir"]))
            data = T.load_dataset(T.root(a.asset) / "datasets" / meta["dataset_id"], T.TASK_MOVE)
            sp = T.split(data)
            tail = sp["dev"][-2000:]                                  # dev tail only - the holdout is NOT opened by replay
            P, Q = T._predict(model, meta["family"], data, T.TASK_MOVE, tail)
            _, Y, R = T._task_arrays(data, T.TASK_MOVE)
            _print({"mode": "shadow", "candidate": s["candidate_id"], "rows": int(len(tail)), "scope": "DEV_TAIL (holdout nieotwierany)",
                    "metrics_uncalibrated": T.metrics(P, Q, Y[tail], R[tail])})
            return 0
        if a.c == "minirocket":
            from . import minirocket_v2 as MR
            if a.action == "parity":
                rep = MR.parity(Path(a.fixtures), a.reference_python, Path(a.native_scores) if a.native_scores else None,
                                Path(a.output) if a.native_scores else None, Path(a.native_status_file) if a.native_status_file else None)
                rep["reference_version_requested"] = a.reference_version
                _print(rep)
                return 0 if all(v != "FAIL" and not str(v).startswith("FAIL") for v in rep["results"].values()) else 3
            if a.action == "native-status":
                _print(MR.native_status(Path(a.native_status_file) if a.native_status_file else None))
                return 0
            if a.action == "export-fixture":
                z = __import__("numpy").load(Path(a.fixtures) / "sktime_fixture.npz")
                mr = MR.MiniRocketV2().configure(z["X"].shape[1], 10000, 32)
                mr.biases = z["biases"].astype("float32")
                mr.fit_idx = __import__("numpy").zeros(len(mr.lay["dilations"]) * 84, "int32")
                Path(a.output).mkdir(parents=True, exist_ok=True)
                _print(MR.export_fixture(Path(a.output) / "PMW_MR2_FIXTURE.bin", mr, z["X"]))
                print("[INFO] Skopiuj PMW_MR2_FIXTURE.bin do <MT5 Data Folder>\\MQL5\\Files\\PMW\\ i uruchom skrypt PMW_MR2_SelfTest.")
                return 0
            if not a.model_id:
                print("[BLAD] --model-id wymagane (candidate_id rodziny MQ_MINIROCKET_RIDGE_V2)")
                return 2
            reg = T._reg(a.asset)
            rid = next((r for r in reg["runs"] if a.model_id.startswith(r + "-")), None)
            if rid is None or not a.model_id.endswith(MR.HEAD_ID):
                print("[BLAD] MODEL_NOT_FOUND albo nie jest MQ_MINIROCKET_RIDGE_V2")
                return 2
            meta, model = T.load_candidate(Path(reg["runs"][rid]["run_dir"]) / "models" / MR.HEAD_ID)
            temps = [c["T"] for c in meta["calibration"]]
            man = MR.export_native(Path(a.output), model[1], model[2], temps, dict(meta, calibration_status="TEMPERATURE"))
            _print({"exported": a.output, "model_bin_sha256": man["model_bin_sha256"], "role": meta["role"],
                    "native": "NATIVE_NOT_EXECUTED (eksport ≠ test natywnej inferencji)"})
            return 0
        if a.c == "benchmark":
            from . import si_families as SFm
            rep = SFm.benchmark([f.strip() for f in a.families.split(",") if f.strip()])
            if a.out:
                Path(a.out).write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
            _print(rep)
            return 0
        if a.c == "neutralize":
            from ..analysis import neutralization as NZ
            d = T.latest_dataset(a.asset, T.TASK_MOVE)
            if d is None:
                print("[BLAD] BLOCKED_NO_DATASET")
                return 2
            data = T.load_dataset(d, T.TASK_MOVE)
            v, elig, info = T._neutral_variants(data)
            _print({"profile": NZ.PROFILE, "signal": a.signal, "rows": int(len(elig)), "eligible": int(elig.sum()), "diagnostics": info["diagnostics"]})
            return 0
        if a.c == "tick-export":
            from . import tick_store as TS
            if a.source == "bridge":
                print("[INFO] Eksport ticków wykonuje działający bot (jeden worker MT5): panel Structure Intelligence → Eksport ticków, "
                      "albo POST /api/v1/structure-intelligence/jobs {kind: tick_export, days}. To polecenie nie łączy się z terminalem samo.")
                return 2
            src = Path(a.path or "")
            files = sorted(src.glob("ticks_*.npz")) if src.is_dir() else []
            if not files:
                print("[BLAD] --source import wymaga --path z plikami ticks_*.npz")
                return 2
            n = 0
            for f in files:
                with __import__("numpy").load(f, allow_pickle=False) as z:
                    ticks = [{"t_ms": int(z["t_ms"][i]), "bid": float(z["bid"][i]), "ask": float(z["ask"][i])} for i in range(len(z["t_ms"]))]
                TS.save_chunk(a.asset, ticks, "IMPORT", "AS_PROVIDED_UTC_MS", False)
                n += len(ticks)
            _print({"imported_ticks": n, "files": len(files), "availability_basis": "HISTORICAL_SOURCE_TIME_ESTIMATE"})
            return 0
        if a.c == "tick-replay":
            from . import tick_store as TS
            r = TS.replay(a.asset, a.tick_size, a.point)
            _print({k: v for k, v in r.items() if k != "dir"})
            return 2 if r.get("status") == "BLOCKED_NO_TICK_HISTORY" else 0
        if a.c == "evaluate-holdout":
            from ..db.database import Database
            _print(T.evaluate_holdout(a.asset, a.candidate_id, a.protocol_id, Database()))
            return 0
        if a.c == "select":
            _print(T.select_shadow(a.asset, a.candidate_id))
            return 0
        if a.c == "rollback":
            _print(T.rollback(a.asset, a.task))
            return 0
        if a.c == "pipeline":
            ds, err = raw(a.dataset, a.allow_synthetic_fixture)
            if err:
                print("[BLAD] " + err)
                return 2
            from ..db.database import Database
            out = {"instrument": a.asset, "profile": a.profile, "tasks": {}}
            d = T.build_move_dataset(a.asset, ds)
            m = T.save_dataset(a.asset, d)
            fams = ["LOGREG", "XGB"] + list(T.SN.FAMILIES)
            dsd = T.root(a.asset) / "datasets" / m["dataset_id"]
            ops = ["ADD", "AND", "IAND"] if a.profile == "standard" else ["ADD"]          # quick = incomplete smoke (ADD only)
            rep = T.train(a.asset, dsd, T.TASK_MOVE, fams, a.profile, db=Database(), sew_operators=ops)
            out["tasks"][T.TASK_MOVE] = {k: rep.get(k) for k in ("run_id", "status", "evidence", "candidates", "role")}
            out["sew_operators"] = ops
            # PMW-UPD-09: the same task with the new families (bar profile HYBRID + MiniRocket V2), then the quote profile separately
            r9 = T.train(a.asset, dsd, T.TASK_MOVE, list(T.SF.FAMILIES), a.profile, db=Database(), spike_cfg={"encoder": "BAR_EVENT_V1",
                         "attention": "HYBRID"}, transform=T.SF.MR.TRANSFORM_ID)
            out["tasks"]["PMW-UPD-09:BAR+MINIROCKET"] = {k: r9.get(k) for k in ("run_id", "status", "candidates", "role")}
            rq = T.train(a.asset, dsd, T.TASK_MOVE, [T.SF.SB_FAMILY], a.profile, db=Database(), spike_cfg={"encoder": "QUOTE_EVENT_V1",
                         "attention": "HYBRID"})
            out["tasks"]["PMW-UPD-09:QUOTE_EVENT_V1"] = {k: rq.get(k) for k in ("run_id", "status", "candidates", "role")}
            from . import minirocket_v2 as MR
            out["minirocket_parity"] = MR.parity(Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "minirocket")["results"]
            for ex in T.EXPERIMENTS:                                                     # PMW-UPD-08 experiments (ticks missing -> BLOCKED only here)
                try:
                    r3 = T.train_experiment(a.asset, dsd, ex, ["LOGREG", "XGB"], a.profile, db=Database())
                    out["tasks"][ex] = {k: r3.get(k) for k in ("run_id", "status", "reason", "rows", "role")}
                except ValueError as exc:
                    out["tasks"][ex] = {"status": "FAILED", "reason": str(exc)}
            try:
                d2 = T.build_setup_dataset(a.asset, ds, a.commission)
                if d2.get("status") == "NO_SETUP":
                    out["tasks"][T.TASK_SETUP] = {"status": "NO_SETUP"}
                else:
                    m2 = T.save_dataset(a.asset, d2)
                    r2 = T.train(a.asset, T.root(a.asset) / "datasets" / m2["dataset_id"], T.TASK_SETUP, fams, a.profile, db=Database())
                    out["tasks"][T.TASK_SETUP] = {k: r2.get(k) for k in ("run_id", "status", "evidence", "candidates", "role")}
            except ValueError as exc:
                out["tasks"][T.TASK_SETUP] = {"status": "BLOCKED_COSTS" if "COSTS" in str(exc) else "FAILED", "reason": str(exc)}
            if a.out:
                Path(a.out).write_text(json.dumps(out, indent=1, default=T._jd), encoding="utf-8")
            _print(out)
            return 0
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
