"""PMW-UPD-11 flow-context knowledge for the agent (loaded by agent.service.load_prompt) + deterministic explanation of one cell's
flow section (no LLM, no new numbers). Adding rules to the prompt is not fine-tuning."""
from __future__ import annotations

KNOWLEDGE_VERSION = "PMW-FLOW-KNOWLEDGE-1.0.0"
RULES = {
    "F01": "Heikin Flow to syntetyczne, wygładzone i opóźnione świece; nie są cenami wykonania ani celem treningu.",
    "F02": "Formująca świeca to podgląd; PARTIAL_STARTUP nie jest stabilnym wejściem modelu.",
    "F03": "Score kanału S/R (20×pivoty + dotknięcia) to geometria pasma, nie prawdopodobieństwo odbicia.",
    "F04": "Bieżąca mapa kanałów w tle nie dowodzi, że pasmo było znane w dawnym setupie – historia jest osobnym trybem as-of.",
    "F05": "Punkty ≠ pips ≠ tick ≠ cena SL; SL jest ceną po zaokrągleniu do tick size, a factor StopDistance nie jest p(bezpieczny stop).",
    "F06": "STATE_AT_H Markowa to rozkład stanu jednej zmiany w kroku h, nie skumulowany zwrot ani p(TP przed SL).",
    "F07": "Rozkład stacjonarny nie musi być równomierny; łańcuch okresowy lub redukowalny nie zbiega do jednej granicy.",
    "F08": "Przedziały Monte Carlo koszyków opisują punkt końcowy, nie przyszłe high/low; niski support wiersza ogranicza prognozę.",
    "F09": "Przewaga wymaga oceny poza próbą z kosztami; brak spełnionych kryteriów to NO_VALIDATED_EDGE.",
}


def prompt_section() -> str:
    return ("## Wiedza: flow context – Heikin Flow, kanały S/R, StopDistance, Markov (" + KNOWLEDGE_VERSION + ")\n"
            + "\n".join(f"- {k}: {v}" for k, v in RULES.items())
            + "\nPodawaj wartości wyłącznie z sekcji `flow` snapshotu; nie dopisuj procentów, których tam nie ma; nie wywołuj order_send.")


def explain_cell(tf: str, flow: dict | None) -> tuple[list[str], set]:
    if not flow or flow.get("status") != "OK":
        return [], set()
    facts, rules = [], {"F01", "F09"}
    h = flow.get("heikin") or {}
    facts.append(f"{tf}: Heikin Flow {h.get('color')} (jakość {h.get('quality')}, syntetyczne)")
    if h.get("quality") == "PARTIAL_STARTUP":
        rules.add("F02")
    sd = flow.get("stopdistance") or {}
    if sd.get("average_points") is not None:
        facts.append(f"{tf}: StopDistance średnia {sd['average_points']:.1f} pkt, sugerowany {sd['suggested_points']:.1f} pkt (= {sd['suggested_price_distance']:.3f} ceny)")
        rules.add("F05")
    nn = (flow.get("sr") or {}).get("nearest") or {}
    if nn.get("support") or nn.get("resistance"):
        facts.append(f"{tf}: najbliższe pasma S/R – wsparcie {nn.get('support')}, opór {nn.get('resistance')}")
        rules.update({"F03", "F04"})
    m3 = flow.get("markov3") or {}
    if m3.get("next"):
        facts.append(f"{tf}: Markov3 stan {m3.get('state')}, rozkład następnego stanu {m3['next']}")
        rules.update({"F06", "F07"})
    if isinstance(flow.get("buckets"), dict) and flow["buckets"].get("K_effective"):
        rules.add("F08")
    return facts, rules
