"""1.46 arch, wave 2, group platform_misc - regression tests (each class names the item key it covers).

I0866  agent: an answer to a USER_QUESTION can only make the AI gate stricter (never replaces the setup assessment)
I0867  agent: model without a price -> warning BUDGET_NOT_ENFORCEABLE_UNKNOWN_PRICE (budget / preflight unchanged)
I0152  agent: claude-fable-5-2 in FALLBACK_MODELS, no server-side fallback under REQUIRED, cost shown as an estimate only
"""
import asyncio
import json
import os
import unittest

import _env

SETUP_NOW = "2026-10-08T12:01:00Z"


class _AgentBase(unittest.TestCase):
    def setUp(self):
        import test_agent as TA
        self.TA = TA
        self.t = TA.TestAgent("test_veto_policy")
        self.t.setUp()
        self.agent = self.t.agent
        self.cfg = self.t.cfg
        self.agent.loop = None

    def tearDown(self):
        self.t.tearDown()

    def handle(self, trigger, ans=None, *, script=None, question=None, key=None):
        TA = self.TA
        client = TA.ScriptedClient(script or [TA.msg([TA.text(json.dumps(ans))], "end_turn")])
        self.agent._client_get = lambda: client
        self.agent.last_auto_run = self.agent.last_user_run = 0
        req = {"trigger": trigger, "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": question,
               "key": key or trigger}
        asyncio.run(self.agent._handle(req))
        return client

    def gate(self, now=SETUP_NOW):
        return self.agent.gate_for(self.TA.CTX["setup"], session_epoch=1, account_key="srv:1", now_iso=now)


