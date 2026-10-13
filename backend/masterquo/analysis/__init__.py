"""Shared market-structure core (1.10): volatility walls, support/resistance zones, chart and candle pattern engines,
M5 range with M1 local zones. Pure functions of bars (no MT5 / DB / Claude inside) - the same code runs live and in replay.
Every result is a versioned record with its availability time; a pattern / zone / wall is evidence, never an order."""
