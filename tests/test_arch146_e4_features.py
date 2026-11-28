"""Etap 4 (Apollo23 1.46, docs/arch146/ETAP2_PROJEKT.md §3-§6): cechy i ledgery - features/schemas.py + ledgers/ (widok).

* features/schemas.py PMW-FEAT-SCHEMAS-1: rejestr 25 schematów cech (id, wersja, właściciel = moduł buildera, lista cech, fingerprint =
  hash WYJŚCIA buildera na zamrożonym fixture PMW-FEAT-FIXTURE-1). Buildery zostają u właścicieli bez zmian. Zmiana buildera bez nowej
  wersji (nowego id) = test czerwony.
* ledgers/view.py PMW-LEDGER-VIEW-1: widok obejmuje wszystkie magazyny z ETAP2 §5 (evaluation, quant/ledger, mm ledger, decision/ledger,
  scalp, ml + pliki) - AUX_ADAPTERS: ledger decyzji PMW-ARC-1, rejestry holdoutu i prób, ledgery plikowe; tylko odczyt, bez migracji,
  writery bez zmian (wiersze testowe zapisują WŁASNE writery właścicieli tam, gdzie to możliwe).
Wszystko tylko odczyt / liczenie na danych SYNTETYCZNYCH - bez MT5, bez zleceń, bez zapisu do data/.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import _env

REQUIRED_IDS = {"PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4", "MQ-FEAT-1.3.0", "SCALP_INDICATOR_CONTEXT_V2",
                "SCALP-SETUP-FEAT-1.0.0", "PMW-TH-FEAT-1", "PMW-MM-EVENT-1", "FS-1.0.0", "SMF-1.0.0", "NSS-FEAT-1.0.0", "PMW-ZONES-SEM-1",
                "PMW-ZONES-SEM-2"}
FIXTURE_DIGEST = "899c42bba3ff4a7d"        # PMW-FEAT-FIXTURE-1 (the generator is frozen with FIXTURE_VERSION)


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = _env.TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()


class TestFeatureSchemaRegistry(_Data):
    """ETAP2 §4 'Cechy': 25 schematów wersjonowanych samymi nazwami (ETAP1 rejestry_cech#4) - rejestr z odciskiem formuły."""

    def test_registry_covers_the_schemas_of_the_code(self):
        from masterquo.features import schemas as FS
        ids = [s.id for s in FS.SCHEMAS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 25)
        self.assertLessEqual(REQUIRED_IDS, set(ids))
        self.assertEqual(set(FS.FINGERPRINTS), set(ids))                  # every schema has a frozen fingerprint, nothing else
        self.assertEqual({s.family for s in FS.SCHEMAS},
                         {"quant", "ml", "zones", "extind", "scalp", "gold_candles", "trainhub", "mm", "lab", "sh", "research"})

    def test_owner_declares_the_label_and_owns_the_builder(self):
        import importlib

        from masterquo.features import schemas as FS
        for s in FS.SCHEMAS:
            self.assertEqual(FS.owner_id(s.id), FS.label(s.id), s.id)
            mod, fn = s.owner.split(" ")[0].split(":")
            self.assertTrue(callable(getattr(importlib.import_module(mod), fn)), s.owner)
            self.assertTrue(s.version and s.version in s.id or s.version in ("1",), s.id)
        self.assertEqual(FS.label("PMW-MM-EVENT-1"), __import__("masterquo.mm.events", fromlist=["x"]).FEATURE_SCHEMA)
        from masterquo.mm import features as MMF
        from masterquo.mm import jobs as MJ
        self.assertEqual(FS.label("PMW-MM-FEATURES-1/HDC"), MMF.schema_id(MJ.HDC_FEATURES))

    def test_names_are_the_owner_lists_and_match_the_dictionary(self):
        from masterquo.features import catalog as FC
        from masterquo.features import schemas as FS
        live = FC.registry_names()
        for s in FS.SCHEMAS:
            nm = FS.names(s.id)
            self.assertTrue(nm, s.id)
            self.assertEqual(len(nm), len(set(nm)), s.id)
            if s.catalog and s.id != "PMW-MM-FEATURES-1/HDC":
                self.assertEqual(nm, live[s.catalog], s.id)               # the same names as PMW-FEAT-DICT-1 knows
        self.assertLessEqual(set(FS.names("PMW-MM-FEATURES-1/HDC")), set(live["mm"]))
        from masterquo.ml import features as MF
        from masterquo.scalp import strategy as ST
        self.assertEqual(FS.names("MQ-FEAT-1.3.0"), MF.FEATURE_NAMES)
        self.assertEqual(FS.names("SCALP-SETUP-FEAT-1.0.0"), list(ST.SETUP_FEATURES))
        self.assertEqual(FS.names("SCALP-NET-FEAT-1.0.0")[:len(ST.SETUP_FEATURES)], list(ST.SETUP_FEATURES))
        for v in ("PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-4"):
            self.assertEqual(FS.get(v).names_kind, "FIXTURE")
        self.assertTrue(any(n.startswith("ctx:regime_sh=") for n in FS.names("PMW-QUANT-FEAT-4")))
        self.assertFalse(any(n.startswith("ctx:regime=") for n in FS.names("PMW-QUANT-FEAT-4")))
        self.assertTrue(any(n.startswith("ctx:regime=") for n in FS.names("PMW-QUANT-FEAT-1")))

    def test_fingerprints_are_frozen_stable_and_create_nothing(self):
        from masterquo.features import schemas as FS
        rows = FS.check()
        bad = [r for r in rows if not r["ok"]]
        self.assertEqual(bad, [], "fingerprint / label differ from the frozen ones - a builder changed without a new schema version")
        self.assertEqual({r["id"]: FS.fingerprint(r["id"]) for r in rows}, FS.FINGERPRINTS)   # recomputed: the same
        self.assertEqual(list(self.data.rglob("*")), [])                  # builders on the fixture write nothing to data/
        self.assertEqual(FS.FINGERPRINTS["PMW-QUANT-FEAT-1"], FS.FINGERPRINTS["PMW-QUANT-FEAT-2"])   # one builder (build2)
        self.assertNotEqual(FS.FINGERPRINTS["PMW-QUANT-FEAT-1"], FS.FINGERPRINTS["PMW-QUANT-FEAT-3"])
        self.assertNotEqual(FS.FINGERPRINTS["PMW-ZONES-SEM-1"], FS.FINGERPRINTS["PMW-ZONES-SEM-2"])
        self.assertEqual(len(set(FS.FINGERPRINTS.values())), len(FS.FINGERPRINTS) - 1)

    def test_fingerprint_is_the_hash_of_the_owner_builder_output(self):
        """The registry wraps the owner's function (same call, same numbers): the digest of a direct call = the registry fingerprint."""
        from masterquo.features import schemas as FS
        from masterquo.lab import features as LF
        from masterquo.quant import features as QF
        from masterquo.trainhub import features as TF
        cands, preds = FS._quant_inputs()

        def fp(out):
            return FS.digest({"fixture": FS.FIXTURE_VERSION, "output": out})
        self.assertEqual(fp([QF.build4(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-4"])
        self.assertEqual(fp([QF.build3(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-3"])
        self.assertEqual(fp([QF.build2(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-1"])
        self.assertEqual(fp(LF.feature_matrix(FS._b("M5", 700), "M5")), FS.FINGERPRINTS["FS-1.0.0"])
        cols = {tf: FS._cols(tf, 1500) for tf in ("M1", "M5", "M15", "M30")}
        th = {}
        for base in ("M1", "M5", "M15"):
            t, X, nm = TF.build(cols, base, 0.01)
            th[base] = {"t": t[-200:], "X": X[-200:], "names": nm}
        self.assertEqual(fp(th), FS.FINGERPRINTS["PMW-TH-FEAT-1"])

    def test_builder_change_without_version_bump_is_red(self):
        """A formula change under the same id is detected - and only for the schemas whose builder it touches."""
        from masterquo.features import schemas as FS
        from masterquo.quant import features as QF

        def red(*ids):
            return {r["id"] for r in FS.check(list(ids)) if not r["ok"]}
        # FEAT-3 / FEAT-4 fix (D8) reverted under the same ids: FEAT-3 / -4 red, the frozen FEAT-1 / -2 (build2) untouched
        with mock.patch.object(QF, "_filter_dir_v3", QF._dir_of):
            self.assertEqual(red("PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-2", "PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4"),
                             {"PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4"})
        # another RSI seed in trainhub (ETAP1: 2.96e-3 at bar 14, 1.18e-5 at bar 100)
        from masterquo.strategies import indicators as SI
        from masterquo.trainhub import features as TF

        def rsi_other_seed(c):
            import numpy as np
            return np.array([np.nan if v is None else v / 100.0 - 0.5 for v in SI.rsi(list(c), 14)])
        with mock.patch.object(TF, "_rsi", rsi_other_seed):
            self.assertEqual(red("PMW-TH-FEAT-1", "FS-1.0.0"), {"PMW-TH-FEAT-1"})
        # SMA ATR instead of Wilder in lab FS-1.0.0 (3.75 % median difference, ETAP1 rejestry_cech#7)
        from masterquo.lab import common as LC
        from masterquo.lab import features as LF

        def sma_atr(h, lo, c, n=14):
            import numpy as np
            prev = np.r_[c[0], c[:-1]]
            tr = np.maximum(np.maximum(h - lo, np.abs(h - prev)), np.abs(lo - prev))
            return LC.sma(tr, n)
        with mock.patch.object(LF, "atr", sma_atr):
            self.assertEqual(red("FS-1.0.0", "SMF-1.0.0"), {"FS-1.0.0"})
        # SEM-1 session coding in SEM-2 (I0865): only SEM-2 changes
        from masterquo.zones import features as ZF
        orig = ZF._session_code
        with mock.patch.object(ZF, "_session_code", lambda ctx, legacy: orig(ctx, True)):
            self.assertEqual(red("PMW-ZONES-SEM-1", "PMW-ZONES-SEM-2"), {"PMW-ZONES-SEM-2"})
        # a missing setup context as NaN instead of 0.0 in setup_features: SETUP red
        from masterquo.scalp import strategy as ST
        orig_sf = ST.setup_features
        with mock.patch.object(ST, "setup_features", lambda *a: {k: (float("nan") if v == 0.0 else v) for k, v in orig_sf(*a).items()}):
            self.assertIn("SCALP-SETUP-FEAT-1.0.0", red("SCALP-SETUP-FEAT-1.0.0"))
        # a version bump in the owner without a registry entry is red as well (the registry must get the new id)
        from masterquo.ml import features as MF
        with mock.patch.object(MF, "FEATURE_SCHEMA_VERSION", "MQ-FEAT-1.4.0"):
            row = FS.check(["MQ-FEAT-1.3.0"])[0]
            self.assertEqual((row["ok"], row["owner_id"]), (False, "MQ-FEAT-1.4.0"))
        self.assertEqual([r["id"] for r in FS.check() if not r["ok"]], [])          # patches gone: green again

    def test_fixture_is_frozen_and_valid(self):
        from masterquo.features import schemas as FS
        fx = FS.fixture()
        self.assertEqual({tf: len(v) for tf, v in fx.items()}, {"M1": 8640, "M5": 1728, "M15": 576, "M30": 288, "H1": 144, "H4": 140, "D1": 90})
        for tf, bars in fx.items():
            s = FS.TF_MIN[tf] * 60
            self.assertLessEqual(bars[-1]["t"] + s, FS.T_END, tf)           # every bar closed at T_END
            self.assertEqual([b["t"] for b in bars], sorted({b["t"] for b in bars}), tf)
            for b in bars:
                self.assertTrue(b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"], (tf, b))
                self.assertEqual(round(b["c"], 2), b["c"])
        self.assertEqual(fx["M1"][0]["open_utc"], "2026-03-02T00:00:00Z")
        self.assertEqual(FS.digest(fx), FIXTURE_DIGEST)
        g = FS._Rng(0)                                                    # splitmix64 reference stream (seed 0): 0xe220a8397b1dcdaf, ...
        self.assertEqual([int(g.u() * 2 ** 53) for _ in range(2)], [0xe220a8397b1dcdaf >> 11, 0x6e789e6aa1b965f4 >> 11])

    def test_canonical_form(self):
        import numpy as np
        from masterquo.features import schemas as FS
        self.assertEqual(FS.canonical([float("nan"), float("inf"), -float("inf"), 1e-13, 0.123456789123, 2650.123456789, True, None]),
                         ["NaN", "Inf", "-Inf", 0.0, 0.1234568, 2650.123, True, None])
        self.assertEqual(FS.canonical(np.array([[1.0, np.nan]])), {"__ndarray__": [1, 2], "v": [[1.0, "NaN"]]})
        self.assertEqual(FS.digest({"a": 1.0, "b": [1, 2]}), FS.digest({"b": [1, 2], "a": 1.0 + 1e-15}))
        self.assertNotEqual(FS.digest({"a": 1.0}), FS.digest({"a": 1.0 + 1e-6}))

    def test_tag_and_manifest_check(self):
        from masterquo.features import schemas as FS
        t = FS.tag("PMW-MM-EVENT-1")
        self.assertEqual(t["feature_schema_id"], FS.label("PMW-MM-EVENT-1"))
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {})["status"], "LEGACY")             # artifacts of today: accepted as today
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {"feature_fingerprint": FS.FINGERPRINTS["SMF-1.0.0"]})["status"], "OK")
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {"feature_fingerprint": "0" * 16})["status"], "MISMATCH")
        self.assertEqual(FS.check_manifest("NOPE", {})["status"], "UNKNOWN_SCHEMA")
        reg = FS.registry()
        self.assertEqual([r["id"] for r in reg], [s.id for s in FS.SCHEMAS])
        self.assertTrue(all(r["fingerprint"] for r in reg))


# ============================================================================================== ledgers: PMW-LEDGER-VIEW-1 coverage
T0 = 1_790_000_000.0                                                    # 2026-09-21 UTC (fixed)
# ETAP2 §5 'ledgery: evaluation, quant/ledger, mm ledger, decision/ledger, scalp, ml (+ pliki)' -> ledgers of the view
ETAP2_STORES = {"evaluation": {"evaluation"}, "quant/ledger": {"quant_rows", "quant_assessments"}, "mm ledger": {"mm_predictions"},
                "decision/ledger": {"decision_records", "execution_intents", "risk_reservations"},
                "scalp": {"scalp_shadow", "ml_scalp_predictions", "ml_scalp_samples", "nss_inferences", "forecast_shadow"},
                "ml": {"ml_predictions", "ml_samples", "eval_ledger"},
                "pliki": {"asge_trials", "structure_intelligence_holdout", "flow_context_holdout", "context_ind_events"}}


def _iso(t: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def _insert(db, table: str, **vals) -> None:
    for c in db.query(f'PRAGMA table_info("{table}")'):
        if c["name"] in vals or not c["notnull"] or c["dflt_value"] is not None or (c["pk"] and "INT" in (c["type"] or "").upper()):
            continue
        vals[c["name"]] = 0 if (c["type"] or "").upper() in ("INTEGER", "REAL", "INT", "FLOAT") else "x"
    db.execute(f'INSERT INTO "{table}"({", ".join(vals)}) VALUES ({", ".join("?" * len(vals))})', tuple(vals.values()))


def _tree(root: Path) -> dict:
    """sha256 of every file except SQLite's WAL sidecars (-wal / -shm): any reader of a WAL database - also mode=ro - may create them
    (the locking protocol), they hold no data of their own once the writer closed (checked separately: the -wal is empty)."""
    import hashlib
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
            if p.is_file() and not p.name.endswith(("-wal", "-shm"))}


class TestLedgerViewStores(_Data):
    """ETAP2 §5: the view covers every ledger store (it lacked the decision ledger, the holdout / trial registries and the file ledgers)."""

    def test_view_covers_every_store_of_etap2_section5(self):
        from masterquo.ledgers import view as LV
        names = set(LV.ALL_ADAPTERS)
        for store, ledgers in ETAP2_STORES.items():
            self.assertLessEqual(ledgers, names, store)
        self.assertEqual(len(LV.ADAPTERS), 19)                             # the prediction / outcome ledgers of I0028 unchanged
        self.assertEqual({a.group for a in LV.ADAPTERS.values()}, {"prediction"})
        self.assertEqual(set(LV.AUX_ADAPTERS) & set(LV.ADAPTERS), set())
        self.assertEqual({a.group for a in LV.AUX_ADAPTERS.values()}, {"decision", "holdout", "trials", "events"})
        # ETAP1 'ledgery': 11 forecast + 4 outcome tables, 3 holdout / trial registries, the decision tables (0025_decision_arc.sql)
        tables = {a.table for a in LV.ALL_ADAPTERS.values() if a.reader is None and set(a.stores) & {"main", "ml"}}
        self.assertLessEqual({"eval_ledger", "lab_holdout_access", "lab_trials", "decision_records", "execution_intents", "risk_reservations",
                              "ml_predictions", "scalp_shadow", "ai_signals", "si_outcomes", "ml_scalp_samples"}, tables)
        from masterquo.db.database import Database
        have = {r["name"] for r in Database().query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual(tables, have)                                 # every adapter reads a table the migrations create
        self.assertEqual(set(LV.RUN_MODES), {"LIVE_SHADOW", "LIVE", "WALK_FORWARD", "REPLAY", "OFFLINE_VALIDATION"})

    def test_file_store_paths_are_the_writers_paths_and_the_view_creates_nothing(self):
        import mq_instruments as mi
        from masterquo.ledgers import view as LV
        st = {s.id: s for s in LV.stores()}
        for n in LV.AUX_ADAPTERS:
            self.assertEqual(list(LV.records(n)), [], n)
        LV.status()
        self.assertEqual(list(self.data.rglob("*")), [])                  # registry + reads: no file, no folder (writers' roots mkdir)
        from masterquo.lab import structure_task as STK
        from masterquo.lab.context_ind import task as CT
        from masterquo.lab.flow_context import task as FT
        from masterquo.wf32_services import Wf32Services
        self.assertEqual(st["apollo_trials"].path, Wf32Services(None).trials.path)
        for inst in mi.profiles():
            self.assertEqual(st[f"structure_intelligence:{inst}"].path, STK.root(inst) / "registry.json")
            self.assertEqual(st[f"flow_context:{inst}"].path, FT.root(inst) / "registry.json")
            self.assertEqual(st[f"context_ind:{inst}"].path, CT.root(inst) / "ledger")
            self.assertEqual((st[f"context_ind:{inst}"].fmt, st[f"flow_context:{inst}"].fmt), ("jsonl_dir", "json"))

    def _fill(self):
        """Rows written by the owners' own writers where they can run offline (RiskBook / IntentLedger, reserve_holdout, TrialLedger,
        the lab registry writers); plain inserts / the documented JSONL format otherwise."""
        import json
        from types import SimpleNamespace

        from masterquo.apollo import asge as ASG
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.decision.ledger import IntentLedger, RiskBook
        from masterquo.lab import structure_task as STK
        from masterquo.lab.context_ind import task as CT
        from masterquo.lab.flow_context import task as FT
        from masterquo.ml import scalp_task as stk
        from masterquo.ml.router import ml_store
        from masterquo.wf32_services import Wf32Services
        db = Database()
        cfg = AppConfig()
        book = RiskBook(db, SimpleNamespace(get=lambda: cfg), sh_limits=dict, clock=lambda: T0)
        il = IntentLedger(db, book)
        a = il.open(path="ACTIVE", mode="PAPER", account_key=None, subject="SU-1", symbol="XAUUSD-", side="BUY", volume=0.1, risk_money=25.0,
                    record_id="DR-1", equity=10_000.0)
        il.sent(a["intent"]["intent_id"], "ATT-1")
        il.outcome(a["intent"]["intent_id"], {"status": "FILLED", "price": 2650.1, "volume": 0.1, "ticket": 7})
        b = il.open(path="SH", mode="PAPER", account_key=None, subject="PL-2", symbol="XAUUSD-", side="SELL", volume=0.2, risk_money=30.0,
                    record_id="DR-2", equity=10_000.0)
        il.outcome(b["intent"]["intent_id"], {"status": "REJECTED", "reason": "INVALID_STOPS"})
        _insert(db, "execution_intents", intent_id="INT-X", dedup_key="k-x", created_at=_iso(T0), updated_at=_iso(T0), path="ACTIVE",
                kind="ENTRY", mode="PAPER", state="WEIRD")
        _insert(db, "decision_records", record_id="DR-1", created_at=_iso(T0), path="ACTIVE", source_id="D-1", strategy_id="XAU-S01",
                symbol="XAUUSD-", mode="PAPER", direction="LONG", base_verdict="ENTER", final_verdict="ENTER", reason_codes='["OK"]',
                models_json='[{"model_id": "ml:legacy", "role": "SHADOW"}]', inputs_hash="ih1", record_json="{}")
        stk.reserve_holdout(db, "XAUUSD", _iso(T0 - 86400), _iso(T0), "mh1", "SCALP_TASK")
        btc_db, _ = ml_store("BTC")
        stk.reserve_holdout(btc_db, "BTC", _iso(T0 - 86400), _iso(T0), "mh2", "SCALP_TASK")
        btc_db.close()
        _insert(db, "lab_holdout_access", at=_iso(T0), asset="XAUUSD", horizon="M5x12", protocol_id="P1", holdout_hash="hh", candidate_id="C1",
                result='{"brier": 0.24}')
        _insert(db, "lab_trials", trial_id="TR-1", created_at=_iso(T0), asset="BTC", horizon="M5x12", model_family="LOGREG", protocol_id="P1",
                data_hash="dh", config="{}", seeds="[11]", status="DONE", metrics='{"logloss": 0.69}')
        led = Wf32Services(None).trials
        led.add({"ir": {"k": 1}, "ir_hash": "IR1", "data_hash": "DH1", "status": "SHADOW_CHALLENGER", "reasons": [], "dev_trades": 40,
                 "dev_mean_net_r": 0.12, "positive_folds": 2, "holdout_mean_net_r": 0.05, "hurdle_net_r": 0.03, "version": ASG.VERSION})
        with open(led.path, "a", encoding="utf-8") as fh:
            fh.write('{"torn": ')                                            # a crash while writing: skipped by the writer and the view
        STK._update_reg("XAUUSD", lambda reg: reg.setdefault("holdout_access", {}).update(
            {"RUN1-LOGREG": {"candidate_id": "RUN1-LOGREG", "protocol_id": "SI-PROTO-1.0.0", "ledger": {"status": "FRESH"}, "metrics": [],
                             "at": _iso(T0), "model_hash": "smh", "role": "SHADOW"}}))
        FT._save_reg("BTC", {"runs": {}, "shadow": {}, "history": [], "holdout_access": {
            "R2-XGB": {"candidate_id": "R2-XGB", "ledger": {"status": "REUSED_PERIOD_EXPLORATORY"}, "metrics": {"m": 1}, "at": _iso(T0 + 60)}}})
        d = CT.root("XAUUSD") / "ledger"
        d.mkdir(parents=True, exist_ok=True)
        e = {"event_id": "EV-1", "seq": 1, "kind": "BOS_UP", "bar": 40, "available_at": T0 + 300, "price": 2651.2}
        (d / "M5_ph1.jsonl").write_text(json.dumps(dict(e, ledger_id="XAUUSD|M5|ph1|E1|EV-1", epoch=1, event_key="k#1")) + "\n", encoding="utf-8")
        (d / "epochs.json").write_text('{"M5": 1}', encoding="utf-8")
        db.close()

    def test_every_aux_adapter_maps_writer_rows_to_the_canonical_record(self):
        from masterquo.ledgers import view as LV
        self._fill()
        by = {}
        for name in LV.AUX_ADAPTERS:
            recs = list(LV.records(name))
            self.assertTrue(recs, name)
            for r in recs:
                self.assertLessEqual(set(LV.REQUIRED), set(r), name)
                self.assertIn(r["outcome_status"], LV.OUTCOME_STATUSES, name)
                self.assertIn(r["run_mode"], LV.RUN_MODES, name)
                self.assertEqual((r["pred_id"], r["view"], r["ledger"]), (f"{name}:{r['source_key']}", "PMW-LEDGER-VIEW-1", name))
                self.assertIsNotNone(r["decision_ts"], name)
            by[name] = recs
        it = {r["prediction"]["path"] + ":" + r["status_raw"]: r for r in by["execution_intents"]}
        self.assertEqual((it["ACTIVE:FILLED"]["outcome_status"], it["SH:REJECTED"]["outcome_status"]), ("SCORED", "EXCLUDED"))
        self.assertEqual(it["ACTIVE:FILLED"]["link_ids"]["source_ref"], "ATT-1")
        self.assertEqual(it["ACTIVE:FILLED"]["outcome"]["status"], "FILLED")
        self.assertEqual((it["ACTIVE:WEIRD"]["outcome_status"], it["ACTIVE:WEIRD"]["status_note"]), ("INVALID", "UNKNOWN_STATUS:WEIRD"))
        rs = {r["prediction"]["path"]: r for r in by["risk_reservations"]}
        self.assertEqual({k: (v["status_raw"], v["outcome_status"]) for k, v in rs.items()},
                         {"ACTIVE": ("CONSUMED", "SCORED"), "SH": ("RELEASED", "EXCLUDED")})
        self.assertEqual(rs["ACTIVE"]["decision_ts"], T0)
        dr = by["decision_records"][0]
        self.assertEqual((dr["side"], dr["run_mode"], dr["prediction"]["models"][0]["model_id"]), ("LONG", "LIVE", "ml:legacy"))
        self.assertEqual({r["instrument"]: r["status_raw"] for r in by["eval_ledger"]}, {"XAUUSD": "FRESH", "BTC": "FRESH"})
        self.assertEqual([r["instrument"] for r in LV.records("eval_ledger", instrument="BTC")], ["BTC"])
        self.assertEqual([r["source_key"] for r in by["asge_trials"]], ["T00001"])          # the torn line is skipped
        self.assertEqual(by["asge_trials"][0]["metrics"]["dev_trades"], 40)
        self.assertEqual([(r["instrument"], r["status_raw"]) for r in by["structure_intelligence_holdout"]], [("XAUUSD", "FRESH")])
        self.assertEqual([r["source_key"] for r in LV.records("flow_context_holdout", instrument="BTC")], ["R2-XGB"])
        self.assertEqual(list(LV.records("flow_context_holdout", instrument="XAUUSD")), [])
        ev = by["context_ind_events"][0]
        self.assertEqual((ev["timeframe"], ev["fingerprint"], ev["decision_ts"], ev["task"]), ("M5", "ph1", T0 + 300, "STRUCTURE_EVENT_BOS_UP"))
        self.assertEqual(by["lab_trials"][0]["metrics"], {"logloss": 0.69})
        st = LV.status()
        self.assertEqual(set(st["ledgers"]), set(LV.ALL_ADAPTERS))
        self.assertEqual(st["ledgers"]["execution_intents"], {"SCORED": 1, "EXCLUDED": 1, "INVALID": 1})

    def test_reading_never_changes_a_store(self):
        import sqlite3

        from masterquo.ledgers import view as LV
        self._fill()
        before = _tree(self.data)
        for name in LV.ALL_ADAPTERS:
            list(LV.records(name))
        LV.status()
        self.assertEqual(_tree(self.data), before)                        # bytes of every store identical, no file added
        self.assertEqual([p.name for p in self.data.rglob("*-wal") if p.stat().st_size], [])    # nothing pending: no write happened
        main = next(s for s in LV.stores() if s.id == "main")
        c = LV.connect_ro(main.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("UPDATE execution_intents SET state='FILLED'")
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
