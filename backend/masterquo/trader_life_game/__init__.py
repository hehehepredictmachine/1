"""TraderLifeGame (Apollo23 TASK 019): educational RPG subsystem - local-first, execution-isolated. Not a market profile."""
from .service import GameError, GameService, ReadOnlyAccountView  # noqa: F401

NAVIGATION_ID = "TRADER_LIFEGAME"      # a navigation destination / subsystem id - NEVER a MarketProfileId
