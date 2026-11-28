"""PMW-LEDGER-VIEW-1 (1.46 arch, Etap 4 pkt 3): one READ-ONLY view of the bot's prediction / outcome ledgers (ledgers/view.py).

No migration, no writer change, never a write: every store is opened with sqlite URI mode=ro and a missing store is reported, not
created. See view.py for the store registry, the adapters and the canonical record.

Shared ledger helpers (1.46 arch I0036, ledgers/settle.py): pure functions used by several forecast ledgers - no service state, no I/O."""
