"""SDformerFlow trainer (TH_SDFORMERFLOW, profile direct_train): python -m sdformer_runtime.train --data bars.json --out DIR --op from_scratch|fine_tune|resume
[--checkpoint DIR] [--epochs N] [--minutes M] [--batch B] [--lr LR] [--seed S] [--cancel-file F] [--status-file F] [--run-id ID]

* data: closed bars [{t, o, h, l, c, tv}] oldest-first of ONE market context (instrument + TF); the dataset hash = sha256 of the bars.
* split: chronological - the last 15 % of samples are the validation tail used only for the technical loss check (not an efficacy report).
* loss: MSE of the STFS forecast of the next 24 normalised bar descriptors (self-supervised, the source's STFS target).
* from_scratch: new weights (seeded); fine_tune: weights of --checkpoint, NEW run id, optimizer reset (data may differ);
  resume: --checkpoint must be a FULL state (weights + optimizer + RNG + step) of the SAME dataset hash and config -> continues the
  training state in a NEW version folder (--out/<run id>, resumed_from = the source version); the source (usually the ACTIVE version)
  is never written; nothing left to train (epoch >= --epochs) -> NOTHING_TO_DO.
* checkpoint (atomic, after every epoch): model, optimizer, epoch / step, RNG states, architecture, normaliser, dataset hash, schema,
  target, runtime / package versions; files last.pt (always), best_training_loss.pt (lowest TRAINING loss - not a quality claim).
* cancel: the cancel file (or SIGTERM) stops at the next batch; the last COMPLETE checkpoint stays (an interrupted epoch is not saved),
  nothing is activated. The time limit (--minutes) inside an epoch saves that epoch marked partial_epoch=True.
* trained_until = time of the last TARGET bar of the training samples; the validation tail starts after a FORECAST-bar embargo.
Last stdout line: RESULT {json}; holdout / accuracy / calibration are NOT computed here -> null with status NOT_RUN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import IMPLEMENTATION_ID, RUNTIME_VERSION

STOP = {"flag": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _status(p: str | None, **kw) -> None:
    if p:
        try:
            Path(p).write_text(json.dumps(kw), encoding="utf-8")
        except OSError:
            pass


def _atomic_save(torch, obj, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def dataset_hash(bars: list[dict]) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{int(float(b['t']))},{float(b['o']):.6f},{float(b['h']):.6f},{float(b['l']):.6f},{float(b['c']):.6f},{float(b.get('tv') or 0):.1f};".encode())
    return h.hexdigest()[:20]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sdformer_runtime.train")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--op", choices=["from_scratch", "fine_tune", "resume"], default="from_scratch")
    ap.add_argument("--checkpoint")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--context", default="")
    ap.add_argument("--cancel-file")
    ap.add_argument("--status-file")
    ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: STOP.update(flag=True))
    import numpy as np
    import torch
    from . import data as D
    from .ckpt import load_checkpoint
    from .model import SDformerFlow, n_params
    torch.set_num_threads(int(a.threads))
    t_start = time.time()
    bars = json.loads(Path(a.data).read_text(encoding="utf-8"))
    bars = bars.get("bars", bars) if isinstance(bars, dict) else bars
    dh = dataset_hash(bars)
    X, Y, T, idx = D.samples(bars)
    if len(X) < 64:
        print("RESULT " + json.dumps({"ok": False, "code": "NO_DATA", "error": f"za mało próbek ({len(X)}) – potrzeba min. 64 okien 120 + 24 świec"}))
        return 1
    run_id = a.run_id or ("SDF-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    out = Path(a.out) / run_id                     # 1.46: created only after the checkpoint checks (no empty version folder)
    resumed_from = None
    rng = np.random.default_rng(a.seed)
    torch.manual_seed(a.seed)
    n_tr = int(len(X) * 0.85)
    # 1.46: embargo - a sample's target covers the next FORECAST bars, so the validation tail starts at the first sample whose bar is
    # more than FORECAST bars after the last training sample (its targets overlapped the training targets: optimistic val_tail_loss)
    v0 = next((j for j in range(n_tr, len(X)) if idx[j] - idx[n_tr - 1] > D.FORECAST), len(X))
    trained_until = float(bars[idx[n_tr - 1] + D.FORECAST]["t"])     # 1.46: last TARGET bar seen in training (was its last INPUT bar)
    mu, sd = X[:n_tr].reshape(-1, D.DESCR).mean(0), X[:n_tr].reshape(-1, D.DESCR).std(0) + 1e-8      # normaliser: TRAINING rows only
    norm = lambda z: (z - mu) / sd                                                                       # noqa: E731
    Xn, Yn = torch.tensor(norm(X)), torch.tensor(norm(Y))
    TF = torch.tensor(D.time_features(T))
    model = SDformerFlow()
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    epoch0, step, best = 0, 0, float("inf")
    if a.op in ("fine_tune", "resume"):
        ck = load_checkpoint(Path(a.checkpoint) / "last.pt")                 # weights_only (1.46) + TorchVersion of 1.46.0 checkpoints
        if ck.get("implementation_id") != IMPLEMENTATION_ID or ck.get("arch") != model.arch:
            print("RESULT " + json.dumps({"ok": False, "code": "INCOMPATIBLE", "error": "checkpoint innej implementacji / architektury"}))
            return 1
        model.load_state_dict(ck["model"], strict=True)
        if a.op == "resume":
            if ck.get("dataset_hash") != dh or not ck.get("optimizer"):
                print("RESULT " + json.dumps({"ok": False, "code": "RESUME_MISMATCH", "error": "resume wymaga tego samego zbioru danych i pełnego stanu (optymalizator) – użyj fine_tune"}))
                return 1
            opt.load_state_dict(ck["optimizer"])
            epoch0, step, best = int(ck["epoch"]), int(ck["step"]), float(ck.get("best_training_loss", best))
            mu, sd = np.asarray(ck["normalizer"]["mu"], np.float32), np.asarray(ck["normalizer"]["sd"], np.float32)
            Xn, Yn = torch.tensor(norm(X)), torch.tensor(norm(Y))
            torch.set_rng_state(ck["rng"]["torch"])
            rng.bit_generator.state = ck["rng"]["numpy"]
            # 1.46: resume wrote into the checkpoint folder = the ACTIVE version (used by the live inference before any activation
            # test; a cancel left a half-written state; previous_run became the same id, so rollback restored nothing) - it now
            # continues the training state in its OWN new version folder, the source is only read
            resumed_from = ck.get("run_id")
            if out.resolve() == Path(a.checkpoint).resolve():
                print("RESULT " + json.dumps({"ok": False, "code": "RESUME_TARGET_IS_SOURCE", "run_id": run_id,
                                              "error": "resume zapisuje nową wersję – --run-id nie może wskazywać katalogu checkpointu"}))
                return 1
            if epoch0 >= a.epochs:
                print("RESULT " + json.dumps({"ok": False, "code": "NOTHING_TO_DO", "run_id": run_id, "resumed_from": resumed_from,
                                              "error": f"checkpoint ma już {epoch0} epok (≥ --epochs {a.epochs}) – nic do wznowienia"}))
                return 1
    out.mkdir(parents=True, exist_ok=True)
    w0 = {k: v.detach().clone() for k, v in model.state_dict().items() if v.dtype.is_floating_point}
    lossf = torch.nn.MSELoss()
    history = []
    cancelled = False
    for ep in range(epoch0, a.epochs):
        model.train()
        perm = rng.permutation(n_tr)
        tot, nb = 0.0, 0
        partial = False
        for b0 in range(0, n_tr, a.batch):
            if STOP["flag"] or (a.cancel_file and Path(a.cancel_file).exists()) or (time.time() - t_start) > a.minutes * 60:
                cancelled = STOP["flag"] or bool(a.cancel_file and Path(a.cancel_file).exists())
                partial = True
                break
            ib = perm[b0:b0 + a.batch]
            pred, _ = model(Xn[ib], TF[ib])
            loss = lossf(pred, Yn[ib])
            if not torch.isfinite(loss):
                print("RESULT " + json.dumps({"ok": False, "code": "NON_FINITE_LOSS", "error": "strata NaN/Inf – przerwano bez zapisu"}))
                return 1
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot, nb, step = tot + loss.item(), nb + 1, step + 1
            if nb % 10 == 0:
                _status(a.status_file, stage="TRAINING", epoch=ep + 1, epochs=a.epochs, batch=nb, step=step, train_loss=tot / nb)
                print(f"[SDF-TRAIN] epoka {ep + 1}/{a.epochs} krok {step} strata {tot / nb:.5f}", flush=True)
        if nb == 0:
            break
        if cancelled and partial:
            break                                  # 1.46: a cancelled, unfinished epoch is never saved as complete - last.pt keeps the last full one
        tr_loss = tot / nb
        model.eval()
        val_loss = None
        if v0 < len(X):
            with torch.no_grad():
                vp, _ = model(Xn[v0:], TF[v0:])
                val_loss = float(lossf(vp, Yn[v0:]))
        history.append({"epoch": ep + 1, "train_loss": tr_loss, "val_tail_loss": val_loss, "batches": nb, **({"partial_epoch": True} if partial else {})})
        state = {"implementation_id": IMPLEMENTATION_ID, "runtime": RUNTIME_VERSION, "arch": model.arch, "model": model.state_dict(),
                 "optimizer": opt.state_dict(), "epoch": ep + 1, "step": step, "rng": {"torch": torch.get_rng_state(), "numpy": rng.bit_generator.state},
                 "normalizer": {"mu": mu.tolist(), "sd": sd.tolist(), "fitted_on": "training rows"}, "dataset_hash": dh, "run_id": run_id,
                 "schema": {"descriptor": list(D.NAMES), "history": D.HISTORY, "forecast": D.FORECAST, "order": "OLDEST_TO_NEWEST"},
                 "target": "STFS_NEXT24_DESCRIPTORS", "context": a.context, "deps": {"torch": str(torch.__version__), "numpy": str(np.__version__)},
                 "trained_until": trained_until, "best_training_loss": min(best, tr_loss), "history": history, "saved_at": _now(),
                 "resumed_from": resumed_from, "partial_epoch": partial}
        _atomic_save(torch, state, out / "last.pt")
        if tr_loss < best:
            best = tr_loss
            _atomic_save(torch, state, out / "best_training_loss.pt")
        print(f"[SDF-TRAIN] epoka {ep + 1} zapisana: strata trening {tr_loss:.5f}, ogon walidacyjny "
              f"{'brak (embargo)' if val_loss is None else f'{val_loss:.5f}'}", flush=True)
        if cancelled:
            break
    changed = any(not torch.equal(w0[k], v) for k, v in model.state_dict().items() if k in w0)
    ok = (out / "last.pt").exists() and changed and not cancelled
    res = {"ok": ok, "code": None if ok else ("CANCELLED" if cancelled else "NO_CHECKPOINT"), "run_id": run_id, "dir": str(out), "op": a.op,
           "resumed_from": resumed_from,
           "dataset_hash": dh, "samples": int(len(X)), "train_samples": n_tr, "params": n_params(model), "epochs_done": len(history) + epoch0,
           "steps": step, "weights_changed": bool(changed), "history": history, "seconds": round(time.time() - t_start, 1),
           "metrics": {"holdout": None, "accuracy": None, "calibration": None, "status": "NOT_RUN"}, "implementation_id": IMPLEMENTATION_ID}
    (out / "sdformer_run.json").write_text(json.dumps({k: v for k, v in res.items()}, indent=2), encoding="utf-8")
    print("RESULT " + json.dumps(res), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
