"""1.46 arch, fala 2 – grupa catalog: katalog modeli (modelhub/catalog.py) i opisy rejestru SH (sh/models.py) zgodne z kodem.
Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach klas / testów). Zmiany wyłącznie prezentacyjne:
sh/setup.py kopiuje z wierszy macierzy tylko id / status / group / use / role (nazwa i opis wyjścia nie są czytane przez cykl SH).

* I0276 (+I0281/I0285/I0291/I0297), I0314, I0316, I0568, I0573, I0576: każda ścieżka w catalog.LOCATION istnieje (si_move, structure_v2,
  vamd, fractal, nss, lab wskazywały nieistniejące pliki / katalogi).
* I0304: flow_reaction wskazuje model reakcji (lab/flow_context/task.py), nie Markov3 (osobny producent flow:markov3).
* I0579: atr_vol wskazuje sh/context.py (_atr, Wilder 14); StopDistance nie jest częścią komponentu SH.
* I0384: katalog nie odsyła do nieistniejącego „panelu 12 Master Models”.
* I0003: wiersze grupowe (th_direction / lab / si_move) oznaczone is_group i nieliczone w counts_by_*; obok stratnego `state` katalog
  publikuje runtime_state (surowa sonda) i oś use (udział per strategia z sh/models.participation).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

INST = "XAUUSD"
ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "backend" / "masterquo"


def _paths(location: str) -> list[str]:
    """Path tokens of a LOCATION text: parenthetical comments removed, split on ',' and '+'; a token counts as a path when it has a '/'
    or ends with '.py' (plain words such as 'engine' are descriptions)."""
    txt = re.sub(r"\([^)]*\)", " ", location)
    out = []
    for tok in re.split(r"[,+]", txt):
        tok = tok.strip()
        if tok and ("/" in tok or tok.endswith(".py")):
            out.append(tok)
    return out


def _exists(p: str) -> bool:
    return (ROOT / p).exists() if p.startswith("backend/") else (PKG / p).exists()


def _item(mid: str) -> dict:
    from masterquo.sh import models as SM
    return next(i for i in SM.REGISTRY if i["id"] == mid)


# ================================================================================================ ścieżki LOCATION
class TestI0276CatalogLocations(unittest.TestCase):
    def test_every_location_path_exists(self):
        """I0276 / I0314 / I0316 / I0568 / I0573 / I0576: before: lab/structure_intelligence/, lab/structure_v2.py, extind/vamd.py,
        extind/fractal.py, scalp/nss and lab/models did not exist."""
        from masterquo.modelhub import catalog as CAT
        missing = {}
        for mid, (loc, _data) in CAT.LOCATION.items():
            paths = _paths(loc)
            bad = [p for p in paths if not _exists(p)]
            if bad:
                missing[mid] = bad
        self.assertEqual(missing, {})

    def test_parser_sees_the_paths(self):
        """The existence test is not vacuous: every LOCATION except the plain-word ones yields at least one path."""
        from masterquo.modelhub import catalog as CAT
        no_path = [mid for mid, (loc, _d) in CAT.LOCATION.items() if not _paths(loc)]
        self.assertEqual(no_path, [])

    def test_si_move_names_the_structure_intelligence_code(self):
        from masterquo.modelhub import catalog as CAT
        loc = CAT.LOCATION["si_move"][0]
        for f in ("lab/structure_task.py", "lab/structure_nets.py", "lab/si_families.py", "lab/si_service.py"):
            self.assertIn(f, loc)
        self.assertNotIn("structure_intelligence/", loc)

    def test_nss_and_lab_name_the_code(self):
        from masterquo.modelhub import catalog as CAT
        self.assertIn("lab/nss.py", CAT.LOCATION["nss"][0])
        self.assertIn("lab/nss_service.py", CAT.LOCATION["nss"][0])
        self.assertIn("lab/protocol.py", CAT.LOCATION["lab"][0])
        self.assertIn("lab/service.py", CAT.LOCATION["lab"][0])


class TestI0316ContextIndicatorLocations(unittest.TestCase):
    def test_vamd_fractal_structure_v2(self):
        """I0314 / I0316 / I0568 / I0573 / I0576."""
        from masterquo.modelhub import catalog as CAT
        self.assertIn("lab/context_ind/vamd.py", CAT.LOCATION["vamd"][0])
        self.assertIn("lab/context_ind/fractal.py", CAT.LOCATION["fractal"][0])
        self.assertIn("analysis/structure_v2.py", CAT.LOCATION["structure_v2"][0])
        for mid in ("vamd", "fractal"):
            self.assertNotIn("extind/", CAT.LOCATION[mid][0])

    def test_fractal_is_m5_only(self):
        """I0576: sh/context._ctx_m5 computes the Katz FD on M5 only (FD.series(m5[-200:]))."""
        from masterquo.modelhub import catalog as CAT
        self.assertEqual(CAT.LOCATION["fractal"][1], "świece M5")
        self.assertEqual(CAT.LOCATION["vamd"][1], "świece M1/M5")            # _ctx_m5 + _ctx_m1


# ================================================================================================ flow_reaction (I0304)
class TestI0304FlowReaction(unittest.TestCase):
    def test_flow_reaction_location_is_reaction_model(self):
        from masterquo.modelhub import catalog as CAT
        loc = CAT.LOCATION["flow_reaction"][0]
        self.assertNotIn("markov.py", loc)
        self.assertIn("lab/flow_context/task.py", loc)

    def test_sh_row_is_the_reaction_model_only(self):
        it = _item("flow_reaction")
        self.assertNotIn("Markov3", it["name"])
        self.assertIn("FLOW_CONTEXT_MOVE_M1_V1", it["name"])
        self.assertNotIn("Markowa", it["output"])
        self.assertEqual(it["id"], "flow_reaction")                          # API id unchanged

    def test_markov3_stays_its_own_producer(self):
        from masterquo.quant import ids as I
        self.assertIn("flow:markov3", I.EXTRA_PRODUCERS)
        self.assertEqual(I.resolve("flow_reaction"), "flow:reaction_m1")


# ================================================================================================ atr_vol (I0579)
class TestI0579AtrVol(unittest.TestCase):
    def test_atr_vol_points_to_sh_context(self):
        from masterquo.modelhub import catalog as CAT
        self.assertIn("sh/context.py", CAT.LOCATION["atr_vol"][0])
        self.assertNotIn("strategies/indicators.py", CAT.LOCATION["atr_vol"][0])
        name = _item("atr_vol")["name"]
        self.assertNotIn("StopDistance", name)
        self.assertIn("ATR(14)", name)

    def test_sh_context_atr_is_wilder_14(self):
        """The text matches the code: sh/context._atr(n=14) with Wilder smoothing, used for M1 and M5."""
        import inspect

        from masterquo.sh import context as CX
        self.assertEqual(inspect.signature(CX._atr).parameters["n"].default, 14)
        self.assertIn("Wilder", inspect.getsource(CX._atr))


# ================================================================================================ panel MM (I0384)
class TestI0384CatalogTexts(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_no_reference_to_missing_mm_panel(self):
        from masterquo.modelhub import catalog as CAT
        rows = CAT.build(None, INST)["items"]
        bad = [r["id"] for r in rows if "panel 12" in (r.get("reason") or "")]
        self.assertEqual(bad, [])
        mm = [r for r in rows if r.get("source") == "mm/inventory.MODULES" and not (r.get("reason") or "").startswith("BLOKADA")]
        self.assertTrue(mm)
        for r in mm:
            self.assertIn("/api/v1/mm/", r["reason"])


# ================================================================================================ grupy i osie stanu (I0003)
class TestI0003CatalogGroupsNotDoubleCounted(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    @staticmethod
    def _reg():
        return {"versions": {"TH_LOGREG_M5_H6": [{"version": "v1"}]}, "active": {"TH_LOGREG_M5_H6": "v1"}}

    def _build(self, rt=None):
        from masterquo.modelhub import catalog as CAT
        with mock.patch("masterquo.trainhub.registry.registry", return_value=self._reg()):
            return CAT.build(rt, INST)

    def test_group_rows_are_flagged_and_not_counted(self):
        from masterquo.quant import ids as I
        out = self._build()
        rows = out["items"]
        by = {r["id"]: r for r in rows}
        for gid in I.GROUPS:
            self.assertTrue(by[gid].get("is_group"), gid)
            self.assertEqual(by[gid]["members"], list(I.GROUPS[gid]))
        self.assertFalse(any(r.get("is_group") for r in rows if r["id"] not in I.GROUPS))
        real = [r for r in rows if not r.get("is_group")]
        exp_cat = {}
        for r in real:
            exp_cat[r["category"]] = exp_cat.get(r["category"], 0) + 1
        self.assertEqual(out["counts_by_category"], exp_cat)
        # before: TRAINABLE counted th_direction next to th_logreg (and the lab / si_move groups)
        self.assertEqual(out["counts_by_category"]["TRAINABLE"], sum(1 for r in real if r["category"] == "TRAINABLE"))
        self.assertEqual(sum(out["counts_by_state"].values()), len(real))
        self.assertEqual(out["counts_group_rows"], len(I.GROUPS))
        # the rows themselves stay (ids, category, state unchanged - the panel lists them)
        self.assertEqual(by["th_direction"]["category"], "TRAINABLE")
        self.assertEqual(by["th_direction"]["state"], "READY")

    def test_runtime_state_is_the_raw_probe(self):
        out = self._build()
        by = {r["id"]: r for r in out["items"]}
        th = by["th_direction"]
        self.assertEqual(th["runtime_state"], "SHADOW_ONLY")                   # state READY is the lossy mapping (kept for compatibility)
        self.assertEqual(th["state"], "READY")
        for r in out["items"]:
            self.assertIn("runtime_state", r, r["id"])
            if r.get("source") == "sh/models.REGISTRY":
                self.assertEqual(r["runtime_state"], r["probe_status"], r["id"])
            else:
                self.assertEqual(r["runtime_state"], r["state"], r["id"])         # no probe, no mapping

    def test_use_axis_matches_the_sh_matrix(self):
        from masterquo.sh import models as SM
        out = self._build()
        with mock.patch("masterquo.trainhub.registry.registry", return_value=self._reg()):
            mx = {r["id"]: r for r in SM.matrix(None, INST)["rows"]}
        for r in out["items"]:
            if r.get("source") != "sh/models.REGISTRY":
                self.assertNotIn("use", r, r["id"])
                continue
            self.assertEqual(r["use"], {s: mx[r["id"]][s]["use"] for s in ("SCALPING", "HEDGING")}, r["id"])


if __name__ == "__main__":
    unittest.main()
