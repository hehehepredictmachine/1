"""Builds the PDF guide "installation of the bot, the models and their training" (1.39):

  release/Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf

  python tools/make_install_guide.py [--shots data/logs] [--out release]

Same layout and fonts as tools/make_manuals.py (header band, chapters, note / warning boxes, footer with the version). Every command and
file name in the text exists in the package (launchers *.bat, `python -m masterquo ...`, config keys) - the guide is checked by
tests/test_install_guide.py. Screenshots (optional) come from the UI tests on the terminal SIMULATOR. Requires reportlab.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Spacer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_manuals as M  # noqa: E402  (shared layout: fonts, styles, boxes, tables, page decoration)

ROOT = M.ROOT
NAME = "Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf"
P, bullets, steps, box, table, shot = M.P, M.bullets, M.steps, M.box, M.table, M.shot


def cmd(text: str):
    """A command line in a light box (monospace is not embedded - DejaVu keeps the Polish characters)."""
    return box("<b>›</b> " + text, "note")


def story(shots: Path | None) -> list:
    V, TAG = M.VERSION, M.VERSION.replace(".", "_")
    s: list = [Spacer(1, 18 * mm), P("Instalacja bota,<br/>modeli i trening", "title"),
               P(f"PepeMarketWizard {V}: instalacja na Windows, pierwsze uruchomienie, tryb LIVE od startu, instalacja modeli prognoz "
                 "(Kronos-base, Chronos-2, Granite TTM), Memory Governor (16 GB), rodziny modeli (ARIMA, GARCH, LSTM, PPO …), trening, aktywacja, GARCH w strategii "
                 "PMW_HG09, walidacja 20 wariantów, aktualizacja i powrót do poprzedniej wersji.", "lead"),
               box(f"<b>Stan:</b> instrukcja odpowiada wersji <b>{V}</b>. Polecenia i nazwy plików pochodzą z paczki i są sprawdzane testem "
                   "(tests/test_install_guide.py). Nie przeprowadzono tutaj testu na Twoim Windows ani z prawdziwym MT5 – zrzuty ekranu "
                   "pochodzą z symulatora (dane syntetyczne)."),
               box("<b>Ważne – tryb LIVE od startu (1.39).</b> Na Twoją prośbę bot startuje w trybie <b>AUTO LIVE</b> i przy pierwszej "
                   "decyzji wiąże się z zalogowanym rachunkiem <b>REAL</b>. To są prawdziwe pieniądze. Przed uruchomieniem przeczytaj "
                   "rozdział 3 (co zostało zdjęte, co nadal chroni rachunek, jak wyłączyć LIVE).", "block"),
               P("Spis treści", "h2"),
               steps(["Wymagania", "Instalacja bota", "Tryb LIVE od startu – co się zmieniło", "Modele – przegląd",
                      "Instalacja modeli prognoz (Kronos-base, Chronos-2, Granite TTM)", "Rodziny modeli – instalacja i trening",
                      "GARCH (VOL_GARCH) i strategia PMW_HG09", "Centrum treningu i eksport danych z MT5",
                      "Walidacja (replay 20 wariantów, prognozy, scalp)", "Nowe menu, intro i WTC PEPE 2.1",
                      "Aktualizacja z 1.38 i powrót", "Problemy i logi"]),
               PageBreak()]
    # 1
    s += [P("1 / Wymagania", "h1"),
          table([["Element", "Wymaganie", "Uwagi"],
                 ["System", "Windows 10 / 11 x64", "Aplikacja Windows ma własny Python (runtime\\python) i WebView2."],
                 ["MetaTrader 5", "zainstalowany, zalogowany, symbol w Market Watch", "np. XAUUSD- u brokera; „Algo Trading” włączone dla LIVE."],
                 ["Python (wariant bez aplikacji)", "3.13 x64 (lub 3.12) z python.org", "01_INSTALUJ.bat sam wybiera interpreter; nie zmienia globalnego Pythona."],
                 ["RAM", "16 GB (zalecane)", "Profil LOW_MEMORY_16GB: Granite ≈ 0,35 GB, Chronos-2 ≈ 1 GB, Kronos ≈ 1,1 GB na proces; Memory Governor pilnuje progów 75/80/85 %."],
                 ["Dysk", "ok. 2 GB bot + modele", "Kronos-base ≈ 0,7 GB (PyTorch + wagi), Chronos-2 ≈ 0,75 GB, Granite TTM ≈ 0,3 GB (wagi 3 MB + PyTorch)."],
                 ["Internet", "przy instalacji", "Pakiety z sumami SHA-256; wagi modeli w przypiętych rewizjach. Instalacja offline: rozdz. 5."],
                 ["GPU (opcjonalnie)", "NVIDIA, CUDA 12.6 / 12.8", "Parametr cu126 / cu128 w instalatorach modeli; bez GPU działa na CPU."]],
                [34, 52, 84]),
          PageBreak()]
    # 2
    s += [P("2 / Instalacja bota", "h1"), P("Aplikacja Windows (zalecane)", "h2"),
          steps([f"Rozpakuj <b>PepeMarketWizard_DESKTOP_{TAG}.zip</b> do <b>nowego</b> folderu (nie nadpisuj starej wersji – to Twój punkt "
                 "powrotu). Porównaj sumę SHA-256 z plikiem <b>.sha256</b>.",
                 "Uruchom MT5 i zaloguj się do rachunku, którym bot ma handlować.",
                 f"Uruchom <b>PepeMarketWizardDesktop.exe</b> (tytuł okna: PepeMarketWizard {V}). Pierwszy start instaluje zależności – "
                 "postęp pokazuje okno startowe.",
                 "Po starcie widać intro (ok. 8,5 s, <b>POMIŃ INTRO</b> lub Esc), a potem menu główne <b>Galaxy</b>."]),
          box("Pliki EXE nie są podpisane certyfikatem Authenticode – Windows SmartScreen może pokazać ostrzeżenie. Uruchamiaj tylko paczkę "
              "o zgodnej sumie SHA-256.", "warn"),
          P("Wariant z plikami .bat (bez aplikacji Windows)", "h2"),
          steps(["<b>01_INSTALUJ.bat</b> – tworzy izolowane środowisko <b>.venv</b>, instaluje pakiety z sumami SHA-256, migruje bazę i "
                 "konfigurację (z kopią). Log w folderze <b>data\\logs</b>.",
                 "<b>02_DIAGNOSTYKA.bat</b> – sprawdza MT5, symbol, zegar serwera; nie składa zleceń.",
                 "<b>03_START_MASTERQUO.bat</b> – start serwera; panel: <b>http://127.0.0.1:8765/</b>. Zatrzymanie: <b>04_STOP_MASTERQUO.bat</b> "
                 "(otwarte pozycje NIE są zamykane – ich SL/TP zostają u brokera).",
                 "<b>07_START_DEMO_DANE_SYNTETYCZNE.bat</b> – symulator terminala (bez rachunku, osobna baza). Na danych syntetycznych bot "
                 "<b>nigdy</b> nie przechodzi w LIVE."]),
          P("Gdzie są dane", "h2"),
          bullets(["Aplikacja Windows: <b>%LOCALAPPDATA%\\PepeMarketWizard\\data</b> (tryb portable: folder programu).",
                   "Wariant .bat: folder <b>data\\</b> obok programu – <b>data\\config.json</b> (ustawienia), baza, modele, logi.",
                   "Kopie konfiguracji przy migracji: <b>data\\config.v13.bak.json</b> (kopia sprzed 1.39)."]),
          PageBreak()]
    # 3
    s += [P("3 / Tryb LIVE od startu – co się zmieniło w 1.39", "h1"),
          P("Na Twoje polecenie („włącz bota w tryb LIVE, zdejmij ograniczenia”) wersja 1.39 startuje od razu w <b>AUTO LIVE</b>. "
            "Zdjęte zostały <b>bramki walidacji</b>; bezpieczniki rachunku zostały – tak jak wybrałeś w pytaniu przed wdrożeniem."),
          table([["Zdjęte (blokowały wejścia LIVE)", "Pozostają (nadal chronią rachunek)"],
                 ["wymóg raportu walidacji (VALIDATED) dla 20 wariantów SC/HG – teraz tylko ostrzeżenie w planie",
                  "STOP (wyłącznik nowych wejść) – działa natychmiast"],
                 ["wymóg skalibrowanego modelu zdarzeń", "limity ryzyka: ryzyko na transakcję, łączne ryzyko, dzienna strata, drawdown, liczba pozycji"],
                 ["wymóg znanej prowizji instrumentu (bez prowizji – ostrzeżenie)", "kontrola spreadu, deduplikacja zleceń, uzgadnianie z MT5"],
                 ["REDUCE na rachunku NETTING bez walidacji – dozwolone z ostrzeżeniem", "wymóg rachunku REAL dla LIVE; dane syntetyczne nigdy nie idą LIVE"]],
                [85, 85]),
          P("Jak działa start", "h2"),
          bullets(["<b>data\\config.json → execution.start_mode = \"AUTO_LIVE\"</b> (domyślnie od 1.39). Przy starcie z prawdziwym terminalem "
                   "bot ustawia ten tryb.",
                   "<b>execution.live_autobind = true</b>: przy pierwszej decyzji bot wiąże tryb LIVE z zalogowanym rachunkiem <b>REAL</b> "
                   "(wpis LIVE_AUTOBIND w dzienniku). Rachunek DEMO nie zostaje związany – LIVE czeka. Zmiana rachunku w MT5 na inny "
                   "blokuje wejścia (ACCOUNT_DIFFERS_FROM_CONFIRMED_…), dopóki nie potwierdzisz nowego.",
                   "Do handlu nadal potrzebne są: <b>ścieżka główna</b> instrumentu (ACTIVE albo SH – panel <b>System Control → Tryb</b> lub "
                   "POST /api/v1/mode/primary-path) oraz <b>limity ryzyka</b> (risk_per_trade_pct, max_total_open_risk_pct, "
                   "daily_loss_limit_pct, max_drawdown_pct, max_open_positions). Bez nich bot pokazuje powód (PRIMARY_PATH_NOT_SELECTED, "
                   "RISK_LIMITS_NOT_CONFIGURED) i nie otwiera pozycji."]),
          P("Jak wyłączyć LIVE", "h2"),
          bullets(["Natychmiast: przycisk <b>STOP</b> (nowe wejścia zatrzymane; otwarte pozycje zostają z SL/TP).",
                   "Na stałe: w <b>data\\config.json</b> ustaw <b>\"execution\": {\"start_mode\": \"SIGNALS\"}</b> (albo \"AUTO_DEMO\", albo null = "
                   "ostatni zapisany tryb) i <b>\"live_autobind\": false</b>, potem uruchom bota ponownie.",
                   "Tryb możesz też zmienić w panelu System Control → Tryb (SIGNALS / PAPER / AUTO DEMO / AUTO LIVE)."]),
          box("Wyniki replay i walidacji nie są obietnicą zysku. Brak walidacji wariantu oznacza, że nie wiesz, jak zachowywał się na "
              "Twoich danych po kosztach. Zalecamy najpierw rachunek DEMO i rozdział 9 (walidacja), nawet jeśli LIVE już tego nie wymaga.", "warn"),
          PageBreak()]
    # 4
    s += [P("4 / Modele – przegląd", "h1"),
          table([["Model / grupa", "Rola w bocie", "Instalacja", "Trening"],
                 ["Kronos-base (NeoQuasar)", "prognoza świec M1/M5, SHADOW (bez zleceń)", "33_KRONOS_INSTALUJ.bat (.venv_kronos)",
                  "przetrenowany przez autorów – bot nie trenuje, tylko pobiera wagi"],
                 ["Chronos-2 (amazon, 120M)", "prognoza, rola OBSERVE + porównanie", "38_MODELE_CHRONOS2_GRANITE.bat chronos2 (.venv_chronos2)",
                  "zero-shot, wagi oficjalne"],
                 ["Granite TTM R2 (IBM, 0,8M)", "lekka prognoza punktowa, OBSERVE + porównanie", "38_MODELE_CHRONOS2_GRANITE.bat granite (.venv_granite)",
                  "zero-shot, wagi oficjalne"],
                 ["Rodziny modeli 1.33: TS_ARIMA, TS_SARIMAX, VOL_GARCH, MICROSTRUCTURE, PAIR_COINT, STATARB, KALMAN_LS, BREAKOUT, TH_RF, TH_XGB, "
                  "TH_SVM, SEQ_LSTM, SEQ_GRU, RL_PPO, NLP_SENTIMENT", "OFF / SHADOW / ASSIST", "w .venv; LSTM / GRU / PPO: 34_DEEP_INSTALUJ.bat",
                  "35_RODZINY_MODELI.bat lub python -m masterquo families …"],
                 ["Prognozy świec 5/15/30 min", "SHADOW", "10_PROGNOZY_INSTALUJ.bat (.venv_candles)", "11 → 12 → 13, rollback 14, start 15"],
                 ["Scalp ML (M5 Range → M1 Sweep)", "SHADOW", "10_PROGNOZY_INSTALUJ.bat", "16 → 19 → 17 → 18 → 20, rollback 21"],
                 ["Centrum treningu (modele bota XAUUSD / BTC)", "po ręcznej aktywacji", "01_INSTALUJ.bat", "32_CENTRUM_TRENINGU.bat / python -m masterquo trainhub"]],
                [44, 36, 46, 44]),
          box("Trening <b>nigdy nie aktywuje</b> modelu sam. Aktywacja to osobny krok (panel albo polecenie activate) z testem integralności "
              "i predykcji; <b>rollback</b> przywraca poprzednią wersję. Trafność modelu to nie zysk."),
          PageBreak()]
    # 5
    s += [P("5 / Instalacja modeli prognoz", "h1"), P("Kronos-base", "h2"),
          cmd("33_KRONOS_INSTALUJ.bat        (CPU)"), cmd("33_KRONOS_INSTALUJ.bat cu126  (GPU NVIDIA, CUDA 12.6)"),
          P("Tworzy izolowane <b>.venv_kronos</b> (PyTorch CPU ≈ 250 MB), pobiera oficjalne wagi Kronos-base + Kronos-Tokenizer-base "
            "(≈ 420 MB) w przypiętych rewizjach, sprawdza sumy i wykonuje prognozę testową. Główne .venv bota nie jest zmieniane. "
            "Status: <b>Wykresy bota → Kronos AI Forecast</b> oraz WTC PEPE → karta KRONOS."),
          P("Chronos-2 i Granite TTM (1.40: zamiast wycofanego FinCast)", "h2"),
          cmd("38_MODELE_CHRONOS2_GRANITE.bat                 (oba modele, CPU)"),
          cmd("38_MODELE_CHRONOS2_GRANITE.bat chronos2        |  38_MODELE_CHRONOS2_GRANITE.bat granite"),
          cmd("38_MODELE_CHRONOS2_GRANITE.bat all cu126       (GPU opcjonalnie; cu128 dla CUDA 12.8 – bot działa bez GPU)"),
          cmd("38_MODELE_CHRONOS2_GRANITE.bat all \"\" D:\\wagi  (instalacja offline z pobranych wcześniej plików wag)"),
          P("Każdy model ma własne środowisko (<b>.venv_chronos2</b>, <b>.venv_granite</b>), wagi z rozmiarem i SHA-256 każdego pliku, test "
            "ładowania i prognozę testową. Status i porównanie: <b>Wykresy bota → Modele prognoz</b>."),
          box("Kronos, Chronos-2 i Granite TTM to modele przetrenowane przez autorów (foundation models). Bot ich nie dotrenowuje – pobiera "
              "oficjalne wagi i liczy prognozy lokalnie. Nie wysyłają zleceń; ich prognoza jest informacją (SHADOW / OBSERVE)."),
          PageBreak()]
    # 6
    s += [P("6 / Rodziny modeli – instalacja i trening", "h1"),
          P("Rodziny modeli liczą się w głównym <b>.venv</b>; LSTM, GRU i PPO potrzebują dodatkowo PyTorch:"),
          cmd("34_DEEP_INSTALUJ.bat          (tworzy .venv_deep: PyTorch CPU, Gymnasium, Stable-Baselines3)"),
          P("Trening wszystkich gotowych rodzin", "h2"),
          cmd("35_RODZINY_MODELI.bat XAUUSD smoke      (profile: smoke | research | full; instrument: XAUUSD | BTC)"),
          P("Raport rozdziela DONE / BLOCKED / FAILED – BLOCKED oznacza brak danych lub środowiska, nie błąd. To samo z linii poleceń "
            "(w folderze programu, środowisko .venv):"),
          cmd("python -m masterquo families list --instrument XAUUSD"),
          cmd("python -m masterquo families train --instrument XAUUSD --family TS_ARIMA --profile research"),
          cmd("python -m masterquo families train-all --instrument XAUUSD --profile smoke"),
          P("Aktywacja, rola, powrót", "h2"),
          cmd("python -m masterquo families activate --instrument XAUUSD --family TS_ARIMA --run &lt;RUN_ID&gt;"),
          cmd("python -m masterquo families use --instrument XAUUSD --family TS_ARIMA --use SHADOW      (OFF | SHADOW | ASSIST)"),
          cmd("python -m masterquo families rollback --instrument XAUUSD --family TS_ARIMA"),
          bullets(["<b>activate</b> sprawdza integralność artefaktu i próbkę predykcji, po czym ustawia rolę SHADOW.",
                   "<b>ASSIST</b> pozwala, by wynik wpływał na ocenę sygnału; SHADOW tylko zapisuje predykcje do porównania.",
                   "RUN_ID znajdziesz w wyniku <b>train</b> albo w <b>families list</b> (kolumna active / runs)."]),
          PageBreak()]
    s += [P("6b / Granite TTM: trening i Memory Governor (1.40)", "h1"),
          bullets(["Dotrenowanie: <b>Wykresy bota → Modele prognoz → Granite TTM – dotrenowanie</b> → „Trenuj” (eksport świec z Centrum treningu, min. 5000; "
                   "osobny proces, zamrożony backbone, test na niewidzianych 15 % danych). Aktywacja tylko gdy wynik jest lepszy od modelu bazowego; "
                   "„Powrót do BASE” cofa. Trening nie startuje z botem i nie biegnie podczas handlu AUTO bez potwierdzenia.",
                   "API: GET /api/v1/models/foundation/granite, POST …/granite/train, …/granite/activate, …/granite/rollback, …/granite/cancel.",
                   "<b>Memory Governor</b>: profil LOW_MEMORY_16GB (domyślny), ECO, BALANCED lub MANUAL (Modele prognoz → Zasoby; API PUT /api/v1/resources/profile). "
                   "Progi RAM 75 / 80 / 85 %: ostrzeżenie, brak ładowania nowych ciężkich modeli, wstrzymanie opcjonalnych prognoz (stan STALE z powodem). "
                   "Kronos i Chronos-2 nigdy nie liczą jednocześnie. Dane rynkowe, pozycje, ryzyko i zlecenia nie czekają na modele.",
                   "Wyniki walidacji na złocie (Q4 2025): żaden z modeli nie pokonał prognozy „ostatnia cena” – dlatego rola domyślna to OBSERVE. "
                   "Szczegóły: docs/MIGRACJA_FINCAST_GRANITE_1_40_PL.md."]),
          PageBreak()]
    # 7
    s += [P("7 / GARCH (VOL_GARCH) i strategia PMW_HG09", "h1"),
          P("Rodzina <b>VOL_GARCH</b> (pakiet arch) dopasowuje model GARCH(1,1) do procentowych log-zwrotów M5 i prognozuje zmienność "
            "następnej świecy. W 1.39 strategia hedge <b>PMW_HG09</b> (adaptacyjny trend) może liczyć sigmę z GARCH zamiast odchylenia "
            "standardowego z 60 świec (domyślnie <b>STD_LOGRET_60_M5</b>)."),
          P("Kroki", "h2"),
          steps(["Wytrenuj: <b>python -m masterquo families train --instrument XAUUSD --family VOL_GARCH --profile research</b> "
                 "(wymaga historii M5 z Centrum treningu – rozdział 8). Wynik: APPROVED i RUN_ID.",
                 "Aktywuj: <b>python -m masterquo families activate --instrument XAUUSD --family VOL_GARCH --run &lt;RUN_ID&gt;</b>.",
                 "Przełącz HG09 na GARCH: strona <b>Strategie</b> → panel <b>Pakiet 20 strategii</b> → wiersz <b>PMW_HG09 – zmienność</b> → "
                 "<b>GARCH (VOL_GARCH)</b>. Obok widać stan modelu (READY z run / ω / α / β albo powód). Zapis to wersjonowana zmiana "
                 "konfiguracji wariantu (API: POST /api/v1/sh/strategies/config).",
                 "Sprawdź w planie / sygnale HG09: pola <b>sigma_method = VOL_GARCH</b>, <b>sigma_source</b> = RUN_ID oraz omega / alpha / beta."]),
          box("Bez cichego zastępstwa: jeśli GARCH nie jest wytrenowany i aktywny (status inny niż READY), HG09 zwraca <b>NO_DATA</b> z "
              "powodem <b>GARCH_NOT_READY</b> i nie wchodzi – nie przełącza się po cichu na odchylenie standardowe. Parametry modelu są "
              "zamrażane w planie, więc późniejszy retrening nie zmienia otwartego koszyka."),
          P("Replay z GARCH", "h2"),
          cmd("python -m masterquo sh pack-replay … --garch-json garch.json   (garch.json z artefaktu wytrenowanego modelu)"),
          PageBreak()]
    # 8
    s += [P("8 / Centrum treningu i eksport danych z MT5", "h1"),
          steps(["MT5 uruchomiony i zalogowany; w MT5: Narzędzia → Opcje → Wykresy → <b>Maks. barów na wykresie</b> ustaw wysoko "
                 "(np. Unlimited), inaczej terminal zwróci krótką historię.",
                 "Panel <b>Modele i trening → Centrum treningu</b> → <b>Eksportuj dane</b> (przyrostowo M1/M5/M15/M30) → "
                 "<b>Uruchom cały proces</b> (dataset, trening, ocena, paczki modeli). Bez panelu: <b>32_CENTRUM_TRENINGU.bat</b> "
                 "(opcje 1–8) albo:",
                 "<b>python -m masterquo trainhub export --instrument XAUUSD</b>, potem <b>python -m masterquo trainhub full --instrument XAUUSD</b>.",
                 "Aktywacja wersji: przycisk <b>Aktywuj</b> (test zgodności i predykcji) lub opcja 6 w 32_CENTRUM_TRENINGU.bat; "
                 "<b>Rollback</b> cofa."]),
          bullets(["Menu treningu dla wszystkiego naraz: <b>00_TRENING_START.bat</b> (instalacja, XAUUSD, BTC, oba, diagnostyka, wyniki, "
                   "wznowienie, rollback). Kod wyjścia: 0 wykonane, 1 błąd techniczny, 2 zablokowane, 3 anulowane, 4 część pominięta.",
                   "Prognozy świec: <b>11_EKSPORT_HISTORII_XAUUSD.bat 6</b> → <b>12_TRENING_MODELI_XAUUSD.bat</b> → "
                   "<b>13_WALIDACJA_MODELI_XAUUSD.bat</b> → <b>15_START_PROGNOZ_SHADOW.bat</b>; powrót <b>14_ROLLBACK_MODELU_PROGNOZ.bat</b>.",
                   "Scalp: <b>16_EKSPORT_HISTORII_SCALP.bat 6</b> → <b>19_REPLAY_SCALP.bat</b> → <b>17_TRENING_SCALP_ML.bat</b> → "
                   "<b>18_WALIDACJA_SCALP.bat</b> → <b>20_START_SCALP_SHADOW.bat</b>; powrót <b>21_ROLLBACK_MODELU_SCALP.bat</b>."]),
          box("Modele trenujesz osobno dla XAUUSD i BTC. Wynik na danych syntetycznych (symulator) nic nie mówi o rynku – do treningu "
              "i walidacji używaj historii z MT5.", "warn"),
          PageBreak()]
    # 9
    s += [P("9 / Walidacja", "h1"),
          P("W 1.39 walidacja nie blokuje już trybu LIVE, ale to jedyny sposób, by sprawdzić wariant po kosztach na Twoich danych."),
          cmd("39_PAKIET_20_WALIDACJA.bat     (replay walk-forward PMW_SC01–SC10 i PMW_HG01–HG10)"),
          P("Ten sam kod co w bocie (detektory, solver TP1/TP2, polityki hedge). Werdykt <b>VALIDATED</b> tylko na danych użytkownika "
            "ze znaną prowizją, ≥ 200 planów poza próbą, ≥ 3 dodatnich odcinkach i dodatniej dolnej granicy bootstrapu. Nic nie jest "
            "wysyłane do terminala. Inne walidacje: <b>30_SH_WALIDACJA.bat</b>, <b>31_MONTE_CARLO_WALIDACJA.bat</b>, "
            "<b>13_WALIDACJA_MODELI_XAUUSD.bat</b>, <b>18_WALIDACJA_SCALP.bat</b>."),
          PageBreak()]
    # 10
    s += [P("10 / Nowe menu, intro i WTC PEPE 2.1", "h1"),
          bullets(["<b>Intro startowe</b> (ok. 8,5 s): „$PEPEMARKET WIZARD” i „They call us cult but we are something more”, cyfrowa siatka "
                   "przechodząca w sieć neuronową. <b>POMIŃ INTRO</b> / Esc pomija, <b>Ctrl+Alt+B</b> lub <b>↻ INTRO</b> odtwarza ponownie. "
                   "Raz na sesję; przy ograniczonych animacjach systemu – od razu koniec.",
                   "<b>Menu Galaxy</b> (#/menu): 7 planet – WTC PEPE (środek), Brain Signal, PEPE$BANK, PEPE$ROI, Models, Signals, Settings – "
                   "pełna sieć 21/21 połączeń, boczne emitery, dolne błyskawice. Planeta otwiera prawdziwy ekran bota; planeta bez "
                   "sekcji pokazuje „Niepołączony moduł”. Status u góry pochodzi z backendu (MT5 ONLINE / DEMO SIM / OFFLINE / UNKNOWN).",
                   "<b>⚙ Projektuj</b>: przeciąganie planet, nazwa, rozmiar, pozycja, kolor, sekcja bota, efekty, dodaj / usuń planetę, "
                   "eksport / import JSON, reset. Poprzednie menu Neural City: <b>#/neural-city</b>.",
                   "<b>WTC PEPE → ⚙ CUSTOMIZE CHART</b> (Chart Lab 2.1): motywy, Candles / Hollow / Heikin Ashi / Line / Area, EMA, VWAP, BB, "
                   "RSI, MACD, ATR, SVP, SMC (okres, kolor, grubość), presety (zapis, import / eksport JSON). Session Volume Profile z POC i "
                   "Value Area dla okna lub sesji London / New York / Asia oraz największy impuls w oknie 3 / 5 / 8 / 12 świec – na "
                   "prawdziwych świecach MT5. Profil z OHLC to przybliżenie (bez footprint / ticków)."]),
          *shot(shots, "ui_galaxy/galaxy_1920x1080.png", "Menu Galaxy V2 – 7 planet, pełna sieć 21/21.", width_mm=150),
          *shot(shots, "ui_wtc_chartlab/chartlab_1920.png", "WTC PEPE – Chart Lab 2.1 z Session Volume Profile.", width_mm=150),
          PageBreak()]
    # 11
    s += [P("11 / Aktualizacja z 1.38 i powrót", "h1"),
          steps([f"Rozpakuj {V} do nowego folderu; skopiuj folder <b>data\\</b> ze starej wersji (aplikacja Windows robi to sama przy "
                 "pierwszym starcie – wybór danych w oknie startowym).",
                 "Przy pierwszym starcie konfiguracja przechodzi na wersję 14 (execution.start_mode, execution.live_autobind); kopia "
                 "poprzedniej: <b>data\\config.v13.bak.json</b>.",
                 "Sprawdź ścieżkę główną i limity ryzyka (rozdział 3) zanim zostawisz bota w LIVE."]),
          P("Powrót do 1.38", "h2"),
          steps(["<b>STOP</b>, potem zamknij aplikację (lub 04_STOP_MASTERQUO.bat).",
                 "Przywróć <b>data\\config.v13.bak.json</b> jako <b>data\\config.json</b> (1.38 nie zna wersji 14 konfiguracji).",
                 "Uruchom folder z wersją 1.38. Modele i baza są zgodne – 1.39 nie zmienia ich formatu."]),
          PageBreak()]
    # 12
    s += [P("12 / Problemy i logi", "h1"),
          table([["Objaw", "Co zrobić"],
                 ["LIVE nie otwiera pozycji", "Panel System Control → Tryb pokazuje powód: PRIMARY_PATH_NOT_SELECTED (wybierz ACTIVE / SH), "
                  "RISK_LIMITS_NOT_CONFIGURED (ustaw limity), AUTO_LIVE_BUT_ACCOUNT_IS_DEMO (zaloguj REAL), NEW_ENTRIES_STOPPED (zdejmij STOP)."],
                 ["HG09: NO_DATA GARCH_NOT_READY", "Wytrenuj i aktywuj VOL_GARCH (rozdział 7) albo wróć do volatility_method STD_LOGRET_60_M5."],
                 ["Model w stanie BLOCKED", "Brak danych lub środowiska – raport podaje powód; zainstaluj brakujące środowisko (34_DEEP_INSTALUJ.bat) "
                  "albo wyeksportuj więcej historii."],
                 ["Prognozy STALE „Memory Governor”", "RAM komputera ≥ 85 % (albo ≥ 80 % dla nieładowanego ciężkiego modelu) – zamknij inne programy lub zmień profil (Modele prognoz → Zasoby)."],
                 ["Krótka historia z MT5", "Zwiększ „Maks. barów na wykresie” w MT5 i powtórz eksport."],
                 ["Intro / animacje obciążają komputer", "⚙ Projektuj → wyłącz efekty; system z „ograniczonymi animacjami” pomija intro."]],
                [52, 118]),
          P("Logi", "h2"),
          bullets(["<b>data\\logs</b> – logi instalacji (01_INSTALUJ, 33_KRONOS_INSTALUJ, 38_…), serwera i treningu.",
                   "<b>02_DIAGNOSTYKA.bat</b> – raport środowiska, MT5 i zegara (zachowaj wynik przy zgłaszaniu problemu)."])]
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "data" / "logs"), help="folder ze zrzutami testów UI (opcjonalnie)")
    ap.add_argument("--out", default=str(ROOT / "release"))
    a = ap.parse_args()
    M.fonts()
    M.styles()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = Path(a.shots) if Path(a.shots).is_dir() else None
    M.build(out / NAME, "INSTALACJA • MODELE • TRENING", story(shots), "PepeMarketWizard – instalacja bota, modeli i trening")
    print(f"{NAME}: {(out / NAME).stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
