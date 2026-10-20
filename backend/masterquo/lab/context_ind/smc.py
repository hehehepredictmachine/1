"""PWM_PULLBACK_CLOSED_v1 (VS03) and PWM_SMC_PULLBACK_BAR_ATOMIC_v1 (VS04) - own profiles; S02/S03 sources not read (no source parity).

Pullback: one search side; HIGH tracks the highest high of the leg and the reference = LOW of that same candle (LOW mirrored). On each
closed bar, against the state BEFORE the bar: new extreme only -> move tracked + reference; reference broken only -> confirm the old
extreme, start the opposite leg from this bar; both (outside bar) -> confirm THIS bar's extreme, start the opposite leg from this bar.
Break: WICK low<ref (HIGH) / high>ref (LOW), or CLOSE profile. Equality never confirms; equal extremes keep the earlier origin. Prices are
compared on the tick grid. Confirmed swings are immutable (append-only ledger) with origin, confirming bar and available_at.

SMC (atomic closed-bar convention, not an intrabar order): exactly one H slot and one L slot (UNSEEDED/ACTIVE/PENDING); seed from the first
valid confirmed pullback pair (H > L), trend NONE. Order per bar: pullback step -> pending trail + IDM ratchet + IDM test (never on the
breaking bar) -> close break vs ACTIVE levels (both sides = CORRUPT_STATE) -> opposite break with an open pending publishes its trail with
OPPOSITE_BREAK_FALLBACK -> earlier opposite sweep candidate becomes x (relocation = new point version) -> BoS/CHoCH (table NONE/UP/DOWN)
-> alternation anchor -> new pending. Without a break: wick candidates only against levels ACTIVE before the bar. Events are append-only
with a local seq; relocations never edit earlier events; as-of views rebuild point versions known at a cutoff."""
from __future__ import annotations

import hashlib
import json

PB_PROFILE = "PWM_PULLBACK_CLOSED_v1"
SMC_PROFILE = "PWM_SMC_PULLBACK_BAR_ATOMIC_v1"
EVENT_BITS = {"BOS_UP": 1, "BOS_DOWN": 2, "CHOCH_UP": 4, "CHOCH_DOWN": 8, "IDM": 16, "X_H": 32, "X_L": 64, "ANCHOR": 128,
              "STRUCTURE_H": 256, "STRUCTURE_L": 512, "FALLBACK": 1024}


class Pullback:
    def __init__(self, break_mode: str = "WICK", tick: float = 0.01, start: str = "HIGH"):
        if break_mode not in ("WICK", "CLOSE") or start not in ("HIGH", "LOW"):
            raise ValueError("PULLBACK_CONFIG_INVALID")
        self.mode, self.tick, self.start = break_mode, tick, start
        self.side = None
        self.ext = self.ext_bar = self.ref = self.ref_bar = None
        self.ledger: list[dict] = []
        self.last_bar = None

    def q(self, x: float) -> int:
        return round(x / self.tick)

    def checkpoint(self) -> dict:
        return {"side": self.side, "ext": self.ext, "ext_bar": self.ext_bar, "ref": self.ref, "ref_bar": self.ref_bar, "n": len(self.ledger),
                "last_bar": self.last_bar}

    def _confirm(self, kind, price, origin, i, t_close, reason, ref):
        sw = {"swing_id": f"PB-{kind}-{origin}-{len(self.ledger)}", "seq": len(self.ledger), "side": kind, "price": price, "origin_bar": origin,
              "confirming_bar": i, "available_at": t_close, "reason": reason, "reference_used": ref, "profile": PB_PROFILE, "mode": self.mode}
        self.ledger.append(sw)
        return sw

    def update(self, i: int, bar: dict, t_close: float) -> list[dict]:
        if self.last_bar is not None and i <= self.last_bar:
            return []                                                   # replayed / out-of-order bar: no second step
        self.last_bar = i
        h, lo, c = float(bar["h"]), float(bar["l"]), float(bar["c"])
        if self.side is None:
            self.side = self.start
            self.ext, self.ext_bar = (h, i) if self.side == "HIGH" else (lo, i)
            self.ref, self.ref_bar = (lo, i) if self.side == "HIGH" else (h, i)
            return []
        out = []
        if self.side == "HIGH":
            new = self.q(h) > self.q(self.ext)
            broken = (self.q(lo) < self.q(self.ref)) if self.mode == "WICK" else (self.q(c) < self.q(self.ref))
            if broken:
                if new:
                    out.append(self._confirm("H", h, i, i, t_close, "OUTSIDE", self.ref))
                else:
                    out.append(self._confirm("H", self.ext, self.ext_bar, i, t_close, "NORMAL", self.ref))
                self.side, self.ext, self.ext_bar, self.ref, self.ref_bar = "LOW", lo, i, h, i
            elif new:
                self.ext, self.ext_bar, self.ref, self.ref_bar = h, i, lo, i
        else:
            new = self.q(lo) < self.q(self.ext)
            broken = (self.q(h) > self.q(self.ref)) if self.mode == "WICK" else (self.q(c) > self.q(self.ref))
            if broken:
                if new:
                    out.append(self._confirm("L", lo, i, i, t_close, "OUTSIDE", self.ref))
                else:
                    out.append(self._confirm("L", self.ext, self.ext_bar, i, t_close, "NORMAL", self.ref))
                self.side, self.ext, self.ext_bar, self.ref, self.ref_bar = "HIGH", h, i, lo, i
            elif new:
                self.ext, self.ext_bar, self.ref, self.ref_bar = lo, i, h, i
        return out

    def provisional(self) -> dict | None:
        return None if self.side is None else {"side": self.side, "tracked": self.ext, "origin_bar": self.ext_bar, "reference": self.ref,
                                               "status": "PROVISIONAL (nie jest potwierdzonym wejściem)"}


