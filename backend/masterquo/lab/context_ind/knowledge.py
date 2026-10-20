"""PMW-UPD-14 section 11.3 knowledge for the agent (loaded by agent.service.load_prompt) + deterministic explanation of one cell's
`context` section (no LLM, no new numbers). Adding rules to the prompt is not fine-tuning."""
from __future__ import annotations

KNOWLEDGE_VERSION = "PMW-CTX-KNOWLEDGE-1.0.0"
RULES = {
    "C01": "VAMD: wysoka alpha = krótsza pamięć względem nowego targetu momentum; znak y to kierunek momentum, nie p(win). Brak targetu nie oznacza „decay do 0”.",
    "C02": "FD (bounded Katz): TREND nie ma strony; clipping, saturacja (CONSERVATIVE_CHOP_SATURATION) i NO_MOTION są jawne. Ekspansja ATR i trend FD mierzą różne cechy.",
    "C03": "SMC: pending wick to tylko kandydat; x istnieje dopiero po potwierdzeniu przełamaniem. IDM i relokacja mają własny czas publikacji; bieżąca geometria nie dowodzi, że punkt był znany w chwili origin.",
    "C04": "Nowa warstwa SMC to nie czwarta niezależna zgoda, jeśli to to samo przełamanie co legacy M03 – wskaźniki mogą być skorelowane i nie liczy się ich naiwnie jako niezależnych potwierdzeń.",
    "C05": "Inspector: indeks bufora jest techniczny; INTEGER_STATE_LIKE nie dowodzi koloru ani BUY. Nieznany shift/empty/potwierdzenie blokuje użycie jako cechy; czytelny bufor nie dowodzi przewagi ani braku repaintu.",
    "C06": "would_block to filtr diagnostyczny (SHADOW); brak blokady nie jest triggerem. FD TREND + VAMD>0 samo nie wystarcza do BUY – wejście wymaga istniejącego triggera i ryzyka.",
    "C07": "Score checklisty nie jest procentem zysku; ogólne p z innego zadania/strony/horyzontu nie pasuje do tego setupu. Brak walidacji poza próbą z kosztami = NO_VALIDATED_EDGE.",
}


def prompt_section() -> str:
    return ("## Wiedza: kontekst VAMD / FD / Pullback+SMC / Buffer Inspector (" + KNOWLEDGE_VERSION + ")\n"
            + "\n".join(f"- {k}: {v}" for k, v in RULES.items())
            + "\nPodawaj wartości wyłącznie z sekcji `context` snapshotu (z jej profile_hash/epoch); przy braku danych podaj powód, "
              "nie uzupełniaj liczb ani kierunku na podstawie nazwy wskaźnika; nie wywołuj order_send.")


def explain_cell(tf: str, ctx: dict | None) -> tuple[list[str], set]:
    if not ctx or ctx.get("status") != "OK":
        return [], set()
    facts, rules = [], {"C04", "C06"}
    v = ctx.get("vamd") or {}
    if v.get("y") is not None:
        facts.append(f"{tf}: VAMD y {v['y']:+.3f} (alpha {v.get('alpha'):.3f}) – momentum, nie p(win)")
        rules.add("C01")
    else:
        facts.append(f"{tf}: VAMD brak wartości ({v.get('status')})")
    f = ctx.get("fd") or {}
    if f.get("zone"):
        extra = " [saturacja]" if f.get("saturated") else (" [clipped]" if f.get("clipped") else "")
        facts.append(f"{tf}: FD strefa {f['zone']}" + (f" ({f['fd_smooth']:.3f})" if f.get("fd_smooth") is not None else "") + extra + " – bez strony")
        rules.add("C02")
    s = ctx.get("smc") or {}
    ev = [e.get("kind") for e in (s.get("last_events") or [])]
    facts.append(f"{tf}: SMC trend {s.get('trend')}, aktywne H {s.get('active_high')}, L {s.get('active_low')}"
                 + (f", ostatnie zdarzenia {', '.join(ev)}" if ev else "") + (" (pending – kandydat)" if s.get("pending") else ""))
    rules.add("C03")
    wb = ctx.get("would_block") or {}
    blocked = [k for k, x in wb.items() if x.get("status") == "WOULD_BLOCK"]
    if blocked:
        facts.append(f"{tf}: filtr kontekstu WOULD_BLOCK dla {', '.join(blocked)} (SHADOW, nie trigger)")
    return facts, rules
