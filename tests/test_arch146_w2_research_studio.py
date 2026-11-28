"""Arch 1.46, wave 2, group research_studio: research modules (G7 radar, ETC change features, SDformerFlow freshness, research composite)
and Pepe Data & Training Studio (runner-group metadata / timeframes, AVWAP session profile, launcher data dir / port, CLI data dir).

I0622 (+I0693)  Studio RUNNER:scalp_A runs in .venv_candles and exports only M1 (scalp_train reads <prefix>_M1.csv only).
I0130           runner-group export timeframes come from training/requirements.REQUIREMENTS (base_tf - part of task_key - kept).
I0690           IND_AVWAP_SESSION features use the bot's zones.session_profile (config.json), the profile is written to feature_schema.json.
I0065           36_STUDIO.bat no longer forces MQ_BOT_DATA_DIR=<program>\\data (Studio uses the bot's own default_data_dir rule);
                tools/verify_release reports a Studio launcher that sets it.
I0105           `python -m masterquo studio` (serve) forces MASTERQUO_DATA_DIR = the Studio data dir; Studio dir == bot dir -> refused.
I0139           36_STUDIO.bat opens the browser on the port of the Studio settings; the unreachable second Python check is gone (35_, 36_).
I0803           G7 CheckOB V2: the pair (newest closed, previous) is checked like the source (V1 kept bit for bit for legacy consumers).
I0804           G7 V2: missing M5 / M15 / H1 candles are absent components (None), not 0; coverage counts present ones.
I0805           SDformerFlow V2 features only from a fresh result (module on, PREDICTION_ACTIVE, result of the newest closed H1 bar).
I0806           research composite V2: an input with a non-zero weight missing -> p_event_raw None, state PARTIAL_INPUTS.
I0858           ETC change features V2 compare with the snapshot of bar i-1 (same parameters), not with the last computed one.
Safety: every research output that existed before (rm:* column names, PMW-PRED records, the legacy composite) keeps EXACTLY its
1.46 value - a trained Quant meta-model (ASSIST HOLD) only reads its own feature list, so the V2 columns never reach it.
All market data here is SYNTHETIC (random walk / hand-made candles)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def walk(n: int, seed: int = 7, start: float = 2000.0, step: float = 300.0, t0: float = 1.7e9) -> list[dict]:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 1.5, n))
    out = []
    for k in range(n):
        o = c[k - 1] if k else c[0]
        h, l_ = max(o, c[k]) + abs(rng.normal(0, 0.8)), min(o, c[k]) - abs(rng.normal(0, 0.8))
        out.append({"t": t0 + k * step, "o": float(o), "h": float(h), "l": float(l_), "c": float(c[k]), "tv": 100.0})
    return out


def flat(n: int, step: float = 3600.0, t0: float = 1.7e9, px: float = 100.0) -> list[dict]:
    return [{"t": t0 + k * step, "o": px, "h": px + 0.5, "l": px - 0.5, "c": px, "tv": 1.0} for k in range(n)]


# ================================================================================================================ Studio
# task keys of the runner groups BEFORE this change (registry of commit 5c679ab) - existing Studio tasks / packages keep them
OLD_RUNNER_KEYS = {
    "XAUUSD": {"forecast": "273c8bef05a467d3", "scalp_A": "1c633c3681e9be1e", "ml": "77a23b5dd1d8e759", "lab": "1ffdad7860dc79a3",
               "indicator_context": "eb10b0068f14d37c", "ml_scalp": "b352211ae705dbe4", "neural_scalp": "8b0601d3142034cb",
               "structure_intelligence": "5f88068b5854ee0b", "flow_context": "e3fa85676b8cf6f5", "context_indicators": "4085cf73ec9ed23b",
               "sh_models": "0546117f9aa96d1b", "sh_pack": "34e1f027e3604075", "monte_carlo": "7f068b1ce35d9f84", "master_models": "15696ea5dfe34db2"},
    "BTC": {"forecast": "880d7cb989027567", "scalp_A": "dde4a78776a7b7f1", "ml": "95f1f4f13acab967", "lab": "6ad6622e264ff430",
            "indicator_context": "5aa0098c9e609ee3", "ml_scalp": "dee0b271c01171a8", "neural_scalp": "32d28ade7d3e14cf",
            "structure_intelligence": "a839c0ad28976b80", "flow_context": "6827ad57c1290a3a", "context_indicators": "268e36181278b7e2",
            "sh_models": "62bdc64fa4d6e6e8", "sh_pack": "42719f07a0fab484", "monte_carlo": "6b75f1c23c856b8e", "master_models": "fa524c04e1486341"},
}
OLD_BASE_TF = {"forecast": "M5", "scalp_A": "M1", "ml": "M5", "lab": "M1", "indicator_context": "M1", "ml_scalp": "M1", "neural_scalp": "M1",
               "structure_intelligence": "M1", "flow_context": "M1", "context_indicators": "M5", "sh_models": "M1", "sh_pack": "M1",
               "monte_carlo": "M1", "master_models": "M5"}


class TestStudioRunnerGroupMetadata(unittest.TestCase):                                     # I0622 (+I0693)
    def test_scalp_a_env_and_timeframes(self):
        from masterquo.studio import registry as R
        _, _, env, tfs = R.RUNNER_GROUPS["scalp_A"]
        self.assertEqual(env, ".venv_candles")                  # training/runner.py t_scalp: core.candles_python()
        self.assertEqual(tfs, ["M1"])                           # gold_candles_runtime/scalp_train.py reads <prefix>_M1.csv only
        self.assertEqual(R.RUNNER_GROUPS["forecast"][2], ".venv_candles")
        for kind, (_, _, e, _) in R.RUNNER_GROUPS.items():
            if kind not in ("forecast", "scalp_A"):
                self.assertEqual(e, ".venv", kind)            # every other runner step runs core.bot_python()

    def test_task_keys_unchanged(self):
        from masterquo.studio import registry as R
        got = {(t["instrument"], t["task_id"]): t["task_key"] for t in R.tasks() if t["adapter"] == "RUNNER_GROUP"}
        for inst, keys in OLD_RUNNER_KEYS.items():
            for kind, h in keys.items():
                self.assertEqual(got[(inst, kind)], f"RUNNER:{kind}:{inst}:{OLD_BASE_TF[kind]}:HNone:{h}")
        sa = next(t for t in R.tasks() if t["model_id"] == "RUNNER:scalp_A" and t["instrument"] == "XAUUSD")
        self.assertEqual(sa["env"], ".venv_candles")
        self.assertEqual([s["tf"] for s in sa["sources"]], ["M1"])


class TestStudioRunnerGroupTfs(unittest.TestCase):                                           # I0130
    def test_timeframes_cover_the_trainers_requirements(self):
        from masterquo.studio import pipeline as P
        from masterquo.studio import registry as R
        from masterquo.training.requirements import REQUIREMENTS
        for kind, (_, _, _, tfs) in R.RUNNER_GROUPS.items():
            rq = REQUIREMENTS["scalp" if kind == "scalp_A" else kind]
            self.assertEqual(tfs[0], OLD_BASE_TF[kind], kind)                                  # base_tf (task_key) unchanged
            self.assertTrue(set(rq["required"]) <= set(tfs), (kind, tfs, rq["required"]))
            self.assertTrue(set(tfs) <= {OLD_BASE_TF[kind], *rq["required"], *rq["optional"]}, (kind, tfs))
            self.assertEqual(len(tfs), len(set(tfs)), kind)
        t = next(x for x in R.tasks() if x["model_id"] == "RUNNER:ml" and x["instrument"] == "XAUUSD")
        self.assertEqual(P.needed_tfs(t), ["M1", "M5", "M15", "H1", "H4", "D1"])               # ml/offline.py NEED
        for kind, need in (("indicator_context", {"M15"}), ("neural_scalp", {"M15", "H1"}), ("structure_intelligence", {"H1"}),
                           ("master_models", {"M1"})):
            t = next(x for x in R.tasks() if x["model_id"] == f"RUNNER:{kind}" and x["instrument"] == "BTC")
            self.assertTrue(need <= set(P.needed_tfs(t)), kind)


class TestStudioAvwapSessionProfile(unittest.TestCase):                                     # I0690
    def bars(self):
        t0 = datetime(2026, 1, 13, 6, 0, tzinfo=UTC).timestamp()         # Tuesday, winter time
        return [{"t": t0 + k * 300, "o": 100.0 + k * 0.01, "h": 100.5 + k * 0.01, "l": 99.5 + k * 0.01, "c": 100.0 + k * 0.01, "tv": 10.0}
                for k in range(12 * 14)]                                                       # 06:00 - 20:00 UTC M5

    def cfg(self, prof):
        return types.SimpleNamespace(zones=types.SimpleNamespace(session_profile={"XAUUSD": prof, "BTC": "LAB_BTC_REFERENCE_V1"}))

    def sessions(self, prof, bars):
        from masterquo.analytics import session_engine as SE
        out = []
        for b in bars:
            ws = [w for w in SE.windows(prof, b["t"], 1, 0) if w["start"].timestamp() <= b["t"] < w["end"].timestamp()]
            out.append(ws[-1]["session"] if ws else "")
        return out

    def test_bot_profile_is_used(self):
        from masterquo.studio import pipeline as P
        bars = self.bars()
        task = {"model_id": "IND_AVWAP_SESSION", "instrument": "XAUUSD", "base_tf": "M5"}
        rows = P.deterministic_features(task, bars, None, self.cfg("SCALP_OPENING_V1"))
        got = [r["session"] for r in rows]
        self.assertEqual(got, self.sessions("SCALP_OPENING_V1", bars))
        self.assertNotEqual(got, self.sessions("LAB_XAU_REFERENCE_V1", bars))     # the profile matters for this window
        self.assertEqual(P.avwap_session_profile(task, self.cfg("SCALP_OPENING_V1")), "SCALP_OPENING_V1")

    def test_without_bot_config_the_reference_profile(self):
        from masterquo.studio import pipeline as P
        bars = self.bars()
        task = {"model_id": "IND_AVWAP_SESSION", "instrument": "XAUUSD", "base_tf": "M5"}
        self.assertEqual([r["session"] for r in P.deterministic_features(task, bars, None)], self.sessions("LAB_XAU_REFERENCE_V1", bars))
        self.assertEqual(P.avwap_session_profile({**task, "instrument": "BTC"}, None), "LAB_BTC_REFERENCE_V1")
        # the bot's own rule for an instrument missing in the mapping (indicators/service.py _profile_id): LAB_XAU_REFERENCE_V1
        cfg = types.SimpleNamespace(zones=types.SimpleNamespace(session_profile={}))
        self.assertEqual(P.avwap_session_profile({**task, "instrument": "BTC"}, cfg), "LAB_XAU_REFERENCE_V1")
        with self.assertRaises(P.Blocked):
            P.avwap_session_profile(task, self.cfg("NO_SUCH_PROFILE"))

    def test_profile_in_the_package_schema(self):
        from masterquo.modelhub.families import base as FB
        from masterquo.studio import pipeline as P
        from masterquo.studio.package import Package, read_json
        task = {"model_id": "IND_AVWAP_SESSION", "instrument": "XAUUSD", "base_tf": "M5", "adapter": "DETERMINISTIC"}
        bars = self.bars()
        with tempfile.TemporaryDirectory() as d:
            pkg = Package(Path(d), task, "R1")
            ctx = P.Ctx(task, pkg, source={"mode": "OFFLINE"}, cfg_store=types.SimpleNamespace(get=lambda: self.cfg("SCALP_OPENING_V1")))
            with mock.patch.object(FB, "bars_from_store", return_value=bars):
                P.stage_build_dataset(ctx)
            self.assertEqual(read_json(pkg.dir / "feature_schema.json")["session_profile"], "SCALP_OPENING_V1")
            with (pkg.dir / "dataset" / "build_dataset" / "features.csv").open(encoding="utf-8") as f:
                rows = [ln.split(",")[1] for ln in f.read().splitlines()[1:]]
            self.assertEqual(rows, self.sessions("SCALP_OPENING_V1", bars))


def _bat(name: str) -> str:
    return (ROOT / name).read_bytes().decode("ascii")


class TestStudioBatDataDir(unittest.TestCase):                                              # I0065
    def test_launcher_does_not_force_the_bot_data_dir(self):
        txt = _bat("36_STUDIO.bat").lower()
        self.assertNotIn('set "mq_bot_data_dir=', txt)
        self.assertIn('set "mq_studio_data_dir=', txt)
        self.assertIn('set "masterquo_data_dir=', txt)

    def test_desktop_folder_uses_the_bots_rule(self):
        from masterquo import paths
        from masterquo.studio import settings as S
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "PepeMarketWizard_Desktop"
            root.mkdir()
            (root / "PepeMarketWizardDesktop.exe").write_bytes(b"MZ")
            env = {k: v for k, v in os.environ.items() if k not in ("MQ_BOT_DATA_DIR", "PMW_HOME")}
            env["LOCALAPPDATA"] = str(Path(d) / "lad")
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(paths, "ROOT_DIR", root):
                self.assertEqual(S.bot_data_dir({"bot_data_dir": None}), Path(d) / "lad" / "PepeMarketWizard" / "data")

    def test_verify_release_reports_a_forced_bot_dir(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import verify_release as V
        bad = b'@echo off\r\nset "MQ_BOT_DATA_DIR=%~dp0data"\r\n"%PY%" -m masterquo studio\r\n'
        self.assertTrue(V.studio_launcher_problems(lambda r: bad, {"36_STUDIO.bat": None}))
        self.assertEqual(V.studio_launcher_problems(lambda r: (ROOT / r).read_bytes(), {"36_STUDIO.bat": None}), [])
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "Apollo23_TEST.zip"
            with zipfile.ZipFile(z, "w") as zz:
                zz.writestr("P/36_STUDIO.bat", bad)
            self.assertTrue(any("MQ_BOT_DATA_DIR" in p for p in V.check_zip(z)))


class TestStudioServeDataDir(unittest.TestCase):                                            # I0105
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("MQ_STUDIO_DATA_DIR", "MQ_BOT_DATA_DIR", "MASTERQUO_DATA_DIR")}

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.td.cleanup()

    def test_serve_forces_the_studio_data_dir(self):
        from masterquo.studio import app as A
        studio, bot = Path(self.td.name) / "studio", Path(self.td.name) / "bot"
        bot.mkdir()
        os.environ.update(MQ_STUDIO_DATA_DIR=str(studio), MQ_BOT_DATA_DIR=str(bot), MASTERQUO_DATA_DIR=str(bot))
        seen = {}

        def fake_app():
            seen["env"] = os.environ.get("MASTERQUO_DATA_DIR")
            return object()
        with mock.patch.object(A, "create_app", side_effect=fake_app), mock.patch("uvicorn.run") as run:
            rc = A.serve(18999)
        self.assertEqual(rc, 0)
        self.assertEqual(seen["env"], str(studio))
        self.assertEqual(os.environ["MASTERQUO_DATA_DIR"], str(studio))
        run.assert_called_once()

    def test_studio_dir_equal_to_the_bot_dir_is_refused(self):
        from masterquo.studio import app as A
        same = Path(self.td.name) / "data"
        same.mkdir()
        os.environ.update(MQ_STUDIO_DATA_DIR=str(same), MQ_BOT_DATA_DIR=str(same), MASTERQUO_DATA_DIR=str(same))
        with mock.patch.object(A, "create_app") as ca, mock.patch("uvicorn.run") as run:
            rc = A.serve(18999)
        self.assertEqual(rc, 2)
        ca.assert_not_called()
        run.assert_not_called()


class TestStudioBatPort(unittest.TestCase):                                                 # I0139
    def test_browser_port_from_settings(self):
        txt = _bat("36_STUDIO.bat")
        starts = [ln for ln in txt.splitlines() if ln.strip().lower().startswith("start ")]
        self.assertEqual(len(starts), 1)
        self.assertNotIn("127.0.0.1:8780", starts[0])
        self.assertIn("%PORT%", starts[0])
        self.assertIn("masterquo.studio.settings", txt)
        self.assertIn('if not defined PORT set "PORT=8780"', txt)

    def test_one_python_check(self):
        for name in ("35_RODZINY_MODELI.bat", "36_STUDIO.bat"):
            self.assertEqual(_bat(name).count('if not exist "%PY%"'), 1, name)

    def test_bat_files_ascii_crlf(self):
        for name in ("35_RODZINY_MODELI.bat", "36_STUDIO.bat"):
            raw = (ROOT / name).read_bytes()
            raw.decode("ascii")
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)

    def test_settings_module_prints_the_port(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "settings.json").write_text(json.dumps({"port": 8899}), encoding="utf-8")
            env = dict(os.environ, MQ_STUDIO_DATA_DIR=d, PYTHONPATH=str(ROOT / "backend"))
            r = subprocess.run([PY, "-m", "masterquo.studio.settings"], cwd=str(ROOT / "backend"), env=env, capture_output=True, text=True,
                               timeout=120, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "8899")


# ================================================================================================================ research: G7
def ob_case(newest: bool) -> list[dict]:
    """50 flat H1 bars + a bearish bar (body 1) followed by a bullish bar (body 2): on the newest closed pair, or one bar earlier."""
    bars = flat(50)
    t = bars[-1]["t"]
    pair = [{"t": t + 3600, "o": 101.0, "h": 101.2, "l": 99.8, "c": 100.0, "tv": 1.0},       # bearish, body 1
            {"t": t + 7200, "o": 100.0, "h": 102.2, "l": 99.9, "c": 102.0, "tv": 1.0}]       # bullish, body 2 > 1.5 x 1
    tail = [] if newest else [{"t": t + 10800, "o": 102.0, "h": 102.1, "l": 101.9, "c": 102.0, "tv": 1.0}]
    return bars + pair + tail


class TestG7CheckObNewestPair(unittest.TestCase):                                           # I0803
    def test_newest_closed_pair_is_an_order_block(self):
        from masterquo.research import g7 as G7
        self.assertEqual(G7.check_ob(ob_case(newest=True)), 1)
        self.assertEqual(G7.check_ob(ob_case(newest=False)), 1)                               # one bar earlier: still found
        self.assertEqual(G7.VERSION, "PMW_G7_SRC_PORT_V2")

    def test_legacy_v1_kept_for_trained_inputs(self):
        from masterquo.research import g7 as G7
        self.assertEqual(G7.check_ob_v1(ob_case(newest=True)), 0)                             # V1 skipped the newest pair (1.46 value)
        self.assertEqual(G7.check_ob_v1(ob_case(newest=False)), 1)
        h1 = ob_case(newest=True)
        m5 = walk(60)
        r1 = G7.radar_v1(m5, m5, h1, None)
        r2 = G7.radar(m5, m5, h1, None)
        self.assertEqual(r1["implementation_id"], "PMW_G7_SRC_PORT_V1")
        self.assertEqual(r1["components"]["ob_h1"], 0)
        self.assertEqual(r2["components"]["ob_h1"], 1)
        self.assertEqual(r2["implementation_id"], "PMW_G7_SRC_PORT_V2")

    def test_source_window_is_13_pairs(self):
        from masterquo.research import g7 as G7

        def ob_at(k: int) -> list[dict]:                 # bearish bar s[k+1], bullish bar s[k] (s[0] = newest closed)
            bars = flat(66)
            n = len(bars)
            bars[n - 2 - k] = dict(bars[n - 2 - k], o=101.0, c=100.0, h=101.2, l=99.8)
            bars[n - 1 - k] = dict(bars[n - 1 - k], o=100.0, c=102.0, h=102.2, l=99.9)
            return bars
        # source (rates[0] = forming bar) i = 2..14 -> pairs (s[1], s[0]) .. (s[13], s[12]); V1 looked at (s[2], s[1]) .. (s[14], s[13])
        for k, v2, v1 in ((0, 1, 0), (1, 1, 1), (12, 1, 1), (13, 0, 1)):
            self.assertEqual(G7.check_ob(ob_at(k)), v2, k)
            self.assertEqual(G7.check_ob_v1(ob_at(k)), v1, k)


class TestG7MissingTfNotZero(unittest.TestCase):                                            # I0804
    def test_missing_timeframes_are_absent(self):
        from masterquo.research import g7 as G7
        m5 = walk(60)
        r = G7.radar(m5, [], [], None)
        self.assertIsNone(r["components"]["fvg_m15"])
        self.assertIsNone(r["components"]["ob_h1"])
        self.assertIsNone(r["rule_confluence_score"])
        self.assertLessEqual(r["coverage"], 0.5)
        self.assertEqual(r["state"], "BLOCKED_DATA")
        self.assertIn("H1", r["reason"])
        self.assertIsNone(G7.check_fvg(m5[:3]))
        self.assertIsNone(G7.check_ob(flat(20)))

    def test_m15_missing_partial_score_from_present_components(self):
        from masterquo.research import g7 as G7
        m5 = walk(60)
        h1 = ob_case(newest=True)
        r = G7.radar(m5, [], h1, None)
        fm5 = G7.check_fvg(m5)
        exp = (30 if fm5 > 0 else -30 if fm5 < 0 else 0) + 40
        if fm5 < 0:
            exp = int(exp * 0.5)
        self.assertEqual(r["rule_confluence_score"], float(exp))
        self.assertEqual(r["components"]["net_fvg"], fm5)
        self.assertEqual(r["coverage"], 0.5)

    def test_legacy_v1_still_zero_and_three_quarters(self):
        from masterquo.research import g7 as G7
        r = G7.radar_v1(walk(60), [], [], None)
        self.assertEqual((r["components"]["fvg_m15"], r["components"]["ob_h1"], r["coverage"]), (0, 0, 0.75))


# ================================================================================================================ research: service
class _Svc(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def svc(self, patch=None):
        from masterquo.research import service as RS
        rt = types.SimpleNamespace(demo=True, bridge=None, sh=types.SimpleNamespace(instrument=lambda: "XAUUSD"))
        s = RS.ResearchModulesService(rt, data_dir=Path(self.td.dir) / "research")
        s.update_settings({"optimizer": {"enabled": False}, **(patch or {})})
        return s

    def ctx(self, svc, data: dict, st: dict):
        from masterquo.research import service as RS
        c = RS.Context("K", "XAUUSD", lambda tf, n=1500: data.get(tf, [])[: st.get(tf, len(data.get(tf, [])))][-n:])
        svc.contexts = {"K": c}
        svc.ensure_main_context = lambda: c
        return c


class TestEtcPrevIsBarIMinus1(_Svc):                                                        # I0858
    def test_change_features_after_a_gap(self):
        from masterquo.research import etc as ETC
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "cellular_feature_graph", "g7_smc_radar")}})
        m5 = walk(700)
        st = {"M5": 400}
        c = self.ctx(svc, {"M5": m5}, st)
        svc._cycle_ctx(c)
        st["M5"] = 403                                                                         # 2 bars never seen (gap / restart)
        svc._cycle_ctx(c)
        p = {k: svc.settings()["etc"][k] for k in ("price", "window_set", "width")}
        cur = m5[:403][-1500:]
        want = ETC.snapshot(cur, len(cur) - 1, p, ETC.snapshot(cur, len(cur) - 2, p))["features"]
        legacy = ETC.snapshot(cur, len(cur) - 1, p, ETC.snapshot(m5[:400], 399, p))["features"]
        mod = c.snaps[-1]["modules"]["exponential_trend_channel"]
        v2 = mod["change_v2"]
        self.assertAlmostEqual(v2["etc_fit_change"], want["etc_fit_change"], places=12)
        self.assertEqual(v2["etc_window_change_flag"], want["etc_window_change_flag"])
        self.assertEqual(v2["prev_bar_t"], cur[-2]["t"])
        for k in ("etc_fit_change", "etc_window_change_flag"):                                 # legacy features: 1.46 value unchanged
            self.assertEqual(mod["M5"]["features"][k], legacy[k])
        f = svc.features_for("XAUUSD", None)
        self.assertEqual(f["etc_fit_change_v2"], v2["etc_fit_change"])
        self.assertEqual(f["etc_fit_change"], legacy["etc_fit_change"])

    def test_next_bar_reuses_the_cached_snapshot_and_param_change_recomputes(self):
        from masterquo.research import etc as ETC
        from masterquo.research import service as RS
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "cellular_feature_graph", "g7_smc_radar")}})
        m5 = walk(700)
        st = {"M5": 400}
        c = self.ctx(svc, {"M5": m5}, st)
        svc._cycle_ctx(c)
        st["M5"] = 401
        with mock.patch.object(RS.ETC, "snapshot", wraps=ETC.snapshot) as sp:
            svc._cycle_ctx(c)
        self.assertEqual(sp.call_count, 1)                                                     # i-1 = the cached snapshot
        svc.update_settings({"etc": {"width": 3.0}})
        st["M5"] = 402
        with mock.patch.object(RS.ETC, "snapshot", wraps=ETC.snapshot) as sp:
            svc._cycle_ctx(c)
        self.assertEqual(sp.call_count, 2)                                                     # other parameters -> i-1 recomputed
        p = {k: svc.settings()["etc"][k] for k in ("price", "window_set", "width")}
        cur = m5[:402]
        want = ETC.snapshot(cur, 401, p, ETC.snapshot(cur, 400, p))["features"]
        self.assertAlmostEqual(c.snaps[-1]["modules"]["exponential_trend_channel"]["change_v2"]["etc_fit_change"], want["etc_fit_change"], places=12)


class TestG7InService(_Svc):                                                                # I0803 / I0804 in the service
    def test_legacy_columns_unchanged_and_v2_separate(self):
        from masterquo.research import g7 as G7
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "cellular_feature_graph", "exponential_trend_channel")}})
        m5 = walk(80)
        c = self.ctx(svc, {"M5": m5, "M15": [], "H1": []}, {})
        svc._cycle_ctx(c)
        g = c.snaps[-1]["modules"]["g7_smc_radar"]
        legacy = G7.radar_v1(m5[-60:], [], [], None, svc.settings()["g7"])
        self.assertEqual({k: g[k] for k in legacy}, legacy)                                   # main fields = 1.46 output bit for bit
        self.assertIsNone(g["v2"]["rule_confluence_score"])
        f = svc.features_for("XAUUSD", None)
        self.assertEqual(f["g7_rule_confluence"], legacy["rule_confluence_score"] / 100.0)
        self.assertEqual((f["g7_net_fvg"], f["g7_ob_h1"]), (float(legacy["components"]["net_fvg"]), 0.0))
        self.assertNotIn("g7_v2_rule_confluence", f)
        self.assertNotIn("g7_v2_ob_h1", f)
        rec = next(p for p in svc.predictions("XAUUSD") if p["model_name"] == "research:g7_smc_radar")
        self.assertEqual((rec["state"], rec["result"]["raw_score"]), ("READY", legacy["rule_confluence_score"]))

    def test_v2_columns_when_data_present(self):
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "cellular_feature_graph", "exponential_trend_channel")}})
        m5, h1 = walk(80), ob_case(newest=True)
        c = self.ctx(svc, {"M5": m5, "M15": walk(80, step=900), "H1": h1}, {})
        svc._cycle_ctx(c)
        g = c.snaps[-1]["modules"]["g7_smc_radar"]
        f = svc.features_for("XAUUSD", None)
        self.assertEqual(f["g7_v2_ob_h1"], 1.0)
        self.assertEqual(f["g7_ob_h1"], 0.0)                                                  # legacy (shifted) value kept
        self.assertEqual(f["g7_v2_rule_confluence"], g["v2"]["rule_confluence_score"] / 100.0)


SDF_RES = {"direction_score_raw": 0.4, "forecast_body_6": [0.1] * 6, "atr14": 1.0, "embedding8": [0.5] * 8, "run_id": "SDF-X", "ms": 3}


class TestSdfStaleNotPublished(_Svc):                                                       # I0805
    def run_cycle(self, svc, sdf, *, h1_n=700):
        m5, h1 = walk(80), walk(h1_n, step=3600, t0=1.7e9 - 3600 * 650)
        c = self.ctx(svc, {"M5": m5, "H1": h1}, {})
        c.sdf = sdf(h1)
        c.last_h1 = h1[-1]["t"]                                                                # no new H1 bar: no inference process
        svc._cycle_ctx(c)
        return c

    def test_error_state_with_an_old_result(self):
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("cellular_feature_graph", "g7_smc_radar", "exponential_trend_channel")}})
        c = self.run_cycle(svc, lambda h1: {"state": "ERROR", "active_run": "SDF-X", "reason": "x",
                                            "result": {**SDF_RES, "bar_t": h1[-3]["t"]}})
        f = svc.features_for("XAUUSD", None)
        self.assertNotIn("sdf_v2_direction_raw", f)
        self.assertFalse(c.snaps[-1]["modules"]["sdformerflow"]["fresh_v2"])
        self.assertEqual(f["sdf_direction_raw"], 0.4)                                          # legacy column: 1.46 value unchanged
        rec = next(p for p in svc.predictions("XAUUSD") if p["model_name"] == "research:sdformerflow")
        self.assertEqual(rec["state"], "READY")                                                # legacy record unchanged (Quant inputs)
        self.assertFalse(rec["result_fresh"])

    def test_fresh_result_and_module_off(self):
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("cellular_feature_graph", "g7_smc_radar", "exponential_trend_channel")}})
        c = self.run_cycle(svc, lambda h1: {"state": "PREDICTION_ACTIVE", "active_run": "SDF-X", "result": {**SDF_RES, "bar_t": h1[-1]["t"]}})
        f = svc.features_for("XAUUSD", None)
        self.assertEqual(f["sdf_v2_direction_raw"], 0.4)
        self.assertEqual(f["sdf_v2_emb7"], 0.5)
        self.assertTrue(c.snaps[-1]["modules"]["sdformerflow"]["fresh_v2"])
        rec = next(p for p in svc.predictions("XAUUSD") if p["model_name"] == "research:sdformerflow")
        self.assertTrue(rec["result_fresh"])
        self.assertEqual(rec["result_data_time"], datetime.fromtimestamp(c.sdf["result"]["bar_t"] + 3600, UTC).isoformat(timespec="seconds"))
        svc.update_settings({"modules": {"sdformerflow": {"enabled": False}}})
        c = self.run_cycle(svc, lambda h1: {"state": "PREDICTION_ACTIVE", "active_run": "SDF-X", "result": {**SDF_RES, "bar_t": h1[-1]["t"]}})
        f = svc.features_for("XAUUSD", None)
        self.assertNotIn("sdf_v2_direction_raw", f)
        self.assertIn("sdf_direction_raw", f)                                                  # legacy kept as in 1.46


class TestCompositePartialInputs(_Svc):                                                     # I0806
    def test_missing_weighted_input(self):
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "exponential_trend_channel")}})
        svc._set_composite({"version": "C-T", "weights": [0.1, 1.0, 0.5, 0.0], "status": "TEST"}, who="test")
        m5 = walk(400)
        c = self.ctx(svc, {"M5": m5, "M15": walk(80, step=900), "H1": walk(120, step=3600)}, {})
        svc._cycle_ctx(c)
        sn = c.snaps[-1]
        self.assertIsNotNone(sn["composite"]["p_event_raw"])                                   # legacy (0.0 fill): 1.46 value
        self.assertEqual(sn["composite"]["inputs"]["etc_position_z_closed"], 0.0)
        v2 = sn["composite_v2"]
        self.assertIsNone(v2["p_event_raw"])
        self.assertEqual(v2["state"], "PARTIAL_INPUTS")
        self.assertIsNone(v2["inputs"]["etc_position_z_closed"])
        self.assertTrue(v2["mask"]["etc_position_z_closed"])
        f = svc.features_for("XAUUSD", None)
        self.assertIn("research_composite_p_raw", f)
        self.assertNotIn("research_composite_v2_p_raw", f)

    def test_complete_inputs_match_the_legacy_value(self):
        svc = self.svc({"modules": {"sdformerflow": {"enabled": False}}})
        svc._set_composite({"version": "C-T", "weights": [0.1, 1.0, 0.5, 0.0], "status": "TEST"}, who="test")
        m5 = walk(400)
        c = self.ctx(svc, {"M5": m5, "M15": walk(80, step=900), "H1": walk(120, step=3600)}, {})
        svc._cycle_ctx(c)
        sn = c.snaps[-1]
        self.assertEqual(sn["composite_v2"]["state"], "READY")
        self.assertAlmostEqual(sn["composite_v2"]["p_event_raw"], sn["composite"]["p_event_raw"], places=15)
        self.assertEqual(svc.features_for("XAUUSD", None)["research_composite_v2_p_raw"], sn["composite_v2"]["p_event_raw"])

    def test_optimizer_rows_still_the_legacy_inputs(self):
        svc = self.svc({"modules": {m: {"enabled": False} for m in ("sdformerflow", "exponential_trend_channel")}})
        m5 = walk(500)
        st = {"M5": 400}
        c = self.ctx(svc, {"M5": m5}, st)
        for k in range(15):
            st["M5"] = 400 + k
            svc._cycle_ctx(c)
        rows = svc._objective_rows(c)
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(r[0]["etc_position_z_closed"], float) for r in rows))   # 1.46 rows (0.0 fill), weights unchanged


class TestOldQuantArtifactsGetTheSameInputs(_Svc):                                          # safety: no fail-open through Quant
    def test_metamodel_ignores_the_v2_columns(self):
        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        names = ["rm:g7_rule_confluence", "rm:g7_ob_h1", "rm:etc_fit_change", "rm:sdf_direction_raw", "rm:research_composite_p_raw", "plan:side_long"]
        n = len(names)
        model = {"feature_names": names, "scaler": {"mean": [0.0] * 2 * n, "scale": [1.0] * 2 * n},
                 "logit": {"coef": list(np.linspace(-1, 1, 2 * n)), "intercept": 0.1}, "calibrator": {"kind": "identity"}, "ridge": None}
        base = {"rm:g7_rule_confluence": 0.3, "rm:g7_ob_h1": 0.0, "rm:etc_fit_change": 0.01, "rm:sdf_direction_raw": 0.4,
                "rm:research_composite_p_raw": 0.55, "plan:side_long": 1.0}
        extra = {"rm:g7_v2_rule_confluence": -0.7, "rm:g7_v2_ob_h1": -1.0, "rm:etc_fit_change_v2": 0.2, "rm:sdf_v2_direction_raw": -0.9,
                 "rm:research_composite_v2_p_raw": 0.1, "rm:etc_window_change_flag_v2": 1.0}
        self.assertEqual(M.predict(model, base)["p_event"], M.predict(model, {**base, **extra})["p_event"])
        cd = {"direction": "LONG", "research_features": {k[3:]: v for k, v in {**base, **extra}.items() if k.startswith("rm:")}}
        feats = F.build2(cd, [])
        for k in extra:
            self.assertIn(k, feats)                                                            # new semantics under NEW names only
        for k, v in base.items():
            if k.startswith("rm:"):
                self.assertEqual(feats[k], v)

    def test_full_cycle_legacy_features_equal_head_semantics(self):
        """features_for of the legacy names = the 1.46 computation (radar V1, ETC change vs the last computed snapshot, composite with
        0.0 fill) on a run with gaps and missing M15 / H1."""
        from masterquo.research import etc as ETC
        from masterquo.research import g7 as G7
        svc = self.svc({"modules": {"sdformerflow": {"enabled": False}}})
        svc._set_composite({"version": "C-T", "weights": [0.1, 1.0, 0.5, 0.3], "status": "TEST"}, who="test")
        m5 = walk(600)
        st = {"M5": 400}
        c = self.ctx(svc, {"M5": m5, "M15": [], "H1": []}, st)
        prev = None
        p = {k: svc.settings()["etc"][k] for k in ("price", "window_set", "width")}
        for n in (400, 401, 404, 405, 409):
            st["M5"] = n
            svc._cycle_ctx(c)
            cur = m5[:n][-1500:]
            e5 = ETC.snapshot(cur, len(cur) - 1, p, prev)
            prev = e5
            r = G7.radar_v1(cur[-60:], [], [], None, svc.settings()["g7"])
            f = svc.features_for("XAUUSD", None)
            for k, v in e5["features"].items():
                if v is not None:
                    self.assertEqual(f[k], v, (n, k))
            self.assertEqual(f["g7_rule_confluence"], r["rule_confluence_score"] / 100.0)
            g = c.snaps[-1]["modules"]["cellular_feature_graph"]["targets"]["BPC10"]["raw_score"]
            e = e5["features"]["etc_position_z_closed"]
            x = [1.0, g, e if e is not None else 0.0, r["rule_confluence_score"] / 100.0]
            z = sum(wi * xi for wi, xi in zip([0.1, 1.0, 0.5, 0.3], x))
            self.assertAlmostEqual(f["research_composite_p_raw"], 1 / (1 + np.exp(-max(-30, min(30, z)))), places=15)
            self.assertNotIn("g7_v2_rule_confluence", f)                                      # H1 missing: V2 score absent


if __name__ == "__main__":
    unittest.main()