# ------------------------------------------------------------------ I0866
class TestI0866UserQuestionOnlyBlocks(_AgentBase):
    """1.45: the USER_QUESTION result replaced by_setup - a BUY answer lifted the AI veto of a confirmed setup (and a missing assessment
    was replaced by the answer); a question started during an assessment marked it SUPERSEDED."""

    def test_question_buy_does_not_lift_veto(self):
        TA = self.TA
        self.handle("SETUP_CONFIRMED", TA.answer(proposed_action="WAIT"))           # assessment: veto
        self.assertEqual(self.gate()["status"], "DISAGREE")
        self.handle("USER_QUESTION", TA.answer(answer_pl="Ryzyka: ..."), question="Jakie ryzyka?")   # answer SELL (= setup side)
        self.assertEqual(self.gate()["status"], "DISAGREE")                         # 1.45: PASS (veto lifted)
        self.assertEqual(self.agent.by_setup["MQS-1"]["record"]["proposed_action"], "WAIT")
        self.assertEqual(self.agent.by_question["MQS-1"]["status_note"], "USER_QUESTION_ANSWER_CAN_ONLY_BLOCK")

    def test_question_wait_still_blocks(self):                                       # guard: today's block stays
        TA = self.TA
        self.handle("SETUP_CONFIRMED", TA.answer())
        self.assertEqual(self.gate()["status"], "PASS")
        self.handle("USER_QUESTION", TA.answer(proposed_action="WAIT"), question="Czekać?")
        g = self.gate()
        self.assertEqual(g["status"], "DISAGREE")
        self.assertIn("AI_USER_QUESTION_ANSWER", g["reason_codes"])
        self.cfg.update({"agent": {"gate_policy": "REQUIRED"}})
        self.assertEqual(self.gate()["status"], "DISAGREE")

    def test_question_without_assessment_never_passes(self):
        TA = self.TA
        self.cfg.update({"agent": {"gate_policy": "REQUIRED"}})
        self.handle("USER_QUESTION", TA.answer(), question="Wejść?")
        g = self.gate()
        self.assertEqual(g["status"], "PENDING")                                    # 1.45: PASS from the answer alone
        self.assertIn("AI_ASSESSMENT_MISSING", g["reason_codes"])

    def test_failed_question_still_fails_like_before(self):
        TA = self.TA
        import anthropic
        import httpx2
        self.cfg.update({"agent": {"gate_policy": "REQUIRED"}})
        self.handle("SETUP_CONFIRMED", TA.answer())
        self.handle("USER_QUESTION", script=[anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x"))], question="?")
        self.assertEqual(self.gate()["status"], "FAIL")                             # same block as 1.45 (the TIMEOUT answer counted)

    def test_newer_assessment_supersedes_older_question(self):
        TA = self.TA
        self.handle("USER_QUESTION", TA.answer(proposed_action="WAIT"), question="?")
        self.handle("SETUP_CONFIRMED", TA.answer())
        self.assertEqual(self.gate()["status"], "PASS")                             # same as 1.45 (the newer assessment replaced it)

    def test_question_started_during_assessment_keeps_assessment(self):
        TA = self.TA

        async def scenario():
            slow = asyncio.Event()

            class Slow(TA.ScriptedClient):
                async def create(self, **kw):
                    await slow.wait()
                    return TA.msg([TA.text(json.dumps(TA.answer(proposed_action="WAIT")))], "end_turn")
            fast = TA.ScriptedClient([TA.msg([TA.text(json.dumps(TA.answer(answer_pl="ok")))], "end_turn")])
            clients = {"c": Slow([])}
            self.agent._client_get = lambda: clients["c"]
            req = {"trigger": "SETUP_CONFIRMED", "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": None,
                   "key": "a"}
            t1 = asyncio.create_task(self.agent._handle(dict(req)))
            await asyncio.sleep(0.05)
            clients["c"] = fast
            self.agent.last_user_run = 0
            await self.agent._handle(dict(req, trigger="USER_QUESTION", question="?", key="b"))
            slow.set()
            await t1
        asyncio.run(scenario())
        res = self.agent.by_setup.get("MQS-1")
        self.assertIsNotNone(res)                                                   # 1.45: SUPERSEDED_BY_NEWER_RUN, never stored
        self.assertNotEqual(res.get("status_note"), "SUPERSEDED_BY_NEWER_RUN")
        self.assertEqual(self.gate()["status"], "DISAGREE")                         # the question's SELL does not lift the WAIT veto


# ------------------------------------------------------------------ I0867
class TestI0867UnknownPriceWarning(_AgentBase):
    def test_unpriced_model_warns_and_budget_unchanged(self):
        TA = self.TA
        self.cfg.update({"agent": {"model": "claude-unknown-9"}})
        st = self.agent.status()
        codes = [w["code"] for w in st.get("warnings") or []]
        self.assertIn("BUDGET_NOT_ENFORCEABLE_UNKNOWN_PRICE", codes)               # 1.45: no warning at all
        self.assertEqual(st["warnings"][0]["model"], "claude-unknown-9")
        script = [TA.NS(content=[TA.text(json.dumps(TA.answer()))], stop_reason="end_turn", stop_details=None, model="claude-unknown-9",
                        usage=TA.NS(input_tokens=10**6, output_tokens=10**6, cache_read_input_tokens=0, cache_creation_input_tokens=0))]
        self.handle("SETUP_CONFIRMED", script=script)
        self.assertEqual(self.agent.last_run_meta["cost_status"], "UNKNOWN_PRICE")
        self.assertIsNone(self.agent.last_run_meta["est_cost_usd"])
        self.assertEqual(self.agent.spent_today(), 0.0)                             # budget semantics unchanged (owner decision)
        self.assertIsNone(self.agent._preflight({"trigger": "SETUP_CONFIRMED"}))

    def test_priced_model_has_no_warning(self):
        self.assertEqual(self.agent.status()["warnings"], [])
        self.handle("SETUP_CONFIRMED", self.TA.answer())
        self.assertEqual(self.agent.last_run_meta["cost_status"], "PRICED")


# ------------------------------------------------------------------ I0152
class TestI0152Fable52SafeVariant(_AgentBase):
    def _refusal_then(self, ans):
        TA = self.TA
        refusal = TA.NS(content=[], stop_reason="refusal", stop_details=TA.NS(category="cyber"), model="claude-fable-5-2",
                        usage=TA.NS(input_tokens=100, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0))
        return [refusal, TA.msg([TA.text(json.dumps(ans))], "end_turn")]

    def test_fable_52_is_a_fallback_model(self):
        from masterquo.agent import service as AS
        self.assertIn("claude-fable-5-2", AS.FALLBACK_MODELS)

    def test_required_never_uses_server_side_fallback(self):
        self.cfg.update({"agent": {"model": "claude-fable-5-2", "gate_policy": "REQUIRED"}})
        c = self.handle("SETUP_CONFIRMED", script=self._refusal_then(self.TA.answer()))
        self.assertNotIn("fallbacks", c.calls[0])
        self.assertNotIn("betas", c.calls[0])
        self.assertEqual(self.agent.by_setup["MQS-1"]["status"], "REFUSED")
        g = self.gate()
        self.assertEqual((g["status"], g["reason_codes"]), ("FAIL", ["AI_RUN_REFUSED"]))    # refusal keeps blocking under REQUIRED

    def test_required_no_fallback_for_older_models_either(self):
        self.cfg.update({"agent": {"model": "claude-fable-5-1", "gate_policy": "REQUIRED"}})
        c = self.handle("SETUP_CONFIRMED", self.TA.answer())
        self.assertNotIn("fallbacks", c.calls[0])                                  # 1.45: fallback also under REQUIRED (can pass)

    def test_veto_uses_fallback_and_its_disagree_blocks(self):
        self.cfg.update({"agent": {"model": "claude-fable-5-2"}})                   # default VETO
        c = self.handle("SETUP_CONFIRMED", self.TA.answer(proposed_action="WAIT"))
        self.assertEqual(c.calls[0].get("fallbacks"), "default")
        self.assertEqual(self.gate()["status"], "DISAGREE")

    def test_cost_is_estimate_only(self):
        TA = self.TA
        self.cfg.update({"agent": {"model": "claude-fable-5-2"}})
        self.assertNotIn("claude-fable-5-2", self.cfg.get().agent.price_per_mtok)    # no key in the default budget table
        st = self.agent.status()
        self.assertEqual(st["cost_estimate_only"]["usd_per_mtok"], {"input": 8.0, "output": 40.0, "cache_read": 0.20})
        self.assertFalse(st["cost_estimate_only"]["counted_in_budget"])
        script = [TA.NS(content=[TA.text(json.dumps(TA.answer()))], stop_reason="end_turn", stop_details=None, model="claude-fable-5-2",
                        usage=TA.NS(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=1_000_000,
                                    cache_creation_input_tokens=0))]
        self.handle("SETUP_CONFIRMED", script=script)
        lm = self.agent.last_run_meta
        self.assertAlmostEqual(lm["est_cost_usd_display"], 8.0 + 4.0 + 0.20)
        self.assertIsNone(lm["est_cost_usd"])
        self.assertEqual(self.agent.spent_today(), 0.0)                             # never in the daily budget
        self.assertIsNone(self.agent._preflight({"trigger": "SETUP_CONFIRMED"}))
        row = self.t.db.one("SELECT est_cost_usd FROM agent_runs WHERE status='OK' ORDER BY rowid DESC LIMIT 1")
        self.assertIsNone(row["est_cost_usd"])

    def test_user_price_in_table_stays_the_budgeted_one(self):
        self.cfg.update({"agent": {"model": "claude-fable-5-2", "price_per_mtok": {"claude-fable-5-2": [8.0, 40.0]}}})
        self.assertIsNone(self.agent.status()["cost_estimate_only"])


# ------------------------------------------------------------------ I0094 / I0125
def _old_config(path, **server):
    """A valid config.json one schema version older (v14) -> ConfigStore() would migrate it and WRITE the file + config.v14.bak.json."""
    from masterquo.config import ConfigStore
    st = ConfigStore(path)
    if server:
        st.update({"server": server})
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["config_version"] = 14
    raw.pop("resources", None)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return path.read_bytes()


class _DataDir(unittest.TestCase):
    def setUp(self):
        from pathlib import Path

        from _env import TempData
        self.td = TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()


class TestI0094ReadOnlyPortAndProfileRefusal(_DataDir):
    def test_port_never_writes_config(self):
        import masterquo.__main__ as M
        cfg = self.data / "config.json"
        before = _old_config(cfg, port=9123)
        self.assertEqual(M._port(), 9123)
        self.assertEqual(cfg.read_bytes(), before)                                  # 1.45: migrated + rewritten
        self.assertEqual(sorted(p.name for p in self.data.glob("config.v*.bak.json")), [])
        cfg.unlink()
        self.assertEqual(M._port(), 8765)
        self.assertFalse(cfg.exists())                                              # 1.45: a default config.json was created

    def test_port_never_raises(self):
        import masterquo.__main__ as M
        (self.data / "config.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(M._port(), 8765)

    def test_profile_refused_while_bot_answers(self):
        from unittest import mock

        import masterquo.__main__ as M
        from masterquo.config import ConfigStore
        ConfigStore().update({"active": {"profile": "ACTIVE"}})
        cfg = self.data / "config.json"
        before = cfg.read_bytes()
        with mock.patch.object(M, "_health", return_value={"app": M.APP_NAME}):
            self.assertEqual(M.cmd_profile("ORIGINAL"), 3)                          # 1.45: 0 and the file rewritten
        self.assertEqual(cfg.read_bytes(), before)

    def test_profile_refused_while_instance_lock_held(self):
        import fcntl
        from unittest import mock

        import masterquo.__main__ as M
        from masterquo.config import ConfigStore
        ConfigStore().update({"active": {"profile": "ACTIVE"}})
        before = (self.data / "config.json").read_bytes()
        with open(M._rt_dir() / "instance.lock", "a+b") as holder:                 # another process = another open file description
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(M, "_health", return_value=None):
                self.assertEqual(M.cmd_profile("ORIGINAL"), 3)
            self.assertEqual((self.data / "config.json").read_bytes(), before)

    def test_profile_written_when_bot_stopped_and_probe_releases_lock(self):
        from unittest import mock

        import masterquo.__main__ as M
        from masterquo.config import ConfigStore
        ConfigStore().update({"active": {"profile": "ACTIVE"}})
        with mock.patch.object(M, "_health", return_value=None):
            self.assertEqual(M.cmd_profile("ORIGINAL"), 0)
        self.assertEqual(ConfigStore().get().active.profile, "ORIGINAL")
        lock = M._single_instance_lock(retries=1)                                  # the probe did not keep the lock
        try:
            self.assertIsNotNone(lock)
        finally:
            if lock is not None:
                lock.close()
            M._LOCK_HANDLE = None


class TestI0125DefaultPortSingleSource(_DataDir):
    def test_literal_only_in_paths(self):
        import re
        from pathlib import Path
        pkg = Path(_env.ROOT) / "backend" / "masterquo"
        hits = [f"{p.relative_to(pkg)}:{i}" for p in pkg.rglob("*.py") for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if re.search(r"\b8765\b", line)]
        self.assertEqual([h.split(":")[0] for h in hits], ["paths.py"], hits)        # 1.45: config, __main__, quant/cli, studio/settings
        from masterquo import paths
        from masterquo.config import ServerConfig
        self.assertEqual((paths.DEFAULT_PORT, ServerConfig().port), (8765, 8765))
        tool = (Path(_env.ROOT) / "tools" / "tsfm_setup.py").read_text(encoding="utf-8")
        self.assertIn(f"DEFAULT_PORT = {paths.DEFAULT_PORT}", tool)

    def test_studio_follows_bot_server_port(self):
        import os
        bot = self.data / "bot"
        studio = self.data / "studio"
        bot.mkdir()
        studio.mkdir()
        old = {k: os.environ.get(k) for k in ("MQ_STUDIO_DATA_DIR", "MQ_BOT_DATA_DIR")}
        os.environ.update(MQ_STUDIO_DATA_DIR=str(studio), MQ_BOT_DATA_DIR=str(bot))
        try:
            from masterquo.config import ConfigStore
            from masterquo.studio import settings as S
            ConfigStore(bot / "config.json").update({"server": {"port": 9001}})
            s = S.load()
            self.assertEqual((s["bot_port"], s.get("bot_port_source")), (9001, "BOT_CONFIG"))   # 1.45: 8765
            S.save({"profile": "research"})                                         # an unrelated save keeps the port automatic
            self.assertIsNone(json.loads((studio / "settings.json").read_text())["bot_port"])
            ConfigStore(bot / "config.json").update({"server": {"port": 9002}})
            self.assertEqual(S.load()["bot_port"], 9002)
            self.assertEqual(S.save({"bot_port": 8766})["bot_port"], 8766)          # an explicit value stays
            ConfigStore(bot / "config.json").update({"server": {"port": 9003}})
            self.assertEqual((S.load()["bot_port"], S.load()["bot_port_source"]), (8766, "SETTINGS"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_quant_cli_server_never_writes_config(self):
        import socket

        from masterquo.quant import cli as QC
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
        s.close()
        cfg = self.data / "config.json"
        before = _old_config(cfg, port=max(free, 1024))
        QC._OPENER = None
        self.assertIsNone(QC._server("/api/v1/health", timeout=0.5))
        self.assertEqual(cfg.read_bytes(), before)                                  # 1.45: ConfigStore() migrated and rewrote it


# ------------------------------------------------------------------ I0097
class TestI0097SettingsStores(_DataDir):
    def test_inventory_uses_runtime_stores(self):
        from types import SimpleNamespace as NS
        from unittest import mock

        from masterquo.kronos import settings as KS
        from masterquo.tsfm import settings as TS
        from masterquo.upgrade import inventory as INV
        rt = NS(tsfm=NS(settings=TS.SettingsStore(self.data / "ts.json")), kronos=NS(settings=KS.SettingsStore(self.data / "ks.json")))

        def boom(*a, **k):
            raise AssertionError("separate settings store built next to the Runtime's one")
        with mock.patch.object(TS, "SettingsStore", boom), mock.patch.object(KS, "SettingsStore", boom):
            rows = INV.models(None, rt=rt)                                          # 1.45: no rt parameter (TypeError)
        errs = [r for r in rows if r.get("error")]
        self.assertFalse([r for r in errs if r["model_id"] in ("tsfm", "kronos")], errs)
        self.assertTrue(any(r["model_id"].startswith("tsfm:") for r in rows))
        self.assertIn("kronos", [r["model_id"] for r in rows])
        with mock.patch.object(TS, "SettingsStore", boom), mock.patch.object(KS, "SettingsStore", boom):
            rep = INV.write_reports("after", None, out_dir=self.data / "rep", rt=rt)
        from pathlib import Path
        doc = json.loads(Path(rep["model_inventory"]).read_text(encoding="utf-8"))
        self.assertFalse([r for r in doc["items"] if r.get("model_id") in ("tsfm", "kronos") and r.get("error")])

    def test_quant_settings_read_modify_write_is_serialised(self):
        import threading
        import time
        from unittest import mock

        from masterquo.quant import service as SV
        q = SV.QuantService.__new__(SV.QuantService)
        q.rt, q.clock, q.settings = None, time.time, SV.Settings(self.data / "quant_settings.json")
        self.assertEqual(q.settings.policy, "RELOAD_ALWAYS")
        a_in, a_go = threading.Event(), threading.Event()
        real_get = SV.Settings.get

        def slow_get(self_):
            d = real_get(self_)
            if threading.current_thread().name == "A":
                a_in.set()
                a_go.wait(5)
            return d
        with mock.patch.object(SV.Settings, "get", slow_get):
            ta = threading.Thread(target=q.set_estimator, args=("legacy_logistic",), name="A")
            ta.start()
            self.assertTrue(a_in.wait(5))
            tb = threading.Thread(target=q.set_mode, args=("OFF",), name="B")
            tb.start()
            time.sleep(0.2)                                                         # B runs (1.45) or waits for A's write (now)
            a_go.set()
            ta.join(5)
            tb.join(5)
        s = q.settings.get()
        self.assertEqual((s["mode"], s["estimator"]), ("OFF", "legacy_logistic"))   # 1.45: A's stale write lost B's mode change


# ------------------------------------------------------------------ I0338
class TestI0338DtRankerStatus(unittest.TestCase):
    def test_status_says_training_not_implemented(self):
        import threading
        from types import SimpleNamespace as NS

        from masterquo.api import wf32_routes

        class App:                                                                   # stand-in app (as modelhub/smoke/ml.py)
            def __init__(self):
                self.routes = {}

            def __getattr__(self, method):
                def deco(path, *a, **k):
                    def wrap(fn):
                        self.routes[(method, path)] = fn
                        return fn
                    return wrap
                return deco

        class Bridge:
            def bars(self, tf, count=None, include_forming=False):
                return []
        app = App()
        wf32_routes.register(app, NS(bridge=Bridge(), db=None, _acct_thread=True, _stop=threading.Event()))
        st = app.routes[("get", "/api/v1/models/dt-ranker/status")]()
        self.assertEqual(st["training_path"], "NOT_IMPLEMENTED")                    # 1.45: no such field
        self.assertFalse(st["ready"])
        self.assertIn("FALLBACK_BASELINE", st["training_note"])


# ------------------------------------------------------------------ I0079
class TestI0079AnalysisLayerHasNoLabOrAgentImport(unittest.TestCase):
    def test_analysis_imports(self):
        import ast
        from pathlib import Path
        pkg = Path(_env.ROOT) / "backend" / "masterquo" / "analysis"
        bad = []
        for p in sorted(pkg.rglob("*.py")):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.ImportFrom):
                    mods = [("." * node.level) + (node.module or "")]
                elif isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                for m in mods:
                    if m.startswith(("..lab", "..agent", "masterquo.lab", "masterquo.agent")):
                        bad.append(f"{p.name}:{node.lineno} {m}")
        self.assertEqual(bad, [])                                                   # 1.45: structure_knowledge.py:122-123 ..lab

    def test_shim_is_the_same_module(self):
        from masterquo.agent import structure_knowledge as new
        from masterquo.analysis import structure_knowledge as old
        self.assertIs(old.explain, new.explain)
        self.assertEqual(old.KNOWLEDGE_VERSION, new.KNOWLEDGE_VERSION)
        self.assertEqual(old.prompt_section(), new.prompt_section())
        from masterquo.analysis.structure_knowledge import RULES
        self.assertIs(RULES, new.RULES)


# ------------------------------------------------------------------ I0135
class TestI0135ExportStubsAreInformational(unittest.TestCase):
    def _help(self, main, argv):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(argv)
        return out.getvalue()

    def test_help_names_the_stub(self):
        from masterquo.lab.flow_context.cli import main as fc
        from masterquo.lab.structure_cli import main as si
        self.assertIn("informacyjne", self._help(fc, ["export", "--help"]))       # 1.45: no description at all
        self.assertIn("informacyjne", self._help(fc, ["--help"]))
        self.assertIn("informacyjne", self._help(si, ["--help"]))
        self.assertIn("training export", self._help(si, ["export", "--help"]))


# ------------------------------------------------------------------ I0104
class TestI0104CpuSamplerIsolation(_DataDir):
    def test_two_consumers_keep_their_own_window(self):
        from unittest import mock

        from masterquo import sysres
        T = [0.0]

        def times():                                                                # /proc/stat-like: 10 ms ticks, 50 % busy
            tot = int(T[0] * 100) / 100.0
            return tot * 0.5, tot

        def sleep(s):
            T[0] += s

        def clock():
            return T[0]
        with mock.patch.object(sysres, "_cpu_times", times), mock.patch.object(sysres.time, "sleep", sleep):
            api, gov = sysres.CpuSampler(clock=clock), sysres.CpuSampler(clock=clock)
            self.assertEqual(api.percent(), 50.0)
            T[0] += 0.003
            self.assertEqual(gov.percent(), 50.0)
            T[0] = 10.0
            self.assertEqual(api.percent(), 50.0)
            T[0] = 10.002                                                           # same 10 ms tick: 1.45 shared window -> None
            self.assertEqual(gov.percent(), 50.0)
            self.assertEqual(api.percent(), 50.0)                                   # < MIN_WINDOW_S: last value, window kept

    def test_governor_and_api_use_different_samplers(self):
        from masterquo import sysres
        from masterquo.config import ConfigStore
        from masterquo.resources.governor import Governor
        g = Governor(ConfigStore())
        self.assertIsInstance(g._cpu, sysres.CpuSampler)
        self.assertIsNot(g._cpu, sysres.API_SAMPLER)
        for hook in ("masterquo.modelhub.families.deep:reset_health_cache", "masterquo.quant.tabicl:reset_install_cache",
                     "masterquo.training.core:reset_candles_cache", "masterquo.sysres:reset_cpu_samplers"):
            mod, fn = hook.split(":")
            __import__(mod, fromlist=[fn]).__dict__[fn]()                           # process-cache hooks exist and run


# ------------------------------------------------------------------ I0118
class TestI0118SecretNamesSingleSource(_DataDir):
    def test_one_source_and_pinned_sets(self):
        from masterquo import secrets_store as SS
        from masterquo.exports import core as EC
        self.assertIs(EC.SECRET_NAMES, SS.ALLOWED)                                  # 1.45: a separate copy
        self.assertEqual(SS.ALLOWED, ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "MT5_PASSWORD", "COINGLASS_API_KEY"))
        self.assertEqual(set(SS.UI_SETTABLE), {"TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "ANTHROPIC_API_KEY", "MT5_PASSWORD"})
        self.assertEqual(SS.DOTENV_VARS, ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "MASTERQUO_DATA_DIR", "FRED_API_KEY", "TELEGRAM_BOT_TOKEN"))

    def test_verify_release_is_a_superset(self):
        import ast
        from pathlib import Path

        from masterquo import secrets_store as SS
        tree = ast.parse((Path(_env.ROOT) / "tools" / "verify_release.py").read_text(encoding="utf-8"))
        names = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and any(getattr(t, "id", None) == "SECRET_NAMES" for t in n.targets))
        self.assertLessEqual(set(SS.ALLOWED) | {"PMW_ADMIN_PASSWORD_HASH", "PMW_SIGNING_KEY"}, set(names))

    def test_dotenv_never_loads_mt5_password_or_coinglass(self):
        from unittest import mock

        import masterquo.__main__ as M
        from masterquo import paths
        (self.data / ".env").write_text("MT5_PASSWORD=x1\nCOINGLASS_API_KEY=x2\nFRED_API_KEY=x3\n", encoding="utf-8")
        keep = {k: os.environ.pop(k, None) for k in ("MT5_PASSWORD", "COINGLASS_API_KEY", "FRED_API_KEY")}
        try:
            with mock.patch.object(paths, "ROOT_DIR", self.data):
                M._load_dotenv()
            self.assertEqual((os.environ.get("MT5_PASSWORD"), os.environ.get("COINGLASS_API_KEY"), os.environ.get("FRED_API_KEY")),
                             (None, None, "x3"))
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_env_example_matches_dotenv_vars(self):
        import re
        from pathlib import Path

        from masterquo import secrets_store as SS
        text = (Path(_env.ROOT) / ".env.example").read_text(encoding="utf-8")
        keys = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE))
        self.assertEqual(keys, set(SS.DOTENV_VARS))                                 # 1.45: 4 of 5 (no MASTERQUO_DATA_DIR)
        head = " ".join(text.splitlines()[:3])
        self.assertTrue(all(v in head for v in SS.DOTENV_VARS), head)                # 1.45: 'WYŁĄCZNIE zmienne wymienione poniżej' (4)

    def test_config_route_masks_every_secret(self):
        import test_audit_146_b_mq_api as MQ
        from masterquo.config import ConfigStore
        from masterquo.secrets_store import ALLOWED, SecretStore
        os.environ["COINGLASS_API_KEY"] = "cg-secret-value-123456"
        try:
            rt = MQ.make_rt(cfg=ConfigStore(), secrets=SecretStore())
            app = MQ.make_app(rt)
            st, body, _ = MQ.call(app, rt, "GET", "/api/v1/config")
            self.assertEqual(st, 200, body[:300])
            sec = json.loads(body)["secrets"]
            self.assertEqual(set(sec), set(ALLOWED))                               # 1.45: COINGLASS_API_KEY missing
            self.assertTrue(all(set(v) == {"source", "masked"} for v in sec.values()))
            self.assertNotIn(b"cg-secret-value-123456", body)
            st, _, _ = MQ.call(app, rt, "POST", "/api/v1/secrets", body={"name": "COINGLASS_API_KEY", "value": "x"})
            self.assertEqual(st, 400)                                               # unchanged: own route for COINGLASS
        finally:
            os.environ.pop("COINGLASS_API_KEY", None)


# ------------------------------------------------------------------ I0120 (safe subset: copy-only snapshot per version, no rollback CLI)
class TestI0120SnapshotPerVersion(_DataDir):
    def _write(self, rel, text):
        p = self.data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_snapshot_of_the_current_version_with_all_settings_files(self):
        from unittest import mock

        from masterquo.upgrade import migrate as M
        self._write("tsfm/settings.json", '{"v": 1}')
        with mock.patch.object(M.INV, "write_reports", return_value={}):
            M.before()                                                              # 1.41 state: before_done
        st41 = (self.data / "upgrade" / "1.41.0.json").read_bytes()
        for rel in ("training_center/settings.json", "telegram/signal_template.json", "presets/strategy.json", "config.json"):
            self._write(rel, '{"user": "' + rel + '"}')
        st = M.snapshot_before("1.46.0")                                            # 1.45: nothing (frozen at 1.41.0)
        b = self.data / "backups" / "pre-1.46.0"
        for rel in ("training_center/settings.json", "telegram/signal_template.json", "presets/strategy.json", "config.json",
                    "tsfm/settings.json"):
            self.assertTrue((b / rel).is_file(), rel)
            self.assertIn(rel, st["snapshot_files"])
        self.assertEqual((self.data / "upgrade" / "1.41.0.json").read_bytes(), st41)   # the 1.41 state file untouched
        self.assertTrue((self.data / "upgrade" / "snapshot-1.46.0.json").is_file())

    def test_copy_only_never_overwrites_or_deletes(self):
        from masterquo.upgrade import migrate as M
        cfg = self._write("presets/strategy.json", '{"v": "pre"}')
        old = self._write("backups/pre-1.46.0/presets/strategy.json", '{"v": "older-snapshot"}')
        st = M.snapshot_before("1.46.0")
        self.assertEqual(old.read_text(encoding="utf-8"), '{"v": "older-snapshot"}')  # first snapshot wins
        self.assertIn("presets/strategy.json", st["already_present"])
        cfg.write_text('{"v": "post"}', encoding="utf-8")
        st2 = M.snapshot_before("1.46.0")                                           # once per version
        self.assertTrue(st2["done"])
        self.assertEqual(cfg.read_text(encoding="utf-8"), '{"v": "post"}')          # current files are never touched
        M.snapshot_before("1.47.0")
        self.assertEqual((self.data / "backups" / "pre-1.47.0" / "presets" / "strategy.json").read_text(encoding="utf-8"), '{"v": "post"}')
        self.assertTrue((self.data / "backups" / "pre-1.46.0").is_dir())             # no pruning

    def test_default_version_and_no_rollback_command(self):
        from pathlib import Path

        from masterquo.upgrade import migrate as M
        from masterquo.version import APP_VERSION
        self.assertEqual(M.snapshot_before()["version"], APP_VERSION)
        root = Path(_env.ROOT) / "backend" / "masterquo"
        self.assertNotIn("rollback-config", (root / "__main__.py").read_text(encoding="utf-8"))     # S0: no CLI rollback path
        self.assertNotIn("rollback_config", (root / "api" / "app.py").read_text(encoding="utf-8"))
        self.assertIn("_UM.snapshot_before()", (root / "runtime.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ I0777
class TestI0777DecisionSnapshotAtSend(unittest.TestCase):
    """Two decisions with the same id (same core) and a different SL: decisions.record_json keeps the first one; the attempt must carry a
    copy of the decision really used for the send. The MT5 request itself is unchanged."""

    def setUp(self):
        import test_risk_execution as TR
        self.TR = TR
        TR.TestExecution.setUp(self)
        self.sent = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: self.sent.append(r) or orig(r)

    def tearDown(self):
        self.TR.TestExecution.tearDown(self)

    def _auto_demo(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)

    def test_attempt_keeps_the_sent_levels(self):
        self._auto_demo()
        first = self.TR.TestExecution.decision(self)
        second = self.TR.TestExecution.decision(self)
        second["risk"] = dict(second["risk"], stop_loss=round(second["risk"]["stop_loss"] + 1.5, 2))
        second["content_hash"] = "abc"
        second["setup"] = dict(second["setup"], version="1.0.0")
        self.assertNotEqual(first["risk"]["stop_loss"], second["risk"]["stop_loss"])
        self.engine.decision = second
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        row = self.db.one("SELECT decision_json, sl, volume FROM order_attempts")
        self.assertIsNotNone(row["decision_json"])                                  # 1.45: no column / no copy
        snap = json.loads(row["decision_json"])
        self.assertEqual(snap["risk"]["stop_loss"], second["risk"]["stop_loss"])
        self.assertEqual(snap["sent"]["sl"], row["sl"])
        self.assertEqual((snap["decision_id"], snap["content_hash"], snap["setup"]["version"]), ("MQD-1", "abc", "1.0.0"))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["sl"], second["risk"]["stop_loss"])            # the request is what it was

    def test_audit_failure_never_blocks_the_send(self):
        self._auto_demo()
        d = self.TR.TestExecution.decision(self)
        d["levels"] = {"stop_loss": float("nan")}                                   # not serialisable (allow_nan=False)
        self.engine.decision = d
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        self.assertEqual(len(self.sent), 1)
        snap = json.loads(self.db.one("SELECT decision_json FROM order_attempts")["decision_json"])
        self.assertEqual(snap["status"], "DECISION_COPY_FAILED")
        orig = self.db.execute

        def broken(sql, args=()):
            if "decision_json" in sql:
                raise RuntimeError("disk")
            return orig(sql, args)
        self.db.execute = broken
        self.engine.decision = self.TR.TestExecution.decision(self, did="MQD-2", setup_id="MQS-T2")
        self.assertEqual(self.gw.execute("MQD-2")["status"], "FILLED")              # a failed audit write: the order still goes out
        self.assertEqual(len(self.sent), 2)


if __name__ == "__main__":
    unittest.main()
