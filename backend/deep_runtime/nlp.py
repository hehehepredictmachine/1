"""Optional local transformer sentiment (e.g. a financial checkpoint the user is licensed to use), loaded ONLY from a local
directory (no download during import). Without the `transformers` package or the checkpoint the caller reports BLOCKED and the
TF-IDF baseline in the bot keeps working."""
from __future__ import annotations

from pathlib import Path


def predict(req):
    ck = Path(req.get("checkpoint") or "")
    if not ck.is_dir():
        return {"ok": False, "error": "CHECKPOINT_NOT_FOUND"}
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(ck), local_files_only=True)
    m = AutoModelForSequenceClassification.from_pretrained(str(ck), local_files_only=True)
    m.eval()
    with torch.no_grad():
        enc = tok(req["texts"], padding=True, truncation=True, max_length=128, return_tensors="pt")
        p = torch.softmax(m(**enc).logits, -1).numpy().tolist()
    return {"ok": True, "p": p, "labels": [m.config.id2label[i] for i in range(len(m.config.id2label))]}
