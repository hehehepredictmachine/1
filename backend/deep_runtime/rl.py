"""RL_PPO: Gymnasium environment over the replay core (masterquo.modelhub.families.rl_core - pure numpy, shared with the bot) and PPO
from Stable-Baselines3. Train on the train segment, choose nothing on the test; validation over several seeds vs FLAT and a momentum
rule; observation normaliser (VecNormalize) saved with the policy and frozen at evaluation. Runtime returns a PROPOSED target exposure -
never an order."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _env_cls():
    import gymnasium as gym
    from gymnasium import spaces
    from masterquo.modelhub.families.rl_core import ReplayCore

    class ReplayEnv(gym.Env):
        metadata = {"render_modes": []}

        def __init__(self, bars, lo, hi, kw, seed=0):
            super().__init__()
            self.core = ReplayCore(bars[lo:hi], **kw)
            self.observation_space = spaces.Box(-np.inf, np.inf, shape=(self.core.obs_dim,), dtype=np.float32)
            self.action_space = spaces.Discrete(3)
            self.rng = np.random.default_rng(seed)
            self.ep_len = kw.get("max_steps", 500)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            hi = max(self.core.k + 1, len(self.core.c) - self.ep_len - 3)
            start = int(self.rng.integers(self.core.k, hi)) if hi > self.core.k else self.core.k
            return self.core.reset(start), {}

        def step(self, a):
            return self.core.step(int(a))
    return ReplayEnv


def _bars(d):
    return json.loads((d / "rl_bars.json").read_text(encoding="utf-8"))


def _eval(model, vn, bars, lo, hi, kw):
    from masterquo.modelhub.families.rl_core import ReplayCore, flat_policy, momentum_policy, run_policy

    def pol(o, core):
        oo = vn.normalize_obs(o[None, :]) if vn is not None else o[None, :]
        a, _ = model.predict(oo, deterministic=True)
        return int(a[0])
    steps = hi - lo - 3
    out = {}
    for name, p in (("ppo", pol), ("flat", flat_policy), ("momentum", momentum_policy)):
        core = ReplayCore(bars[lo:hi], **dict(kw, max_steps=steps))
        out[name] = run_policy(core, p, core.k, steps)
    return out


def train(req):
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
    d = Path(req["dir"])
    bars = _bars(d)
    cfg = req["cfg"]
    kw = cfg["env"]
    n = len(bars)
    tr, va = int(n * 0.6), int(n * 0.8)
    Env = _env_cls()
    seeds = cfg.get("seeds", [1, 2])
    runs = []
    best = None
    for s in seeds:
        venv = VecNormalize(DummyVecEnv([lambda s=s: Env(bars, 0, tr, kw, seed=s)]), norm_obs=True, norm_reward=False)
        model = PPO("MlpPolicy", venv, seed=int(s), n_steps=int(cfg.get("n_steps", 256)), batch_size=64, learning_rate=3e-4, verbose=0, device="cpu")
        model.learn(total_timesteps=int(cfg.get("timesteps", 4000)))
        venv.training = False
        ev = _eval(model, venv, bars, tr, va, kw)
        runs.append({"seed": s, "val": ev})
        if best is None or ev["ppo"]["net_pnl"] > best[0]["ppo"]["net_pnl"]:
            best = (ev, model, venv, s)
    ev, model, venv, s = best
    model.save(str(d / "ppo_policy"))
    venv.save(str(d / "ppo_vecnorm.pkl"))
    test = _eval(model, venv, bars, va, n, kw)
    (d / "rl_config.json").write_text(json.dumps({"env": kw, "seed": s, "obs_dim": int(Env(bars, 0, 100, kw).core.obs_dim)}), encoding="utf-8")
    return {"ok": True, "seeds": runs, "chosen_seed": s, "test": test,
            "val_ppo_minus_flat": ev["ppo"]["net_pnl"] - ev["flat"]["net_pnl"], "val_ppo_minus_momentum": ev["ppo"]["net_pnl"] - ev["momentum"]["net_pnl"]}


def predict(req):
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
    d = Path(req["dir"])
    conf = json.loads((d / "rl_config.json").read_text(encoding="utf-8"))
    Env = _env_cls()
    bars = req["bars"]
    dummy = DummyVecEnv([lambda: Env(bars, 0, len(bars), conf["env"])])
    vn = VecNormalize.load(str(d / "ppo_vecnorm.pkl"), dummy)
    vn.training = False
    model = PPO.load(str(d / "ppo_policy"), device="cpu")
    from masterquo.modelhub.families.rl_core import ReplayCore
    core = ReplayCore(bars, **conf["env"])
    core.reset(len(bars) - 2)
    core.pos = float(req.get("position", 0.0))
    o = core.obs()
    oo = vn.normalize_obs(o[None, :])
    a, _ = model.predict(oo, deterministic=True)
    import torch
    with torch.no_grad():
        dist = model.policy.get_distribution(model.policy.obs_to_tensor(oo)[0])
        probs = dist.distribution.probs.cpu().numpy()[0].tolist()
    return {"ok": True, "action": int(a[0]), "probs": probs}
