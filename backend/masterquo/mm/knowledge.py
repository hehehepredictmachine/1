"""PMW-MM master-models knowledge for the agent (loaded by agent.service.load_prompt; read by the tool get_master_models).
Adding rules to the prompt is not fine-tuning; every number the agent quotes must come from the tool output."""
from __future__ import annotations

KNOWLEDGE_VERSION = "PMW-MM-KNOWLEDGE-1.0.0"
RULES = {
    "MM-K01": "Master models działają w trybie SHADOW/OBSERVE: nie są bramką, nie głosują w SCALPING/HEDGING i nie zmieniają decyzji ani ryzyka; "
              "brak danych (status inny niż OK) to brak odczytu, nie neutralny sygnał.",
    "MM-K02": "Align Mean to jedna definicja średniej na wszystkich TF; odległość w pkt/%/ATR to kontekst, nie sygnał ani prawdopodobieństwo.",
    "MM-K03": "Kalman fast/slow i strefy wybicia liczą wyłącznie zamknięte świece; 'ostatnie zaakceptowane wybicie' to kierunek zdarzenia, nie pozycja; "
              "filtr SESSION_VWAP używa tick volume (proxy aktywności, nie wolumen transakcyjny).",
    "MM-K04": "GPR podaje średni log-zwrot 3×M5 z wariancją (latentną i obserwacyjną); pasma są założeniem gaussowskim, a kalibracja z ledgera przy "
              "n<200 jest niekonkluzywna – nie zamieniaj jej na procent szansy.",
    "MM-K05": "Tablica dowodów nie łączy wyników: zgodność modułów liczonych z tego samego feedu cen (SAME_PRICE_FEED) nie jest niezależnym potwierdzeniem.",
    "MM-K06": "Modele trenowane (HDC, event engine, STE-FlowNet) mają wpływ dopiero po artefakcie VALIDATED_SHADOW na REAL_USER_DATA; wynik na danych "
              "SYNTHETIC_TEST to test techniczny – NO_VALIDATED_EDGE.",
}


def prompt_section() -> str:
    return ("## Wiedza: master models PMW-MM – tryb SHADOW/OBSERVE (" + KNOWLEDGE_VERSION + ")\n"
            + "\n".join(f"- {k}: {v}" for k, v in RULES.items())
            + "\nWartości bierz wyłącznie z `get_master_models`; nie dopisuj procentów, których tam nie ma; nie wywołuj order_send.")
