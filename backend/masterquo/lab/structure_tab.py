"""Tabular feature order of STRUCTURE_MOVE_M1_V1 (leaf module). 1.46 arch I0085: shared by structure_task and si_families without the
structure_task <-> si_families import cycle (si_families imported TAB lazily from structure_task, which imports si_families).
structure_task re-exports TAB under its old name - the order and the names are unchanged (artefacts depend on them)."""
from __future__ import annotations

TAB = ["ret1", "ret3", "ret5", "ret15", "body", "upper", "lower", "clv", "range_atr", "trend_int", "trend_maj", "trend_unknown", "dist_h", "dist_l",
       "ev_bos_up", "ev_bos_dn", "ev_chg_up", "ev_chg_dn", "ev_sweep_h", "ev_sweep_l", "bars_since_event", "mitp_buy", "mitp_sell", "mitp_vote",
       "mitp_held", "bb_pctb", "atr_ratio", "hour_sin", "hour_cos", "spread_atr", "spread_known", "m5_ret3", "m5_pos", "m15_ret3", "m15_pos",
       "h1_ret3", "h1_pos", "ctx_known", "black_known"]
