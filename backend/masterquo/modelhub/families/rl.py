"""RL_PPO family: PPO (Stable-Baselines3, .venv_deep) on the Gymnasium replay environment (rl_core). Output = PROPOSED target exposure
(SHORT / FLAT / LONG) with the policy's action probabilities - an action probability is not a probability of profit. The proposal is
read by the panel / risk context only; it never calls order_send and the existing risk engine and execution mode keep control."""
from __future__ import annotations

import json

import numpy as np

from . import base as B
from . import deep as D
from .rl_core import ACTION_NAMES


class PPO(B.Family):
    ID = "RL_PPO"
    NAME = "PPO (Stable-Baselines3, Gymnasium replay) – propozycja ekspozycji"
    KIND = "TRAINED"
    TASK_TYPE = "RL_ACTION"
    UNIT = "action"
    TASK = "TARGET_EXPOSURE"
    DEPS = ("torch", "gymnasium", "stable_baselines3")
    RUNTIME = "DEEP"
    TF = "M5"
    HORIZONS = ()
    RECEIVERS = ("RISK:exposure_proposal (OBSERVE)", "PANEL:model_status")
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 3000}

    def fit(self, data, cfg, tmp, budget):
        bars = data["bars"][-int(budget.get("max_rows", 12000)):]
        pt = float(data.get("point") or 0.01)
        spread = float(np.median([b.get("spread") or 0 for b in bars])) * pt
        env = {"k": 16, "spread": spread, "slippage": float(cfg.get("slippage_price", pt * 5)), "commission": float(cfg.get("commission_price", 0.0)),
               "unit": 1.0, "max_units": 1, "reward_scale": float(np.std(np.diff([b["c"] for b in bars]))) or 1.0, "max_steps": 500}
        (tmp / "rl_bars.json").write_text(json.dumps([{k: b[k] for k in ("o", "h", "l", "c")} for b in bars]), encoding="utf-8")
        prof = budget.get("profile") or "research"
        tc = {"env": env, "seeds": [1] if prof == "smoke" else [1, 2, 3], "timesteps": 1024 if prof == "smoke" else 50000, "n_steps": 256}
        res = D.call("train_ppo", {"dir": str(tmp), "cfg": tc}, timeout=float(budget.get("timeout_s", 3600)))
        (tmp / "rl_bars.json").unlink(missing_ok=True)
        if not res.get("ok"):
            raise B.Unavailable("ERROR", f"trening PPO: {res.get('error')}")
        vm = {"val_ppo_minus_flat": res["val_ppo_minus_flat"], "val_ppo_minus_momentum": res["val_ppo_minus_momentum"]}
        return {"metrics": res, "validation": self.promotion(vm, {"val_ppo_minus_flat": (">", 0.0), "val_ppo_minus_momentum": (">", 0.0)}),
                "sample": {"expected": None, "tolerance": 0.0}}

    def load(self, d):
        return {"dir": str(d), **json.loads((d / "rl_config.json").read_text(encoding="utf-8"))}

    def predict(self, art, live):
        bars = live["bars"][-200:]
        if len(bars) < 40:
            raise B.Unavailable("BLOCKED_DATA", "za mało świec")
        r = D.call("predict_ppo", {"dir": art["dir"], "bars": [{k: b[k] for k in ("o", "h", "l", "c")} for b in bars],
                                   "position": float(live.get("position") or 0.0)}, timeout=120)
        if not r.get("ok"):
            raise B.Unavailable("ERROR", f"inferencja PPO: {r.get('error')}")
        pr = r["probs"]
        return {"action": ACTION_NAMES[int(r["action"])], "action_probabilities": {ACTION_NAMES[i]: float(pr[i]) for i in range(3)},
                "note": "propozycja docelowej ekspozycji – nie zlecenie; prawdopodobieństwo akcji ≠ prawdopodobieństwo zysku"}
