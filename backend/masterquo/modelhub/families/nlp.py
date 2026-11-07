"""NLP_SENTIMENT - text sentiment (NEGATIVE / NEUTRAL / POSITIVE of the TEXT, not classes of the XAUUSD move).

Corpus: imported JSONL / CSV records {id, source, lang, text, label, topic?, published_at, first_seen_at, version}; deduplicated by a hash
of normalised text before training and aggregation. Chronological split by first_seen_at (information is usable only from when it was
seen). Baseline: TF-IDF (1-2 grams) + multinomial logistic regression, temperature calibrated on validation; metrics macro-F1, log loss,
confusion. Optional local transformer (deep_runtime.nlp) only from a local checkpoint the user is licensed to use - never downloaded here.
Runtime: the existing news module's recent headlines (headline only - marked) -> per-text sentiment + topic relevance (gold / USD / Fed /
BTC keywords) + exponentially decayed aggregate by first_seen_at. Without a corpus: BLOCKED_DATA (waiting for data); it never creates
orders from text.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import time
from pathlib import Path

import numpy as np

from . import base as B

LABELS = ("NEGATIVE", "NEUTRAL", "POSITIVE")
TOPICS = {"GOLD": ("gold", "xau", "bullion", "złoto"), "USD": ("dollar", "usd", "dxy", "treasury"), "FED": ("fed", "fomc", "powell", "rate"),
          "BTC": ("bitcoin", "btc", "crypto")}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def text_hash(t: str) -> str:
    return hashlib.sha256(norm(t).encode()).hexdigest()[:20]


def corpus_path() -> Path:
    return B.root() / "_corpus" / "nlp_corpus.jsonl"


def import_file(path: Path) -> dict:
    """JSONL or CSV -> corpus (dedup by text hash; label must be one of LABELS)."""
    cp = corpus_path()
    cp.parent.mkdir(parents=True, exist_ok=True)
    have = {r["hash"] for r in load_corpus()}
    rows, bad = [], 0
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            src = list(csv.DictReader(f))
    else:
        src = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in src:
        lab = str(r.get("label") or "").upper()
        if not r.get("text") or lab not in LABELS:
            bad += 1
            continue
        h = text_hash(r["text"])
        if h in have:
            continue
        have.add(h)
        rows.append({"hash": h, "id": r.get("id") or h, "source": r.get("source"), "lang": r.get("lang") or "en", "text": r["text"], "label": lab,
                     "published_at": r.get("published_at"), "first_seen_at": r.get("first_seen_at") or r.get("published_at"), "version": r.get("version")})
    with cp.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"added": len(rows), "rejected": bad, "total": len(have)}


def load_corpus() -> list[dict]:
    p = corpus_path()
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def proba3s(m, Xs) -> np.ndarray:
    """3-class probabilities for a (sparse) matrix, missing classes kept at ~0."""
    p = np.asarray(m.predict_proba(Xs), dtype=float)
    out = np.full((Xs.shape[0], 3), 1e-9)
    for j, c in enumerate(m.classes_):
        out[:, int(c)] = p[:, j]
    return out / out.sum(axis=1, keepdims=True)


def topics(text: str) -> dict:
    t = norm(text)
    return {k: (1.0 if any(w in t for w in ws) else 0.0) for k, ws in TOPICS.items()}


class NLP(B.Family):
    ID = "NLP_SENTIMENT"
    NAME = "Sentyment tekstu – TF-IDF + regresja logistyczna (+ opcjonalny lokalny transformer)"
    KIND = "TRAINED"
    TASK_TYPE = "NLP_SENTIMENT"
    UNIT = "sentiment"
    TASK = "TEXT_SENTIMENT_3"
    DEPS = ("sklearn",)
    TF = None
    HORIZONS = ()
    RECEIVERS = ("AGENT:news_context", "PANEL:news_sentiment", "RISK:information_context (OBSERVE)")
    DATA = {"kind": "TEXT", "source": "import JSONL/CSV (oznaczony korpus) + nagłówki z news/", "min_records": 300}

    def validate_data(self, data):
        n = len(data.get("corpus") or [])
        need = self.DATA["min_records"]
        return (n >= need, None if n >= need else f"za mało oznaczonych tekstów: {n} < {need} (import JSONL/CSV)")

    def fit(self, data, cfg, tmp, budget):
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import confusion_matrix, f1_score
        rows = sorted(data["corpus"], key=lambda r: str(r.get("first_seen_at") or ""))
        X = [r["text"] for r in rows]
        y = np.asarray([LABELS.index(r["label"]) for r in rows])
        n = len(y)
        a, b = int(n * 0.6), int(n * 0.8)
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000, sublinear_tf=True)
        Xa = vec.fit_transform(X[:a])
        m = LogisticRegression(max_iter=1000, C=2.0).fit(Xa, y[:a])
        from ...trainhub.learn import Prior, calibrate, logloss, temperature
        pv = proba3s(m, vec.transform(X[a:b]))
        T = temperature(pv, y[a:b])
        pvc = calibrate(pv, T)
        val = {"val_macro_f1": float(f1_score(y[a:b], pvc.argmax(1), average="macro")), "val_log_loss": logloss(pvc, y[a:b]),
               "val_baseline_log_loss": logloss(Prior().fit(None, y[:a]).predict_proba(np.zeros(b - a)), y[a:b])}
        vec2 = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000, sublinear_tf=True)
        m2 = LogisticRegression(max_iter=1000, C=2.0).fit(vec2.fit_transform(X[:b]), y[:b])
        ph = calibrate(proba3s(m2, vec2.transform(X[b:])), T)
        hold = {"macro_f1": float(f1_score(y[b:], ph.argmax(1), average="macro")), "log_loss": logloss(ph, y[b:]),
                "confusion": confusion_matrix(y[b:], ph.argmax(1), labels=[0, 1, 2]).tolist(), "n": int(n - b)}
        joblib.dump({"vec": vec2, "clf": m2, "T": T}, tmp / "nlp.joblib")
        sample_txt = X[-5:]
        exp = calibrate(proba3s(m2, vec2.transform(sample_txt)), T).tolist()
        vm = {"val_macro_f1": val["val_macro_f1"], "val_skill": 1 - val["val_log_loss"] / val["val_baseline_log_loss"] if val["val_baseline_log_loss"] else None}
        return {"metrics": {**val, "holdout": hold, "dedup": "hash znormalizowanego tekstu", "split": "chronologiczny wg first_seen_at",
                            "label_note": "sentyment tekstu ≠ ruch XAUUSD; wpływ na rynek wymaga osobnej walidacji"},
                "validation": self.promotion(vm, {"val_skill": (">", 0.0)}),
                "sample": {"texts": sample_txt, "expected": exp, "tolerance": 1e-9}}

    def load(self, d):
        import joblib
        return joblib.load(d / "nlp.joblib")              # trusted path: our own artifact directory only

    def score(self, art, texts: list[str]) -> np.ndarray:
        from ...trainhub.learn import calibrate
        return calibrate(proba3s(art["clf"], art["vec"].transform(texts)), art["T"])

    def predict(self, art, live):
        items = [n for n in (live.get("news") or []) if n.get("headline")]
        if not items:
            raise B.Unavailable("BLOCKED_DATA", "brak nagłówków z news/ (feed wyłączony lub pusty)")
        seen = {}
        for n in items:
            seen.setdefault(text_hash(n["headline"]), n)
        items = list(seen.values())
        P = self.score(art, [n["headline"] for n in items])
        now = time.time()
        w = []
        from ...indicators.contract import ts as _ts
        for n in items:
            try:
                age = max(0.0, now - (_ts(n.get("first_seen_at") or n.get("published_at")) or now))
            except (TypeError, ValueError):
                age = 86400.0
            w.append(math.exp(-age / (6 * 3600)))
        w = np.asarray(w)
        agg = (P * w[:, None]).sum(0) / max(w.sum(), 1e-12)
        top = {k: float(np.mean([topics(n["headline"])[k] for n in items])) for k in TOPICS}
        return {"sentiment": {LABELS[i]: float(agg[i]) for i in range(3)}, "texts": len(items), "decay_half_life_h": 6 * math.log(2),
                "topic_share": top, "input": "nagłówki (bez pełnej treści)"}
