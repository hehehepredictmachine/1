"""S05 SESSION_RANGE_BREAKOUT - breakout of an initial session range (opening range).

Sessions are configuration studied on the broker feed (an OTC gold CFD has no single exchange
open). Each session: local start time in an IANA time zone (DST handled by zoneinfo), range
length and trading window. Bars are M5 in UTC.
  range      high/low of the M5 bars inside [start, start + range_minutes); frozen only after the
             last bar of the window has CLOSED and >= 80% of the expected bars exist
  LONG (SHORT mirrored), only inside [range end, range end + trade_minutes)
  WATCH      range frozen, price inside it
  EARLY      forming bar above the range, or close above it by less than the buffer
  TRIGGER    CLOSED M5 bar closes above range high + buffer_atr x ATR(M5)
  invalid.   close back below the range midpoint; the setup expires at the end of the window
  SL         range midpoint (range >= 1 ATR) or range low (narrow range) - 0.1 ATR (+spread SHORT)
  targets    TP1 = high + 1 x range, TP2 = high + 2 x range
  dedupe     one setup per session, date and side
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .base import Draft, MarketView, Strategy, long_stop
from .common import level_bucket, plan, valid_targets

UTC = timezone.utc


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class SessionRangeBreakout(Strategy):
    id = "S05"
    name = "SESSION_RANGE_BREAKOUT"
    version = "1.0.0-EXPERIMENTAL"
    family = "BREAKOUT"
    setup_tfs = ("M5",)
    context_tf = "H1"
    required_tfs = ("M5",)
    min_bars = 40
    regime_fit = {"EXPANSION": 1.0, "COMPRESSION": 0.7, "TRANSITION": 0.6, "TREND_UP": 0.5, "TREND_DOWN": 0.5, "RANGE": 0.4,
                  "EXHAUSTION_OR_REVERSAL_CANDIDATE": 0.1}
    params = {"sessions": [{"name": "LONDON", "tz": "Europe/London", "start": "08:00", "range_minutes": 60, "trade_minutes": 180},
                           {"name": "NEW_YORK", "tz": "America/New_York", "start": "08:30", "range_minutes": 30, "trade_minutes": 150}],
              "buffer_atr": 0.1, "min_coverage": 0.8, "time_exit_bars": 36}

    @staticmethod
    def session_window(sess: dict, ref_utc: datetime) -> tuple[datetime, datetime, datetime]:
        tz = ZoneInfo(sess["tz"])
        local_day = ref_utc.astimezone(tz).date()
        hh, mm = (int(x) for x in sess["start"].split(":"))
        start = datetime(local_day.year, local_day.month, local_day.day, hh, mm, tzinfo=tz).astimezone(UTC)
        rng_end = start + timedelta(minutes=sess["range_minutes"])
        return start, rng_end, rng_end + timedelta(minutes=sess["trade_minutes"])

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:
        v = view.tfs.get("M5")
        if v is None or len(v) < self.min_bars:
            return []
        i = v.last
        a = v.atr()[i]
        if not a:
            return []
        last_open = _p(v.t[i])
        last_close = last_open + timedelta(minutes=5)
        out = []
        for sess in p["sessions"]:
            start, rng_end, trade_end = self.session_window(sess, last_open)
            if not (rng_end <= last_close <= trade_end):
                continue
            idx = [k for k in range(max(0, i - 200), i + 1) if start <= _p(v.t[k]) < rng_end]
            expected = sess["range_minutes"] // 5
            if not idx or len(idx) < p["min_coverage"] * expected or _p(v.t[idx[-1]]) + timedelta(minutes=5) > last_close:
                continue
            hi, lo = max(v.h[k] for k in idx), min(v.l[k] for k in idx)
            height = hi - lo
            if height <= 0:
                continue
            mid = (hi + lo) / 2
            buf = p["buffer_atr"] * a
            after = range(idx[-1] + 1, i)
            if any(v.c[k] > hi + buf for k in after):
                continue                                     # this side already triggered in this session
            phase, missing = None, []
            if v.c[i] > hi + buf and i > idx[-1]:
                phase = "TRIGGER"
            elif (v.forming and v.forming["h"] > hi) or v.c[i] > hi:
                phase, missing = "EARLY", ["CLOSE_BEYOND_RANGE_PLUS_BUFFER"]
            elif lo <= v.c[i] <= hi and v.c[i] >= mid:
                phase, missing = "WATCH", ["RANGE_NOT_BROKEN"]
            if phase is None:
                continue
            remaining = int((trade_end - last_close).total_seconds() // 300)
            entry = v.c[i] if phase == "TRIGGER" else hi + buf
            sl = long_stop(view, mid if height >= a else lo, 0.1 * a)
            tg = valid_targets("LONG", entry, sl, [(hi + height, 0.5, "RANGE_1X"), (hi + 2 * height, 0.5, "RANGE_2X")])
            day = start.date().isoformat()
            out.append(Draft(
                strategy_id=self.id, direction="LONG", timeframe="M5", phase=phase,
                structure_key=f"{sess['name']}:{day}", event_key=f"BREAKOUT:LONG:{level_bucket(view, hi)}", anchor_time=start.isoformat().replace("+00:00", "Z"),
                entry_plan=plan("SESSION_RANGE_BREAK", entry, (hi, hi + buf), f"zamknięcie M5 powyżej zakresu sesji {sess['name']} + bufor", hi + buf, 2, 1.0),
                invalidation_level=mid, stop_loss=sl, targets=tg,
                exit_rules={"time_exit_bars": p["time_exit_bars"], "be_after_tp1": True, "session_end_utc": trade_end.isoformat().replace("+00:00", "Z")},
                expires_bars=max(1, remaining),
                components={"structure": 1.0 if len(idx) >= expected else 0.7, "formation": 1.0 if 0.8 * a <= height <= 4 * a else 0.5,
                            "trigger": 1.0 if phase == "TRIGGER" else 0.0},
                momentum_mode="CONTINUATION", missing=missing, reason_codes=[f"SESSION_{sess['name']}", f"RANGE_{height / a:.1f}ATR"],
                facts={"range_high_px": round(hi, 3), "range_low_px": round(lo, 3), "session": sess["name"], "range_start_utc": start.isoformat(),
                       "window_end_utc": trade_end.isoformat(), "bars_in_range": len(idx)},
                horizon="SCALP"))
        return out
