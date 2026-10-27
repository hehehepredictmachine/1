"""SCALPING / HEDGING strategies (PMW-SH-1): shared units, plans, risk, ownership, state machines, context and replay.
Nothing in this package sends an order by itself: execution goes through masterquo.sh.executor, which honours the
execution mode (SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE)."""
