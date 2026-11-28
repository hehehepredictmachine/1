"""Strategy identifiers (1.46 arch, I0083) - a leaf module WITHOUT imports.

config.py (a base module) needs only the ids and the scan-only defaults; before it imported the whole strategy registry (12 strategy
modules, S12 -> analysis.*) lazily from _default_toggles and the manual_strategy_id validator. The registry imports these names (one
definition - no copy) and a test checks tuple(registry.STRATEGIES) == STRATEGY_IDS in the same order.
"""

STRATEGY_IDS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S11", "S12")
# strategies that may be scanned/shown but are not allowed to trade until the user enables them (unvalidated challengers)
DEFAULT_NO_TRADE = {"S11", "S12"}
