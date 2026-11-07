"""SEQ_LSTM / SEQ_GRU in PyTorch: input [batch, lookback, features] -> 3 classes DOWN / FLAT / UP (label of the shared dataset).
Small CPU-checkable architecture; early stopping on the validation part, best-checkpoint restore, gradient clipping, fixed seeds;
temperature calibration fitted on validation logits (softmax alone is not a verified confidence). Inference in eval mode, no grad,
the same scaler (applied by the caller from the stored artifact). Saves model.pt (state_dict) + seq_config.json."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def _net(arch, n_feat, hidden, layers, dropout):
    import torch.nn as nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            rnn = nn.LSTM if arch == "LSTM" else nn.GRU
            self.rnn = rnn(n_feat, hidden, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0)
            self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 3))

        def forward(self, x):
            o, _ = self.rnn(x)
            return self.head(o[:, -1, :])
    return Net()


def _logloss(p, y):
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1))))


def train(req):
    import torch
    import torch.nn.functional as Fn
    d = Path(req["dir"])
    z = np.load(d / "seq_data.npz")
    Xtr, ytr, Xva, yva, Xho, yho = z["Xtr"], z["ytr"], z["Xva"], z["yva"], z["Xho"], z["yho"]
    cfg = req["cfg"]
    seed = int(cfg.get("seed", 7))
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(int(cfg.get("threads", 2)))
    net = _net(req["arch"], Xtr.shape[-1], int(cfg.get("hidden", 32)), int(cfg.get("layers", 1)), float(cfg.get("dropout", 0.1)))
    opt = torch.optim.Adam(net.parameters(), lr=float(cfg.get("lr", 1e-3)))
    w = torch.tensor(np.bincount(ytr, minlength=3) + 1.0, dtype=torch.float32)
    w = (w.sum() / w) / 3
    Xt, yt = torch.from_numpy(Xtr), torch.from_numpy(ytr)
    Xv = torch.from_numpy(Xva)
    best, best_state, bad, hist = math.inf, None, 0, []
    rng = np.random.default_rng(seed)
    first_w = [p.detach().clone() for p in net.parameters()]
    for ep in range(int(cfg.get("epochs", 20))):
        net.train()
        perm = rng.permutation(len(Xt))
        for i in range(0, len(perm), int(cfg.get("batch", 128))):
            b = perm[i:i + int(cfg.get("batch", 128))]
            opt.zero_grad()
            loss = Fn.cross_entropy(net(Xt[b]), yt[b], weight=w)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
        net.eval()
        with torch.no_grad():
            pv = torch.softmax(net(Xv), -1).numpy()
        vl = _logloss(pv, yva)
        hist.append({"epoch": ep + 1, "val_log_loss": vl})
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= int(cfg.get("patience", 4)):
                break
    net.load_state_dict(best_state)
    net.eval()
    changed = float(sum((p.detach() - q).abs().sum().item() for p, q in zip(net.parameters(), first_w)))
    with torch.no_grad():
        lv = net(Xv).numpy()
        lh = net(torch.from_numpy(Xho)).numpy()
    Ts = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

    def sm(l, T):
        e = np.exp((l - l.max(1, keepdims=True)) / T)
        return e / e.sum(1, keepdims=True)
    T = min(Ts, key=lambda t: _logloss(sm(lv, t), yva))
    pv, ph = sm(lv, T), sm(lh, T)
    prior = (np.bincount(ytr, minlength=3) + 1.0) / (len(ytr) + 3)
    torch.save(net.state_dict(), d / "model.pt")
    conf = {"arch": req["arch"], "n_feat": int(Xtr.shape[-1]), "hidden": int(cfg.get("hidden", 32)), "layers": int(cfg.get("layers", 1)),
            "dropout": float(cfg.get("dropout", 0.1)), "temperature": T, "lookback": int(Xtr.shape[1])}
    (d / "seq_config.json").write_text(json.dumps(conf), encoding="utf-8")
    sample = Xho[-8:]
    with torch.no_grad():
        sp = sm(net(torch.from_numpy(sample)).numpy(), T)
    np.save(d / "seq_sample_X.npy", sample)
    return {"ok": True, "history": hist, "val_log_loss": _logloss(pv, yva), "val_baseline_log_loss": _logloss(np.tile(prior, (len(yva), 1)), yva),
            "holdout_log_loss": _logloss(ph, yho), "holdout_baseline_log_loss": _logloss(np.tile(prior, (len(yho), 1)), yho),
            "holdout_accuracy": float((ph.argmax(1) == yho).mean()), "temperature": T, "param_change_l1": changed,
            "sample_p": sp.tolist(), "device": "cpu", "torch": torch.__version__}


def predict(req):
    import torch
    d = Path(req["dir"])
    conf = json.loads((d / "seq_config.json").read_text(encoding="utf-8"))
    net = _net(conf["arch"], conf["n_feat"], conf["hidden"], conf["layers"], conf["dropout"])
    net.load_state_dict(torch.load(d / "model.pt", map_location="cpu", weights_only=True))
    net.eval()
    X = np.load(req["x_path"]).astype(np.float32)
    with torch.no_grad():
        l = net(torch.from_numpy(X)).numpy()
    e = np.exp((l - l.max(1, keepdims=True)) / conf["temperature"])
    p = e / e.sum(1, keepdims=True)
    return {"ok": True, "p": p.tolist()}
