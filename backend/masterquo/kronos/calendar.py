"""Empirical trading calendar -> future candle timestamps for Kronos (y_timestamp).

MetaTrader 5 does not expose the symbol's trading sessions through the Python API, so the schedule is MEASURED from the broker's own
closed bars, in SERVER time (the broker defines sessions, the daily break and the weekend in server time; DST shifts of the server are
therefore already inside the data):
  slot = (weekday, time-of-day // slot_seconds); for every weekday the dates with at least one bar are counted;
  occupancy(slot) = dates on which the slot had a bar / dates of that weekday with trading whose slot time had already passed when
  the history ends (the current, unfinished day counts only for its earlier slots);
  OPEN if occupancy >= OPEN_MIN, CLOSED if <= CLOSED_MAX or the weekday never traded, otherwise AMBIGUOUS.
Future times are generated bar by bar after the last closed bar, skipping CLOSED slots (daily break, weekend). An AMBIGUOUS slot inside
the horizon, a history shorter than MIN_DAYS or no open slot within MAX_SKIP_DAYS -> no timestamps, with the reason: the forecast is
suspended for that data instead of pretending the closed market is a continuous stream of candles.
"""
from __future__ import annotations

from collections import defaultdict

OPEN_MIN = 0.6
CLOSED_MAX = 0.2
MIN_DAYS = 7.0
MAX_SKIP_DAYS = 6
DAY = 86400


class Calendar:
    def __init__(self, t_raw: list[int], slot_sec: int):
        self.slot = int(slot_sec)
        ts = sorted({int(t) for t in t_raw})
        self.first, self.last = (ts[0], ts[-1]) if ts else (None, None)
        self.coverage_days = ((ts[-1] - ts[0]) / DAY) if len(ts) > 1 else 0.0
        dates_wd: dict[int, set] = defaultdict(set)
        slot_dates: dict[tuple, set] = defaultdict(set)
        for t in ts:
            day = t // DAY
            wd = (day + 3) % 7                                       # 1970-01-01 was a Thursday -> Monday = 0
            dates_wd[wd].add(day)
            slot_dates[(wd, (t % DAY) // self.slot)].add(day)
        self.dates_wd = {wd: sorted(v) for wd, v in dates_wd.items()}
        self.n_dates = {wd: len(v) for wd, v in dates_wd.items()}
        self.counts = {k: len(v) for k, v in slot_dates.items()}

    def usable(self) -> tuple[bool, str | None]:
        if self.first is None:
            return False, "brak świec do ustalenia kalendarza sesji"
        if self.coverage_days < MIN_DAYS:
            return False, f"historia {self.coverage_days:.1f} dnia < {MIN_DAYS:.0f} dni – nie da się ustalić tygodniowego kalendarza sesji"
        return True, None

    def state(self, t_raw: int) -> tuple[str, float | None]:
        day = int(t_raw) // DAY
        wd = (day + 3) % 7
        slot = (int(t_raw) % DAY) // self.slot
        # only dates on which this slot had already happened when the history ends count (the current, unfinished day does not
        # count for its later slots - otherwise every future slot of today would look "half open")
        nd = sum(1 for d in self.dates_wd.get(wd, ()) if d * DAY + slot * self.slot <= (self.last or 0))
        if nd == 0:
            return "CLOSED", 0.0                                     # this weekday never traded in the measured history
        occ = self.counts.get((wd, slot), 0) / nd
        if occ >= OPEN_MIN:
            return "OPEN", occ
        if occ <= CLOSED_MAX:
            return "CLOSED", occ
        return "AMBIGUOUS", occ

    def future(self, last_open_raw: int, tf_sec: int, n: int) -> tuple[list[int] | None, dict]:
        """Server-time opens of the next n bars after the last closed bar, or (None, info with the reason)."""
        ok, why = self.usable()
        if not ok:
            return None, {"status": "CALENDAR_INSUFFICIENT", "reason": why}
        out, skipped = [], 0
        t = int(last_open_raw) + tf_sec
        limit = int(last_open_raw) + MAX_SKIP_DAYS * DAY + n * tf_sec
        while len(out) < n:
            if t > limit:
                return None, {"status": "CALENDAR_NO_SESSION", "reason": f"brak otwartego slotu sesji w ciągu {MAX_SKIP_DAYS} dni po ostatniej świecy"}
            st, occ = self.state(t)
            if st == "OPEN":
                out.append(t)
            elif st == "AMBIGUOUS":
                return None, {"status": "CALENDAR_UNCERTAIN", "reason": f"niepewny slot sesji {_fmt(t)} (czas serwera; obecność świec w "
                                                                         f"{occ:.0%} dni) – przyszłe czasy świec nie są wiarygodne",
                              "slot_server": _fmt(t)}
            else:
                skipped += 1
            t += tf_sec
        return out, {"status": "OK", "skipped_closed_slots": skipped, "crosses_break": skipped > 0,
                     "coverage_days": round(self.coverage_days, 1)}

    def expected_missing(self, t_raws: list[int], tf_sec: int) -> dict:
        """Gaps inside the context: consecutive bars further apart than one bar, counted only on OPEN slots (a weekend or the daily
        break is not a gap)."""
        missing, ambiguous = 0, 0
        for a, b in zip(t_raws, t_raws[1:]):
            t = a + tf_sec
            steps = 0
            while t < b and steps < 5000:
                st, _ = self.state(t)
                if st == "OPEN":
                    missing += 1
                elif st == "AMBIGUOUS":
                    ambiguous += 1
                t += tf_sec
                steps += 1
        return {"missing_open_slots": missing, "ambiguous_slots": ambiguous}


def _fmt(t: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(t), tz=timezone.utc).strftime("%a %Y-%m-%d %H:%M")


def slot_seconds(tf_sec: int) -> int:
    """Calendar resolution: the timeframe itself, but never finer than 5 minutes (M1 bars are missing in quiet minutes without ticks -
    a 5-minute slot is a robust session measure; M1 times inside an open slot are all treated as tradable)."""
    return max(int(tf_sec), 300)
