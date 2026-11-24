"""1.46 arch, wave 2, group platform_misc - regression tests (each class names the item key it covers).

I0866  agent: an answer to a USER_QUESTION can only make the AI gate stricter (never replaces the setup assessment)
I0867  agent: model without a price -> warning BUDGET_NOT_ENFORCEABLE_UNKNOWN_PRICE (budget / preflight unchanged)
I0152  agent: claude-fable-5-2 in FALLBACK_MODELS, no server-side fallback under REQUIRED, cost shown as an estimate only
"""
import asyncio
import json
import unittest

import _env  # noqa: F401

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


if __name__ == "__main__":
    unittest.main()