class SMC:
    def __init__(self, idm_mode: str = "WICK", detect_sweeps: bool = True, pb_mode: str = "WICK", tick: float = 0.01):
        if idm_mode not in ("WICK", "CLOSE"):
            raise ValueError("IDM_MODE_INVALID")
        self.idm_mode, self.sweeps_on, self.tick = idm_mode, detect_sweeps, tick
        self.pb = Pullback(pb_mode, tick)
        self.profile = {"profile": SMC_PROFILE, "idm_mode": idm_mode, "detect_sweeps": detect_sweeps, "pullback": PB_PROFILE, "pb_mode": pb_mode}
        self.reset()

    def reset(self):
        self.trend = "NONE"
        self.slot = {"H": {"status": "UNSEEDED"}, "L": {"status": "UNSEEDED"}}
        self.points: dict[str, dict] = {}          # point_id -> current version
        self.versions: list[dict] = []             # append-only point versions
        self.chain: list[str] = []                 # confirmed structure chain (point ids, alternating)
        self.pending = None
        self.sweep = {"H": None, "L": None}
        self.events: list[dict] = []
        self.seq = 0
        self.bars: list[dict] = []
        self.last_pb = {"H": None, "L": None}

    # ---------------------------------------------------------------- helpers
    def _ev(self, kind, i, t_close, **kw):
        self.seq += 1
        e = {"event_id": f"EV-{self.seq}", "seq": self.seq, "kind": kind, "bar": i, "available_at": t_close, **kw}
        self.events.append(e)
        return e

    def _publish(self, side, price, origin, i, t_close, reason, **kw):
        pid = f"SP-{side}-{origin}-{len(self.versions)}"
        v = {"point_id": pid, "version": 1, "side": side, "price": price, "origin_bar": origin, "published_bar": i, "available_at": t_close,
             "reason": reason, **kw}
        self.points[pid] = v
        self.versions.append(dict(v))
        self.chain.append(pid)
        self.slot[side] = {"status": "ACTIVE", "level": price, "point_id": pid, "version": 1}
        self._ev("STRUCTURE_" + side, i, t_close, point_id=pid, price=price, origin_bar=origin, reason=reason)
        self.sweep = {"H": None, "L": None}                            # new generation of levels: stale candidates dropped
        return pid

    def _hl_range(self, a, b, side):
        seg = self.bars[a:b + 1]
        if side == "H":
            k = max(range(len(seg)), key=lambda j: (seg[j]["h"], -j))
            return seg[k]["h"], a + k
        k = min(range(len(seg)), key=lambda j: (seg[j]["l"], j))
        return seg[k]["l"], a + k

    # ---------------------------------------------------------------- step
    def update(self, bar: dict, t_close: float) -> dict:
        i = len(self.bars)
        self.bars.append({"h": float(bar["h"]), "l": float(bar["l"]), "c": float(bar["c"]), "t": bar["open_utc"]})
        n0 = len(self.events)
        new_sw = self.pb.update(i, bar, t_close)                       # 1. pullback first
        for s in new_sw:
            self.last_pb[s["side"]] = s
            self._ev("PULLBACK_" + s["side"], i, t_close, swing_id=s["swing_id"], price=s["price"], origin_bar=s["origin_bar"])
        h, lo, c = self.bars[-1]["h"], self.bars[-1]["l"], self.bars[-1]["c"]
        if self.slot["H"]["status"] == "UNSEEDED" and self.slot["L"]["status"] == "UNSEEDED":
            H, L = self.last_pb["H"], self.last_pb["L"]
            if H and L:
                if H["price"] > L["price"]:
                    for s in sorted((H, L), key=lambda x: (x["origin_bar"], x["seq"])):
                        self._publish(s["side"], s["price"], s["origin_bar"], i, t_close, "SEED", swing_id=s["swing_id"])
                    self._ev("SEEDED", i, t_close)
                else:
                    self._ev("SEED_REJECTED_CROSSED", i, t_close)
                    self.last_pb = {"H": None, "L": None}
            return self._result(n0)
        pre_active = {s: (dict(self.slot[s]) if self.slot[s]["status"] == "ACTIVE" else None) for s in ("H", "L")}
        # 2-3. pending trail, IDM ratchet (newly confirmed pullbacks) and IDM test - never on the breaking bar
        if self.pending and i > self.pending["break_bar"]:
            p = self.pending
            side = p["side"]
            if side == "H":
                if h > p["trail"]:
                    p["trail"], p["trail_bar"] = h, i
                for s in new_sw:
                    prot = self.slot["L"].get("level") if self.slot["L"]["status"] == "ACTIVE" else None
                    if s["side"] == "L" and (prot is None or s["price"] >= prot) and s["price"] <= p["trail"] and (p["idm"] is None or s["price"] > p["idm"]):
                        p["idm"], p["idm_kind"], p["idm_src"] = s["price"], "PULLBACK", s["swing_id"]
                taken = p["idm"] is not None and ((lo <= p["idm"]) if self.idm_mode == "WICK" else (c < p["idm"]))
            else:
                if lo < p["trail"]:
                    p["trail"], p["trail_bar"] = lo, i
                for s in new_sw:
                    prot = self.slot["H"].get("level") if self.slot["H"]["status"] == "ACTIVE" else None
                    if s["side"] == "H" and (prot is None or s["price"] <= prot) and s["price"] >= p["trail"] and (p["idm"] is None or s["price"] < p["idm"]):
                        p["idm"], p["idm_kind"], p["idm_src"] = s["price"], "PULLBACK", s["swing_id"]
                taken = p["idm"] is not None and ((h >= p["idm"]) if self.idm_mode == "WICK" else (c > p["idm"]))
            if taken:
                e = self._ev("IDM", i, t_close, side=side, ref=p["idm"], ref_kind=p["idm_kind"], ref_src=p.get("idm_src"), mode=self.idm_mode)
                price, origin = self._hl_range(p["break_bar"], i, side)
                self._publish(side, price, origin, i, t_close, "IDM_CONFIRMED", idm_event=e["event_id"])
                self.pending = None
        # 4. close breaks vs ACTIVE levels
        up = self.slot["H"]["status"] == "ACTIVE" and c > self.slot["H"]["level"]
        dn = self.slot["L"]["status"] == "ACTIVE" and c < self.slot["L"]["level"]
        if up and dn:
            self._ev("CORRUPT_STATE", i, t_close, reason="close beyond both active levels")
            return self._result(n0)
        if up or dn:
            d = "UP" if up else "DOWN"
            side, opp = ("H", "L") if up else ("L", "H")
            # 5. opposite break with an unresolved pending extreme -> publish its trail (fallback, not an IDM)
            if self.pending and self.pending["side"] == opp:
                p = self.pending
                self._publish(opp, p["trail"], p["trail_bar"], i, t_close, "OPPOSITE_BREAK_FALLBACK")
                self.pending = None
            # 6a. same-side candidate is rejected (ordinary break), opposite candidate from an EARLIER bar becomes x
            if self.sweep[side] is not None:
                self._ev("SWEEP_REJECTED", i, t_close, side=side, candidate=self.sweep[side])
                self.sweep[side] = None
            cand = self.sweep[opp] if self.sweeps_on else None
            if cand and cand["wick_bar"] < i and self.points.get(cand["point_id"], {}).get("version") == cand["version"]:
                old = self.points[cand["point_id"]]
                new = dict(old, version=old["version"] + 1, price=cand["wick"], origin_bar=cand["wick_bar"], published_bar=i, available_at=t_close,
                           reason="RELOCATED_BY_X")
                self.points[cand["point_id"]] = new
                self.versions.append(dict(new))
                x = self._ev("X_" + opp, i, t_close, level=old["price"], point_id=old["point_id"], wick_bar=cand["wick_bar"], wick=cand["wick"])
                self._ev("STRUCTURE_POINT_RELOCATED", i, t_close, point_id=old["point_id"], old_version=old["version"], new_version=new["version"],
                         cause_x=x["event_id"])
                if self.slot[opp].get("point_id") == old["point_id"]:
                    self.slot[opp] = dict(self.slot[opp], level=cand["wick"], version=new["version"])
            self.sweep = {"H": None, "L": None}
            # 6b. BoS / CHoCH
            broken = self.slot[side]
            kind = "BOS" if self.trend in ("NONE", d) else "CHOCH"
            old_trend = self.trend
            self.trend = d
            self._ev(f"{kind}_{d}", i, t_close, level=broken["level"], point_id=broken["point_id"], point_version=broken["version"],
                     old_trend=old_trend, new_trend=d)
            self.slot[side] = {"status": "PENDING", "consumed": broken}
            # alternation anchor: the chain must alternate - break UP starts an H publication, so the last point must be L
            if self.chain and self.points[self.chain[-1]]["side"] == side:
                last = self.points[self.chain[-1]]
                price, origin = self._hl_range(last["origin_bar"], i, opp)
                self._publish(opp, price, origin, i, t_close, "ALTERNATION_ANCHOR")
                self.slot[side] = {"status": "PENDING", "consumed": broken}
            # new pending extreme with its IDM reference
            prot = self.slot[opp] if self.slot[opp]["status"] == "ACTIVE" else None
            trail = h if side == "H" else lo
            ref = self.last_pb[opp]
            idm, kind_ref, src = None, None, None
            if ref and ref["available_at"] <= t_close and prot and ((side == "H" and prot["level"] <= ref["price"] <= trail) or
                                                                     (side == "L" and trail <= ref["price"] <= prot["level"])):
                idm, kind_ref, src = ref["price"], "PULLBACK", ref["swing_id"]
            elif prot:
                idm, kind_ref = prot["level"], "STRUCTURE_FALLBACK"
            if idm is None:
                self._ev("PENDING_BLOCKED", i, t_close, side=side, reason="NO_IDM_REFERENCE")
            self.pending = {"side": side, "break_bar": i, "trail": trail, "trail_bar": i, "idm": idm, "idm_kind": kind_ref, "idm_src": src}
            return self._result(n0)
        # 7. wick candidates against levels ACTIVE before this bar and still current
        if self.sweeps_on:
            for s in ("H", "L"):
                pa = pre_active[s]
                cur = self.slot[s]
                if not pa or cur.get("point_id") != pa["point_id"] or cur.get("status") != "ACTIVE":
                    continue
                if s == "H" and h > pa["level"] and c <= pa["level"]:
                    old = self.sweep["H"]
                    if old is None or h > old["wick"]:
                        self.sweep["H"] = {"point_id": pa["point_id"], "version": pa["version"], "level": pa["level"], "wick": h, "wick_bar": i}
                        self._ev("SWEEP_CANDIDATE_H", i, t_close, level=pa["level"], wick=h)
                if s == "L" and lo < pa["level"] and c >= pa["level"]:
                    old = self.sweep["L"]
                    if old is None or lo < old["wick"]:
                        self.sweep["L"] = {"point_id": pa["point_id"], "version": pa["version"], "level": pa["level"], "wick": lo, "wick_bar": i}
                        self._ev("SWEEP_CANDIDATE_L", i, t_close, level=pa["level"], wick=lo)
        return self._result(n0)

    def _result(self, n0) -> dict:
        evs = self.events[n0:]
        mask = 0
        for e in evs:
            if e["kind"] in EVENT_BITS:
                mask |= EVENT_BITS[e["kind"]]
            if e.get("reason") == "ALTERNATION_ANCHOR":
                mask |= EVENT_BITS["ANCHOR"]
            if e.get("reason") == "OPPOSITE_BREAK_FALLBACK":
                mask |= EVENT_BITS["FALLBACK"]
        return {"trend": self.trend, "slots": {k: {kk: vv for kk, vv in v.items() if kk != "consumed"} for k, v in self.slot.items()},
                "pending": dict(self.pending) if self.pending else None, "events": evs, "event_mask": mask}

    # ---------------------------------------------------------------- views
    def points_asof(self, cutoff: float | None = None) -> list[dict]:
        cur: dict = {}
        for v in self.versions:
            if cutoff is None or v["available_at"] <= cutoff:
                cur[v["point_id"]] = v
        return sorted(cur.values(), key=lambda v: (v["origin_bar"], v["published_bar"]))

    def state_hash(self) -> str:
        return hashlib.sha256(json.dumps({"events": self.events, "versions": self.versions, "trend": self.trend}, sort_keys=True, default=str)
                              .encode()).hexdigest()[:16]


def run(bars: list[dict], tf_s: int = 60, **kw) -> SMC:
    from datetime import datetime
    s = SMC(**kw)
    for b in bars:
        t = b["open_utc"] if isinstance(b["open_utc"], (int, float)) else datetime.fromisoformat(str(b["open_utc"]).replace("Z", "+00:00")).timestamp()
        s.update(b, t + tf_s)
    return s
