"""STFS - spatio-temporal feature sampling for financial event feature maps (PMW-MM-STFS-1). Training-only, ZERO learnable parameters.

Source principle (S3CE-Net, event-based person re-ID): during training, sample temporal sub-sets and spatial patches of the feature map,
aggregate them and supervise the views, to broaden semantic coverage; no sampling at inference. Financial adaptation (documented
deviations): the feature map is the event encoder's per-event hidden state H[B, T, C] (time = event order inside a unit, C = latent GRU
channels). Latent channels have no semantic map, so the "spatial" view samples seed-controlled random CHANNEL SUBSETS
(`LATENT_CHANNEL_RANDOM_SUBSETS`, RELATIONSHIP_MAP_UNAVAILABLE) - no claim that a subset is a market concept, and no adjacency grouping.
Views (all mask-aware, parameter-free):
  temporal  = mean over k sampled valid time positions (sorted, without replacement) of H[b, t, :]            -> [B, C]
  feature   = per subset S: time-mean of H[b, :, S], scattered back into C with zeros and scaled by C/|S|   -> [B, C] (mean over subsets)
  global    = mean over all valid (t) of H[b, t, :]                                                            -> [B, C]
The SSAM attention of S3CE-Net does not exist in this repository and is NOT re-implemented (no specification): STFS is inserted after
the existing event encoder (mm.event_engine). Losses: label-smoothed cross-entropy through the model's EXISTING direction head (its
descriptor block W_q, b) and a batch-hard triplet loss on L2-normalised view embeddings (distance = 1 - cosine). Batches without a valid
anchor/positive/negative report zero valid triplets (loss term 0, no fabricated pairs).
"""
from __future__ import annotations

import numpy as np

from ..lab import autodiff as A

VERSION = "PMW-MM-STFS-1"


class STFS:
    n_params = 0                                                            # parameter-free by construction

    def __init__(self, k_time: int = 6, n_subsets: int = 3, subset_frac: float = 0.5, seed: int = 11):
        if k_time < 1 or n_subsets < 1 or not (0 < subset_frac <= 1):
            raise ValueError("STFS_CONFIG_INVALID")
        self.k_time, self.n_subsets, self.frac = k_time, n_subsets, subset_frac
        self.rng = np.random.Generator(np.random.PCG64(seed))
        self.grouping = "LATENT_CHANNEL_RANDOM_SUBSETS"
        self.last_meta: dict = {}

    def views(self, H: A.T, mask: np.ndarray, training: bool) -> dict | None:
        """H: autodiff tensor [B, T, C]; mask: bool [B, T] valid positions. Returns None in evaluation (no random views)."""
        if not training:
            return None
        B, T, C = H.data.shape
        m = mask.astype(float)
        cnt = m.sum(axis=1)
        if np.any(cnt == 0):
            raise ValueError("STFS_EMPTY_SEQUENCE")
        sel = np.zeros((B, T))
        for b in range(B):
            v = np.where(mask[b])[0]
            k = min(self.k_time, len(v))
            sel[b, np.sort(self.rng.choice(v, k, replace=False))] = 1.0
        w_t = sel / sel.sum(axis=1, keepdims=True)
        temporal = (H * w_t[:, :, None]).sum(axis=1)
        w_all = m / cnt[:, None]
        global_ = (H * w_all[:, :, None]).sum(axis=1)
        k_ch = max(1, int(round(self.frac * C)))
        subsets = [np.sort(self.rng.choice(C, k_ch, replace=False)) for _ in range(self.n_subsets)]
        fv = None
        for S in subsets:
            cm = np.zeros(C)
            cm[S] = C / len(S)
            part = global_ * cm[None, :]
            fv = part if fv is None else fv + part
        feature = fv * (1.0 / self.n_subsets)
        self.last_meta = {"time_selected": sel.astype(bool), "subsets": [s.tolist() for s in subsets], "grouping": self.grouping}
        return {"temporal": temporal, "feature": feature, "global": global_}


def label_smoothed_ce(logits: A.T, y: np.ndarray, eps: float) -> A.T:
    if not (0 <= eps < 1):
        raise ValueError("LABEL_SMOOTHING_INVALID")
    K = logits.data.shape[1]
    if np.any((y < 0) | (y >= K)):
        raise ValueError("TARGET_INDEX_INVALID")
    q = np.full((len(y), K), eps / K)
    q[np.arange(len(y)), y] += 1 - eps
    return -(A.log_softmax(logits, axis=1) * q).sum(axis=1).mean()


def triplet_batch_hard(E: A.T, y: np.ndarray, margin: float = 0.2) -> tuple[A.T, int]:
    """E: [B, C] embeddings (L2-normalised here). d = 1 - cos. For each anchor: hardest positive (same label, != itself) and hardest
    negative. Returns (mean loss over valid anchors, n_valid). n_valid = 0 -> a zero tensor."""
    norm = A.T(np.sqrt((E.data ** 2).sum(axis=1, keepdims=True)) + 1e-12)
    Z = E / norm
    S = Z @ Z.transpose(1, 0)
    D = 1.0 - S
    B = len(y)
    terms = []
    for a in range(B):
        pos = np.where((y == y[a]) & (np.arange(B) != a))[0]
        neg = np.where(y != y[a])[0]
        if not len(pos) or not len(neg):
            continue
        p = pos[np.argmax(D.data[a, pos])]
        n = neg[np.argmin(D.data[a, neg])]
        terms.append(A.relu(D[a, p] - D[a, n] + margin))
    if not terms:
        return A.T(0.0), 0
    tot = terms[0]
    for t in terms[1:]:
        tot = tot + t
    return tot * (1.0 / len(terms)), len(terms)
