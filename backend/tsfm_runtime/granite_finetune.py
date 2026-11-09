"""Fine-tuning of Granite TTM on the user's own closed bars (runs ONLY in .venv_granite, started by the Training Center - never with the bot).

  python -m tsfm_runtime.granite_finetune --data <dataset.json> --weights-root DIR --out DIR --horizon 12 [--epochs 6] [--threads 2]
                                          [--stride 4] [--lr 1e-3] [--seed 7] [--status-file F]

Dataset: written by masterquo/tsfm/granite_train.export (closed bars of ONE instrument / timeframe, sorted, validated): times, open, high,
low, close + metadata (data kind, symbol, sha256). Windows: the last 512 closes before an origin -> the next H closes; z-score of the
CONTEXT window only (the same as the live adapter), MSE on the H steps in normalized units.
Chronological split with an embargo of (512 + H) bars between parts: train 70 % / validation 15 % / test 15 % - the test part is never seen
by training or early stopping. Recipe of the TTM authors for few-shot adaptation: the backbone is frozen, the decoder + head are trained.
Report on the TEST part (unseen): MAE / RMSE at H and direction hit rate (neutral band 0.25 x ATR14, the bot's rule) for the fine-tuned
model, the pretrained base and the naive "last price" - written honestly whatever the result. The checkpoint (config.json +
model.safetensors) is saved with granite_finetune.json (sha256 of both files, base fingerprint, data range, metrics). It is NOT activated
here: activation is a separate, explicit step in the bot (checkpoint = run id; rollback = BASE).
Progress: "[GRANITE-TRAIN] [k/n] ..." lines, a status file, the last line "RESULT <json>". SIGTERM / closing = clean stop, nothing saved.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import lock
from . import manifest as M

STOP = {"flag": False}


def say(status_file, step, total, msg, state="RUNNING"):
    line = f"[GRANITE-TRAIN] [{step}/{total}] {msg}"
    print(line, flush=True)
    if status_file:
        try:
            Path(status_file).write_text(json.dumps({"state": state, "step": step, "total": total, "message": msg,
                                                     "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False),
                                         encoding="utf-8")
        except OSError:
            pass


def atr14(h, l, c, i):
    trs = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(i - 13, i + 1)]
    return sum(trs) / 14.0


def windows(n: int, ctx: int, H: int, stride: int):
    """Origins i (index of the LAST context bar) split chronologically with an embargo of ctx + H bars between the parts."""
    idx = list(range(ctx - 1, n - H))
    if len(idx) * 0.15 <= (ctx + H) + 50:
        raise ValueError(f"za mało świec: {n} – walidacja i test (po 15 %) muszą być dłuższe niż embargo {ctx + H} świec (ok. 5000 świec)")
    a, b = int(len(idx) * 0.70), int(len(idx) * 0.85)
    emb = ctx + H
    train = idx[:a][::stride]
    val = idx[a + emb:b][::max(1, stride // 2)]
    test = idx[b + emb:][::H]                          # non-overlapping horizons on the unseen part
    if not (train and val and test):
        raise ValueError("za mało świec po podziale z embargo (trening / walidacja / test)")
    return train, val, test


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tsfm_runtime.granite_finetune")
    ap.add_argument("--data", required=True)
    ap.add_argument("--weights-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--horizon", type=int, required=True)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--stride", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--run-id")
    ap.add_argument("--status-file")
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: STOP.update(flag=True))
    os.environ["HF_HUB_OFFLINE"] = "1"
    total = 6
    res: dict = {"ok": False}
    try:
        say(a.status_file, 1, total, "wczytuję zbiór danych i sprawdzam model bazowy")
        ds = json.loads(Path(a.data).read_text(encoding="utf-8"))
        c = [float(x) for x in ds["close"]]
        h, l = [float(x) for x in ds["high"]], [float(x) for x in ds["low"]]
        if not all(math.isfinite(x) and x > 0 for x in c):
            raise ValueError("zbiór zawiera nieprawidłowe ceny (NaN / ≤ 0) – odrzucony")
        pin = lock.model("granite_ttm")
        ctx, H = pin["max_context"], int(a.horizon)
        if not 1 <= H <= pin["native_horizon"]:
            raise ValueError(f"horyzont {H} poza zakresem 1..{pin['native_horizon']}")
        M.verify(a.weights_root, "granite_ttm")
        base_dir = M.model_dir(a.weights_root, "granite_ttm")
        import numpy as np
        import torch
        from .engines import _ttm_class
        torch.manual_seed(a.seed)
        np.random.seed(a.seed)
        torch.set_num_threads(max(1, a.threads))
        TTM = _ttm_class()
        base = TTM.from_pretrained(str(base_dir), local_files_only=True).eval()
        model = TTM.from_pretrained(str(base_dir), local_files_only=True)
        tr, va, te = windows(len(c), ctx, H, max(1, a.stride))
        C = np.asarray(c, dtype=np.float64)

        def batch(ix):
            X = np.stack([C[i - ctx + 1:i + 1] for i in ix])
            Y = np.stack([C[i + 1:i + 1 + H] for i in ix])
            mu, sd = X.mean(1, keepdims=True), X.std(1, keepdims=True)
            sd[sd <= 0] = 1.0
            return (torch.tensor(((X - mu) / sd)[:, :, None], dtype=torch.float32), torch.tensor((Y - mu) / sd, dtype=torch.float32),
                    mu[:, 0], sd[:, 0])

        def predict(m, ix):
            out = []
            m.eval()
            with torch.inference_mode():
                for k in range(0, len(ix), 256):
                    Xb, _, mu, sd = batch(ix[k:k + 256])
                    y = m(past_values=Xb).prediction_outputs[:, :H, 0].numpy().astype(np.float64)
                    out.append(y * sd[:, None] + mu[:, None])
            return np.concatenate(out)

        def val_loss(m):
            m.eval()
            with torch.inference_mode():
                Xb, Yb, _, _ = batch(va)
                return float(torch.mean((m(past_values=Xb).prediction_outputs[:, :H, 0] - Yb) ** 2))

        for name, p in model.named_parameters():
            p.requires_grad = not name.startswith("backbone.")                # TTM few-shot recipe: frozen backbone
        trainable = [p for p in model.parameters() if p.requires_grad]
        n_train = sum(p.numel() for p in trainable)
        opt = torch.optim.AdamW(trainable, lr=a.lr, weight_decay=1e-4)
        say(a.status_file, 2, total, f"okna: trening {len(tr)}, walidacja {len(va)}, test {len(te)} (bez nakładania); trenowane parametry {n_train} "
                                     f"(backbone zamrożony); wątki CPU {torch.get_num_threads()}")
        best, best_state, history = val_loss(model), None, []
        base_val = best
        t0 = time.perf_counter()
        rng = np.random.default_rng(a.seed)
        for ep in range(a.epochs):
            if STOP["flag"]:
                raise KeyboardInterrupt
            model.train()
            order = rng.permutation(len(tr))
            for k in range(0, len(order), a.batch):
                if STOP["flag"]:
                    raise KeyboardInterrupt
                Xb, Yb, _, _ = batch([tr[j] for j in order[k:k + a.batch]])
                loss = torch.mean((model(past_values=Xb).prediction_outputs[:, :H, 0] - Yb) ** 2)
                opt.zero_grad()
                loss.backward()
                opt.step()
            vl = val_loss(model)
            history.append({"epoch": ep + 1, "val_mse": vl})
            if vl < best:
                best, best_state = vl, {k: v.detach().clone() for k, v in model.state_dict().items()}
            say(a.status_file, 3, total, f"epoka {ep + 1}/{a.epochs}: MSE walidacji {vl:.5f} (bazowy {base_val:.5f}, najlepszy {best:.5f})")
        if best_state is not None:
            model.load_state_dict(best_state)
        train_s = time.perf_counter() - t0
        say(a.status_file, 4, total, "ocena na niewidzianej części testowej")
        pf, pb = predict(model, te), predict(base, te)
        y = np.asarray([c[i + H] for i in te])
        last = np.asarray([c[i] for i in te])

        def metrics(pred):
            e = pred[:, H - 1] - y
            hits = n = 0
            for j, i in enumerate(te):
                band = 0.25 * atr14(h, l, c, i)
                dp, da = pred[j, H - 1] - last[j], y[j] - last[j]
                if abs(dp) <= band or abs(da) <= band:
                    continue
                n += 1
                hits += int((dp > 0) == (da > 0))
            return {"mae_h": float(np.mean(np.abs(e))), "rmse_h": float(np.sqrt(np.mean(e * e))), "direction_n": n,
                    "direction_hit": (hits / n) if n else None}
        mf, mb = metrics(pf), metrics(pb)
        naive = {"mae_h": float(np.mean(np.abs(last - y))), "rmse_h": float(np.sqrt(np.mean((last - y) ** 2)))}
        verdict = ("IMPROVED_VS_BASE" if mf["mae_h"] < mb["mae_h"] else "NOT_BETTER_THAN_BASE")
        note = ("lepszy od modelu bazowego" if verdict == "IMPROVED_VS_BASE" else "nie lepszy od modelu bazowego – nie aktywuj") + \
               ("; lepszy od prognozy „ostatnia cena”" if mf["mae_h"] < naive["mae_h"] else "; NIE lepszy od prognozy „ostatnia cena” (błądzenie losowe)")
        if STOP["flag"]:
            raise KeyboardInterrupt
        say(a.status_file, 5, total, "zapis checkpointu (bez aktywacji)")
        run_id = a.run_id or ("GTR-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
        out = Path(a.out) / run_id
        out.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(out), safe_serialization=True)
        files = [{"name": f, "sha256": M.sha256_file(out / f), "size": (out / f).stat().st_size} for f in ("config.json", "model.safetensors")]
        man = {"schema": "PMW-GRANITE-FT-1", "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "base_fingerprint": lock.fingerprint("granite_ttm"), "files": files,
               "data": {k: ds.get(k) for k in ("instrument", "symbol", "timeframe", "data_kind", "first", "last", "bars", "sha256", "source")},
               "train": {"context": ctx, "horizon": H, "epochs": a.epochs, "lr": a.lr, "batch": a.batch, "stride": a.stride, "seed": a.seed,
                         "threads": torch.get_num_threads(), "trainable_params": n_train, "frozen": "backbone", "train_s": round(train_s, 1),
                         "windows": {"train": len(tr), "val": len(va), "test": len(te)}, "embargo_bars": ctx + H, "history": history},
               "metrics": {"test_finetuned": mf, "test_base": mb, "test_naive_last_price": naive, "val_mse_base": base_val, "val_mse_best": best,
                           "verdict": verdict, "note": note,
                           "rule": "część testowa (15 % końca) nie była używana w treningu ani do wyboru epoki; horyzonty bez nakładania"}}
        (out / "granite_finetune.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        res = {"ok": True, "run_id": run_id, "dir": str(out), "metrics": man["metrics"], "train": man["train"]}
        say(a.status_file, 6, total, f"gotowe: {run_id} – {note}", state="DONE")
    except KeyboardInterrupt:
        res = {"ok": False, "code": "CANCELLED", "error": "trening przerwany – nic nie zapisano"}
        say(a.status_file, 6, total, res["error"], state="FAILED")
    except M.ManifestError as exc:
        res = {"ok": False, "code": exc.code, "error": exc.detail}
        say(a.status_file, 6, total, f"BŁĄD {exc.code}: {exc.detail}", state="FAILED")
    except (ValueError, KeyError, OSError) as exc:
        res = {"ok": False, "code": "DATA", "error": f"{type(exc).__name__}: {exc}"[:400]}
        say(a.status_file, 6, total, f"BŁĄD: {res['error']}", state="FAILED")
    except MemoryError as exc:
        res = {"ok": False, "code": "RESOURCE_LIMIT", "error": f"MemoryError: {exc}"[:300]}
    print("RESULT " + json.dumps(res, ensure_ascii=False), flush=True)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
