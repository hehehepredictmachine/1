"""Local transformer sentiment - NOT CONNECTED in 1.46 (experimental tool, I0223 / I0471): no module of the bot calls the worker op
nlp_predict, families.nlp_transformer_path is not read, and `transformers` is not in requirements-deep-win.txt. NLP_SENTIMENT is
the TF-IDF + logistic regression model of masterquo.modelhub.families.nlp. If called directly: a checkpoint is loaded ONLY from a
local directory (no download), a missing one -> CHECKPOINT_NOT_FOUND."""
from __future__ import annotations

from pathlib import Path


def predict(req):
    # 1.46: Path("") is the working directory (is_dir() True) - a missing checkpoint tried to load transformers from the CWD
    ck = Path(req["checkpoint"]) if req.get("checkpoint") else None
    if ck is None or not ck.is_dir():
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
