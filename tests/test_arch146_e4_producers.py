"""1.46 arch Etap 4 – rejestr producentów: quant/ids (+ PRODUCERS) jedynym źródłem id, sh/models.REGISTRY, modelhub/catalog,
mm/inventory, quant/inventory i tools/model_map – widoki (ETAP2_PROJEKT.md §3/§4/§5).

Ruch jest NEUTRALNY: stałe skopiowane w widokach (quant/inventory._MM_TOOL i lista usług _analysis_rows, modelhub/catalog._FIXED_CANON
zadeklarowany dwa razy, wyprowadzenia id wiersza SH / modułu MM w trzech miejscach, krotki ("chronos2", "granite_ttm", "tirex2"),
("SEQ_LSTM", "SEQ_GRU", "RL_PPO"), ("data_quality", "risk_engine", "news"), DELEGATED rodzin) czytają teraz quant/ids albo własne dane
właściciela. Dowody:
* TestOldNewEquality – stare implementacje (skopiowane dosłownie z bazy cf5d941) == nowe, na >= 200 losowych wejściach (stałe ziarno);
* TestViewsIdenticalToBase – odpowiedzi katalogu (/api/v1/models/catalog), macierzy SH (/api/v1/sh models), inwentarza Quant,
  inwentarza MM i mapy modeli na TYM SAMYM stanie (pusty katalog danych, rt None + stały stub) identyczne z bazą (git archive bazy,
  osobny proces); pomijany bez repozytorium git;
* reguła "brak drugiego źródła id": tests/test_arch146_architecture.py::TestNoSecondIdSource.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

import _env
from _env import TempData

SEED = 146
N = 400
BASE_COMMIT = "cf5d941"          # stan gałęzi po wszystkich falach napraw (baza Etapu 4)

# ------------------------------------------------------------------------------------------------ old implementations (base cf5d941)
_OLD_FIXED_CANON = {"market_zones": "analysis:market_zones", "zone_map": "analysis:zones", "monte_carlo": "analysis:montecarlo"}
_OLD_MM_TOOL = {"buzoa": "TOOL", "sdom": "TOOL", "stfs": "TOOL", "quant_momentum": "NONE", "renko": "NONE", "head_shoulders": "NONE",
                "data_grabber": "TOOL", "tsvp": "TOOL", "mathbench": "TOOL", "chart_sync": "TOOL", "fusion_board": "TOOL"}
_OLD_TSFM = ("chronos2", "granite_ttm", "tirex2")
_OLD_DEEP = ("SEQ_LSTM", "SEQ_GRU", "RL_PPO")
_OLD_RULE_ROWS = ("data_quality", "risk_engine", "news")
_OLD_DELEGATED = ("TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT")


def _old_canonical_row_id(r: dict, I) -> str | None:
    rid, src = str(r.get("id") or ""), r.get("source")
    if src == "sh/models.REGISTRY":
        return f"group:{rid}" if rid in I.GROUPS else (I.resolve(rid) or f"sh:{rid}")
    if src == "mm/inventory.MODULES":
        m = rid.removeprefix("mm_")
        return I.resolve(m) or f"mm:{m}"
    if src == "trainhub":
        return I.resolve(rid.upper())
    return _OLD_FIXED_CANON.get(rid)


def _old_canonical_of(r: dict, I) -> str:
    cid = _old_canonical_row_id(r, I)
    if cid:
        return cid
    rid, src = r["id"], r.get("source")
    if src == "trainhub":
        return "trainhub:" + rid.upper()
    if src == "mm/inventory.MODULES":
        mid = rid.removeprefix("mm_")
        return I.resolve(mid) or I.resolve("mm:" + mid) or "mm:" + mid
    if rid in _OLD_FIXED_CANON:
        return _OLD_FIXED_CANON[rid]
    if rid in I.GROUPS:
        return "group:" + rid
    return I.resolve(rid) or "sh:" + rid


def _old_delegated(fid: str, inst: str, profile: str) -> str | None:
    if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
        return f"trening w trainhub: python -m masterquo trainhub train --instrument {inst} --models {fid} --profile {profile}"
    if fid == "SEQ_GRU_EVENT":
        return "trening w Centrum MM (mm/event_engine) – adapter istniejącego modelu zdarzeń, nie jest trenowany w magazynie rodzin"
    return None


def _name_pool() -> list[str]:
    """Every name the views can meet (aliases, canonical ids, SH / MM / catalog / trainhub row ids, families) + random noise."""
    from masterquo.mm import inventory as MI
    from masterquo.modelhub.families import registry as famreg
    from masterquo.quant import ids as I
    from masterquo.sh import models as SM
    from masterquo.trainhub import learn
    pool = set(I._ALIAS_TO) | set(I.PRODUCERS) | set(I.GROUPS) | set(I.EXTRA_PRODUCERS) | set(_OLD_FIXED_CANON) | set(_OLD_MM_TOOL)
    pool |= {it["id"] for it in SM.REGISTRY} | {m["id"] for m in MI.MODULES} | {"mm_" + m["id"] for m in MI.MODULES} | set(famreg())
    pool |= {m.lower() for m in learn.MODELS} | set(learn.MODELS) | {"", "zzz", "fincast", "Chronos-2", "tsfm:new", "mm:", "mm_", "TH_NEW",
                                                                      "TH_LOGREG_M5_H6", "gold_candles_99m", "group:lab", "research:g7"}
    rnd = random.Random(SEED)
    pool |= {"".join(rnd.choice("abcdefghijklmnopqrstuvwxyz_:ABCDEFGHIJ0123456789") for _ in range(rnd.randint(1, 14))) for _ in range(60)}
    return sorted(pool)


class TestOldNewEquality(unittest.TestCase):
    """Moved derivations: old literal implementation == new quant/ids-based one on random inputs (seed 146, >= 200 cases each)."""

    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.pool = _name_pool()

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_catalog_canonical_row_id_and_canonical_of(self):
        from masterquo.modelhub import catalog as CT
        from masterquo.quant import ids as I
        rnd = random.Random(SEED)
        srcs = ["sh/models.REGISTRY", "mm/inventory.MODULES", "trainhub", "1.28", "zones", "montecarlo", None, "quant/inventory (rejestr kanoniczny)"]
        cases = [{"id": rnd.choice(self.pool), "source": rnd.choice(srcs)} for _ in range(N)]
        cases += [{"id": n, "source": s} for n in self.pool for s in srcs]
        self.assertGreaterEqual(len(cases), 200)
        diff = [(r, _old_canonical_row_id(r, I), CT.canonical_row_id(r)) for r in cases if _old_canonical_row_id(r, I) != CT.canonical_row_id(r)]
        self.assertEqual(diff, [])
        diff = [(r, _old_canonical_of(r, I), CT._canonical_of(r)) for r in cases if _old_canonical_of(r, I) != CT._canonical_of(r)]
        self.assertEqual(diff, [])

    def test_sh_row_and_mm_module_ids(self):
        from masterquo.quant import ids as I
        rnd = random.Random(SEED + 1)
        names = self.pool + [rnd.choice(self.pool) + rnd.choice(["", "_M5", ":x", "2"]) for _ in range(N)]
        self.assertGreaterEqual(len(names), 200)
        for n in names:
            old_sh = f"group:{n}" if n in I.GROUPS else (I.resolve(n) or f"sh:{n}")          # quant/inventory._sh_rows + catalog
            self.assertEqual(I.sh_row_id(n), old_sh, n)
            self.assertEqual(I.mm_module_id(n), I.resolve(n) or I.resolve("mm:" + n) or "mm:" + n, n)   # catalog SH join / _canonical_of
            if I.resolve(n) is None:
                self.assertEqual(I.mm_module_id(n), f"mm:{n}", n)                            # quant/inventory._mm_rows (own row)
            self.assertEqual(I.MM_MODULES.get(n, "TOOL"), _OLD_MM_TOOL.get(n, "TOOL"), n)
            self.assertEqual(n in I.TSFM_MODELS, n in _OLD_TSFM, n)

    def test_quant_inventory_has_no_copies(self):
        from masterquo.modelhub import catalog as CT
        from masterquo.quant import ids as I
        from masterquo.quant import inventory as QI
        self.assertFalse(hasattr(QI, "_MM_TOOL"))
        self.assertFalse(hasattr(CT, "_FIXED_CANON"))
        self.assertEqual(I.MM_MODULES, _OLD_MM_TOOL)
        self.assertEqual(I.CATALOG_ROWS, _OLD_FIXED_CANON)
        self.assertEqual(I.TSFM_MODELS, _OLD_TSFM)
        # the analysis service rows: same ids, order, categories, roles, adapters, validation as the base literal rows
        self.assertEqual([(e["id"], e["category"], e["quant_role"], e["adapter"], e["validation"], e["code_state"]) for e in QI._analysis_rows()], [
            ("analysis:montecarlo", "SIMULATION", "SIMULATION", "quant.adapters.extended", "NOT_VALIDATED", "IMPLEMENTED"),
            ("analysis:zones", "ANALYSIS", "CONTEXT_STATE", "quant.adapters.extended", "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:market_zones", "ANALYSIS", "NOT_A_VOTE", None, "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:indicators", "ANALYSIS", "CONTEXT_STATE", "quant.adapters.extended", "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:svp", "ANALYSIS", "GATE_EXISTING", None, "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:dxy_correlation", "ANALYSIS", "CONTEXT_FEATURE", "quant.adapters.extended", "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:walls", "ANALYSIS", "GATE_EXISTING", None, "NOT_APPLICABLE", "IMPLEMENTED"),
            ("analysis:evaluation", "ANALYSIS", "SETUP_EVENT", "evaluation.service (ledger)", "NOT_APPLICABLE", "IMPLEMENTED"),
            ("quant:metamodel", "META_MODEL", "META_MODEL", "quant.service (assessment)", "NOT_VALIDATED", "IMPLEMENTED"),
            ("ext:catboost", "NOT_IMPLEMENTED", "NONE", None, "NOT_APPLICABLE", "NOT_IMPLEMENTED")])

    def test_rule_category_and_deep_env_derivations(self):
        from masterquo.modelhub import catalog as CT
        from masterquo.modelhub.families import registry as famreg
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as SM
        new_rule = [it["id"] for it in SM.REGISTRY if it["kind"] == "DETERMINISTIC" and set(it["roles"].values()) <= set(CT.RULE_ROLES)]
        self.assertEqual(new_rule, list(_OLD_RULE_ROWS))
        cat = {r["id"]: r["category"] for r in CT.build(None, "XAUUSD")["items"] if r.get("source") == "sh/models.REGISTRY"}
        self.assertEqual(sorted(k for k, v in cat.items() if v == "RULE"), sorted(_OLD_RULE_ROWS))
        fams = famreg()
        self.assertEqual(sorted(f for f, x in fams.items() if x.RUNTIME == "DEEP"), sorted(_OLD_DEEP))
        env = {e["id"].split(":", 1)[1]: e["env"] for e in QI._family_rows()}
        self.assertEqual({f: (".venv_deep" if f in _OLD_DEEP else ".venv") for f in env}, env)

    def test_families_delegated(self):
        from masterquo.modelhub.families import run as FR
        from masterquo.modelhub.families import service as FS
        rnd = random.Random(SEED + 2)
        names = self.pool + [rnd.choice(self.pool) for _ in range(N)]
        self.assertGreaterEqual(len(names), 200)
        for n in names:
            self.assertEqual(n in FS.DELEGATED, n in _OLD_DELEGATED, n)
            for inst, prof in (("XAUUSD", "smoke"), ("BTC", "full")):
                self.assertEqual(FR.delegated(n, inst, prof), _old_delegated(n, inst, prof), n)


# ------------------------------------------------------------------------------------------------ API views on the same state (base vs now)
_DUMP = r'''
import atexit, json, os, shutil, sys, tempfile
from types import SimpleNamespace
root = sys.argv[1]
os.environ["MASTERQUO_DATA_DIR"] = tempfile.mkdtemp(prefix="e4prod_")
atexit.register(shutil.rmtree, os.environ["MASTERQUO_DATA_DIR"], ignore_errors=True)
sys.path.insert(0, os.path.join(root, "backend"))
sys.path.insert(0, os.path.join(root, "tools"))
from masterquo.modelhub import catalog as CT
from masterquo.mm import inventory as MI
from masterquo.quant import inventory as QI
from masterquo.sh import models as SM
import model_map


class _Use:
    def __init__(self, u):
        self.use = u


def stub():
    models = {m: SimpleNamespace(use={"SCALPING": _Use("OBSERVE"), "HEDGING": _Use("ASSIST")}) for m in ("chronos2", "granite_ttm", "tirex2")}
    ts = SimpleNamespace(workers={m: SimpleNamespace(state={"status": "READY"}) for m in models},
                         settings=SimpleNamespace(get=lambda: SimpleNamespace(models=models)))
    kr = SimpleNamespace(state={"status": "READY"}, settings=SimpleNamespace(get=lambda: SimpleNamespace(strategy_use={"SCALPING": _Use("OBSERVE")})))
    return SimpleNamespace(tsfm=ts, kronos=kr, mm=None, families=None, quant=None)


CAT = ("id", "canonical_id", "aliases", "category", "source", "is_group", "members", "state", "runtime_state", "probe_status", "use", "group",
       "roles", "training", "location")
SHR = ("id", "kind", "group", "train", "runner_step", "owner_train", "status", "SCALPING", "HEDGING", "group_by_tf")
INV = ("id", "aliases", "category", "code_state", "runtime_state", "validation", "quant_role", "adapter", "source_registry", "env", "timeframes",
       "variants", "live_output")
out = {}
for inst in ("XAUUSD", "BTC"):
    for tag, rt in (("none", None), ("stub", stub())):
        c = CT.build(rt, inst)
        out[f"catalog_{tag}_{inst}"] = {"items": [{k: r.get(k) for k in CAT} for r in c["items"]],
                                        **{k: c[k] for k in ("counts_by_category", "counts_by_state", "counts_group_rows")}}
        m = SM.matrix(rt, inst)
        out[f"sh_{tag}_{inst}"] = {"rows": [{k: r.get(k) for k in SHR} for r in m["rows"]], "mode": m["mode"], "groups": m["correlation_groups"]}
        q = QI.build(rt, inst)
        out[f"inventory_{tag}_{inst}"] = {"entries": [{k: e.get(k) for k in INV} for e in q["entries"]], "coverage": q["coverage"]}
    out[f"sh_not_evaluated_{inst}"] = [{k: r.get(k) for k in SHR} for r in SM.not_evaluated(inst)["rows"]]
out["mm_inventory"] = [{k: r.get(k) for k in ("id", "status", "category", "unit_tests", "status_chain")} for r in MI.merge_run(None, "")]
mp = model_map.build()
out["model_map"] = {"elements": [{k: e.get(k) for k in ("id", "aliases", "legacy_ids", "category", "registry_source")} for e in mp["elements"]],
                    "outside": [e["id"] for e in mp["outside_registry"]]}
print(json.dumps(out, sort_keys=True, ensure_ascii=False, default=str))
'''


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(_env.ROOT), *args], capture_output=True, check=False)


class TestViewsIdenticalToBase(unittest.TestCase):
    """Catalog / SH matrix / Quant inventory / MM inventory / model map: ids, canonical ids, aliases, categories, sources, states and the use
    axis identical to the base commit on the same state. Scope = the identity projection (descriptive texts may change in later steps; a
    deliberate change of a producer id or category moves BASE_COMMIT)."""

    def test_same_state_same_views(self):
        try:
            known = _git("cat-file", "-e", f"{BASE_COMMIT}^{{commit}}").returncode == 0
        except OSError:
            known = False
        if not known:
            self.skipTest("brak repozytorium git / commitu bazy Etapu 4 (paczka wydania)")
        tmp = tempfile.mkdtemp(prefix="e4prod_base_")
        try:
            arc = _git("archive", "--format=tar", BASE_COMMIT, "backend/masterquo", "backend/mq_instruments.py", "backend/mq_venv.py", "tools",
                       "config")
            self.assertEqual(arc.returncode, 0, arc.stderr[-400:])
            subprocess.run(["tar", "-x", "-C", tmp], input=arc.stdout, check=True)
            env = {**os.environ, "PMW_BOOTSTRAP": "0", "MQ_FAKE_MARKET_ALWAYS_OPEN": "1", "MQ_BASKETS_OFFLINE": "1"}
            env.pop("MASTERQUO_DATA_DIR", None)
            dumps = []
            for root in (tmp, str(_env.ROOT)):
                r = subprocess.run([sys.executable, "-c", _DUMP, root], capture_output=True, text=True, env=env, timeout=900, check=False)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                dumps.append(json.loads(r.stdout.strip().splitlines()[-1]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        base, now = dumps
        self.assertEqual(sorted(base), sorted(now))
        for k in base:
            self.assertEqual(now[k], base[k], k)


if __name__ == "__main__":
    unittest.main()
