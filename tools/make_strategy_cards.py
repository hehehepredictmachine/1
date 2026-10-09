"""Generates docs/PLAYBOOK_10_STRATEGII.md from the live registry (rules = module docstrings, parameters,
regime fit, data needs) plus the editorial fields below. Run after any strategy change:
    python tools/make_strategy_cards.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from masterquo.strategies import registry  # noqa: E402

MODULES = {"S01": "s01_trend_pullback", "S02": "s02_adaptive_trend", "S03": "s03_channel_breakout", "S04": "s04_volatility_compression_breakout",
           "S05": "s05_session_range_breakout", "S06": "s06_breakout_retest", "S07": "s07_failed_breakout_reclaim", "S08": "s08_range_edge_reversion",
           "S09": "s09_statistical_mean_reversion", "S10": "s10_exhaustion_structure_reversal"}

# hypothesis | inspiration (status) | own formalisation/adaptation | distinguishing condition | exit logic | near-miss | invalidation example
ED = {
    "S01": ("W istniejącym trendzie korekta do strefy wartości (EMA20–EMA50) częściej kończy się kontynuacją niż odwróceniem.",
            "Grimes – pullback w trendzie jako podstawowy setup kontynuacji; Kaufman – systemy podążania za trendem (METADATA_ONLY, reguła SOURCE_UNVERIFIED)",
            "Trend = EMA20>EMA50, nachylenie EMA50 i ER(20); korekta mierzona w ATR (1–3,5); strefa EMA50−0,25ATR..EMA20+0,25ATR; reakcja = zamknięcie nad high poprzedniej świecy.",
            "wymagana rozpoznana korekta (nie nowe maksimum)", "TP1 = ekstremum impulsu, TP2 = zasięg impulsu od wejścia; BE po TP1; wyjście czasowe 36 świec",
            "korekta < 1 ATR lub brak kontaktu ze strefą → EARLY/WATCH", "zamknięcie poniżej dołka korekty − 0,2 ATR"),
    "S02": ("Gdy efektywność ruchu (ER) rośnie, adaptacyjna średnia szybko podąża za ceną; zmiana stanu trendu daje wejście w nowy ruch.",
            "Kaufman – Adaptive Moving Average (KAMA) i efficiency ratio (METADATA_ONLY; formuła KAMA szeroko opublikowana, tekst książki niezweryfikowany)",
            "KAMA(10,2,30) na M15/H1; pasmo histerezy 0,3 ATR (własna adaptacja zamiast filtra z odchylenia KAMA); wejście tylko przy ZMIANIE stanu.",
            "zmiana stanu trendu (nie korekta jak S01)", "trailing: powrót pod KAMA − pasmo; TP1 1,5R, TP2 3R (brak celu strukturalnego w hipotezie)",
            "ER < 0,3 przy przecięciu → EARLY", "zamknięcie poniżej KAMA − pasmo (poziom z chwili wykrycia)"),
    "S03": ("Wybicie poza zakres N poprzednich świec sygnalizuje początek ruchu kierunkowego.",
            "Kaufman – breakout kanału (Donchian) jako klasyczny system (METADATA_ONLY, reguła SOURCE_UNVERIFIED)",
            "Kanał z 20 świec POPRZEDZAJĄCYCH (świeca wybicia nie ustala progu); bufor 0,1 ATR; limit wielkości świecy 2,5 ATR (bez gonienia).",
            "przebicie kanału z historii", "TP = połowa i cała szerokość kanału; BE po TP1", "świeca > 2,5 ATR → EARLY (BREAKOUT_BAR_TOO_LARGE)",
            "zamknięcie poniżej środka kanału"),
    "S04": ("Po okresie niskiej zmienności częściej następuje jej ekspansja; kierunek wyznacza wyjście z pudełka kompresji.",
            "Kaufman/Chan – zmienność i reżimy (METADATA_ONLY, SOURCE_UNVERIFIED); własna formalizacja percentylowa",
            "Kompresja = percentyl szerokości Bollingera ≤ 15% z 120 świec przez ≥ 5 świec, pudełko znane przed świecą sygnału; odległość wejścia ≤ 1 ATR.",
            "historyczna kompresja (nie sam kontakt z kanałem)", "TP = 1× i 2× wysokość pudełka", "zamknięcie za daleko od pudełka → EARLY (TOO_FAR_FROM_BOX)",
            "zamknięcie z powrotem poniżej środka pudełka"),
    "S05": ("Zakres początkowego okna sesji wyznacza poziomy, których wybicie w oknie handlu ma kierunkową kontynuację.",
            "Koncepcja opening range breakout – literatura ogólna (SOURCE_UNVERIFIED); godziny sesji = konfiguracja do zbadania na feedzie brokera",
            "Londyn 08:00 Europe/London (60 min), Nowy Jork 08:30 America/New_York (30 min); DST przez zoneinfo; zakres zamrożony po zamknięciu ostatniej świecy okna.",
            "zamrożony zakres sesji", "TP = 1× i 2× zakres; wygaśnięcie z końcem okna handlu", "wybicie bez zamknięcia ponad bufor → EARLY",
            "zamknięcie poniżej środka zakresu"),
    "S06": ("Przebity poziom, który po powrocie utrzymuje się (retest), potwierdza zmianę roli poziomu.",
            "Grimes – wybicie i test poziomu (METADATA_ONLY, SOURCE_UNVERIFIED)",
            "Poziom = potwierdzony pivot 3/3; sekwencja wybicie → retest (low ≤ poziom + 0,3 ATR) → reakcja (zamknięcie nad high świecy retestu ≤ 3 świece).",
            "obowiązkowa sekwencja wybicie→retest→reakcja", "TP1 = maksimum po wybiciu, TP2 = 2R", "brak retestu → WATCH; retest bez reakcji → EARLY",
            "zamknięcie poniżej poziomu − 0,5 ATR"),
    "S07": ("Nieudane wyjście poza zakres i szybki powrót do środka często kończy się ruchem w przeciwną stronę.",
            "Grimes – failure test / nieudane wybicie (METADATA_ONLY, SOURCE_UNVERIFIED). Bez danych zleceń nie twierdzimy, kto „zebrał płynność”",
            "Poziom = dolna krawędź 20 poprzednich świec; wyjście > 0,1 ATR poza; powrót zamknięciem nad poziom + 0,1 ATR w ≤ 3 świecach.",
            "zaobserwowane wyjście i powrót", "TP = środek i przeciwna krawędź zakresu", "powrót bez bufora → EARLY", "zamknięcie poniżej ekstremum wyjścia"),
    "S08": ("W rozpoznanej konsolidacji odrzucenie krawędzi prowadzi do ruchu w stronę środka zakresu.",
            "Grimes – zakresy i ich krawędzie; Kaufman – systemy przeciwtrendowe (METADATA_ONLY, SOURCE_UNVERIFIED)",
            "Zakres z 40 świec PRZED sygnałem: ER ≤ 0,25, wysokość 2–8 ATR, ≥ 2 dotknięcia każdej krawędzi; świeca odrzucenia zamyka się w górnej połowie.",
            "zakres znany przed sygnałem, bez wymogu wyjścia poza (różnica vs S07)", "TP = środek i przeciwna krawędź (−15%)", "dotknięcie bez odrzucenia → EARLY",
            "zamknięcie poniżej dołu zakresu − 0,3 ATR"),
    "S09": ("Duże odchylenie z-score ceny od średniej kroczącej częściowo wraca – hipoteza do testu, nie założenie stacjonarności złota.",
            "Chan – mean reversion na odchyleniu od średniej / Bollinger (METADATA_ONLY, SOURCE_UNVERIFIED)",
            "z = (close − SMA40)/std40; WATCH ≤ −1,5, EARLY ≤ −2; trigger = zawrócenie z i świeca wzrostowa; filtr ER(20) < 0,35 (brak silnego trendu).",
            "mierzalne odchylenie statystyczne (bez ręcznych granic jak S08)", "TP1 = SMA − 1σ, TP2 = SMA; wyjście czasowe 20 świec", "z nie zawraca → EARLY",
            "odchylenie rośnie do −3,5σ (poziom zamrożony)"),
    "S10": ("Słabnący impuls (dywergencja lub nadmierne rozciągnięcie) z potwierdzoną zmianą struktury poprzedza odwrócenie.",
            "Grimes – zmiana struktury rynku; momentum/dywergencja (METADATA_ONLY, SOURCE_UNVERIFIED). Sam RSI nie jest triggerem",
            "Impuls ≥ 3 ATR do ekstremum ≤ 12 świec temu; wyczerpanie = dywergencja RSI (+2) lub rozciągnięcie ≥ 2,5 ATR od EMA20; trigger = zamknięcie nad ostatni niższy szczyt.",
            "potwierdzona zmiana struktury (bez wymogu S07)", "TP = 50% i 78,6% zniesienia impulsu", "zbliżenie do poziomu CHoCH → EARLY", "zamknięcie poniżej ekstremum"),
}


def main() -> int:
    L = ["# Playbook – 10 strategii ACTIVE (S01–S10)", "",
         "Wygenerowane z kodu (`python tools/make_strategy_cards.py`). Wszystkie strategie: **status walidacji FUNCTIONAL_ONLY_OOS_NOT_RUN** – kompletne,",
         "uruchamialne i przetestowane funkcjonalnie (testy syntetyczne), **bez** potwierdzonej skuteczności na XAUUSD-. Parametry są robocze (nie zoptymalizowane).",
         "", "Wspólne dla wszystkich (kontrakt MQ-STRATEGY-CONTRACT-1.0.0):",
         "* reguła LONG zapisana raz; SHORT = ta sama reguła na cenach odbitych lustrzanie (p' = 2C − p) – identyczna logika obu kierunków,",
         "* etapy: WATCH (struktura rozpoznana) → EARLY (formacja rozwija się / trigger na świecy tworzącej się) → CONFIRMED (prawdziwy trigger na ZAMKNIĘTEJ świecy + wynik ≥ progu),",
         "* punktacja ACTIVE 0–100: struktura 25, formacja 25, momentum 20 (RSI/MACD/EMA jako JEDNA kategoria – mediana głosów), trigger 15, kontekst HTF 10, dodatkowe 5 (DXY – obecnie niedostępne → 0 pkt, bez skracania mianownika),",
         "* zlecenie: rynkowe po zamknięciu świecy wyzwalającej, wyłącznie przez wspólny gateway i moduł ryzyka (sizing, RR netto, koszty); SL dla SHORT + spread (stop na Ask),",
         "* deduplikacja: setup_id = hash(symbol, rachunek, strategia, kierunek, TF, klucz struktury) – odświeżenia aktualizują wersję; event_id grupuje strategie opisujące ten sam ruch,",
         "* ważność: liczba świec TF setupu (`expires_bars`), po CONFIRMED okno wejścia 3 świece → MISSED_ENTRY; unieważnienie natychmiastowe,",
         "* restart: stan w SQLite (`strategy_setups`), ale po starcie aktywne setupy są oznaczane RESTART_REVALIDATION i wracają tylko po ponownym wykryciu na świeżych danych,",
         "* cooldown: detekcji – brak (struktura publikowana raz, unieważniona nie wraca); powiadomień – tylko EARLY/CONFIRMED/unieważnienie; zleceń – UNIQUE entry_key (1 wejście na setup).",
         ""]
    for sid, s in registry.STRATEGIES.items():
        mod = importlib.import_module("masterquo.strategies." + MODULES[sid])
        h, src, form, dist, exit_, near, inval = ED[sid]
        fit = ", ".join(f"{k} {v}" for k, v in sorted(s.regime_fit.items(), key=lambda x: -x[1]))
        L += [f"## {sid} — {s.name} (v{s.version})", "",
              f"**Hipoteza:** {h}", "", f"**Źródło inspiracji (dostęp):** {src}", "", f"**Własna formalizacja i adaptacja do XAUUSD- CFD:** {form}", "",
              f"**Warunek wyróżniający:** {dist}", "",
              f"**Reżim i horyzont:** dopasowanie do reżimu: {fit}. TF setupu: {', '.join(s.setup_tfs)}; kontekst: {s.context_tf}; wymagane dane: {', '.join(s.required_tfs)}; "
              f"min. historia: {s.min_bars} zamkniętych świec (warm-up).", "",
              "**Reguły (z kodu):**", "```", (mod.__doc__ or "").strip(), "```", "",
              f"**Parametry robocze (do badań, nie zoptymalizowane):** `{json.dumps(s.params, ensure_ascii=False)}`", "",
              f"**Wyjście i zarządzanie:** {exit_}.", "", f"**Near-miss:** {near}.  **Unieważnienie:** {inval}.", "",
              "**Przykłady:** syntetyczne scenariusze LONG/SHORT/near-miss/unieważnienia w `tests/_strategy_fixtures.py` (oznaczone SYNTHETIC) – testy `tests/test_strategies.py`.", ""]
    out = ROOT / "docs" / "PLAYBOOK_10_STRATEGII.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("written", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
