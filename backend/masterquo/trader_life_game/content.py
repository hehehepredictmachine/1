"""TraderLifeGame (TASK 019) - static, versioned game content: classes, difficulties, ranks, attributes, skill tree, quests,
academy curriculum and cosmetic catalogue.

Everything here is EDUCATIONAL / COSMETIC. Class bonuses only scale XP of matching learning activities; no value here ever reaches
strategies, signals, risk, lot size or execution. Difficulty milestones are aspirational virtual goals, never a return promise.
"""
from __future__ import annotations

CONTENT_VERSION = "TLG-CONTENT-1"

ATTRIBUTES = ("discipline", "risk_management", "analytical_intelligence", "strategy_mastery", "psychology", "patience", "consistency",
              "market_knowledge")

CLASSES = {
    "THE_ROOKIE": {"name": "THE ROOKIE", "avatar": "rookie", "specialization": "Fundamenty i nawyki",
                   "description": "Zaczynasz od zera: struktura rynku, dziennik i dyscyplina przed jakąkolwiek strategią.",
                   "start": {"discipline": 10, "risk_management": 10, "analytical_intelligence": 8, "strategy_mastery": 5, "psychology": 10,
                             "patience": 10, "consistency": 8, "market_knowledge": 8},
                   "xp_bonus": {"LESSON_COMPLETED": 1.10, "JOURNAL_NOTE_COMPLETED": 1.10},
                   "intro": "Witaj, Rookie. Nie szukamy dziś zysku – szukamy nawyku. Pierwszy krok: wpis w dzienniku i lekcja fundamentów."},
    "THE_ANALYST": {"name": "THE ANALYST", "avatar": "analyst", "specialization": "Analiza techniczna i kontekst",
                    "description": "Czytasz wykres jak mapę: poziomy, struktura, sesje. Twoja siła to przygotowanie przed wejściem.",
                    "start": {"discipline": 10, "risk_management": 8, "analytical_intelligence": 16, "strategy_mastery": 8, "psychology": 8,
                              "patience": 10, "consistency": 8, "market_knowledge": 12},
                    "xp_bonus": {"CHART_ANALYSIS": 1.15, "PLAN_PREPARED": 1.10},
                    "intro": "Analityku, wykres nie kłamie, ale łatwo go przeczytać pod tezę. Każdą analizę zapisuj razem z unieważnieniem."},
    "THE_STRATEGIST": {"name": "THE STRATEGIST", "avatar": "strategist", "specialization": "Budowa i walidacja strategii",
                       "description": "Myślisz regułami i próbą statystyczną. Backtest i out-of-sample to twój język.",
                       "start": {"discipline": 12, "risk_management": 10, "analytical_intelligence": 10, "strategy_mastery": 16, "psychology": 8,
                                 "patience": 10, "consistency": 10, "market_knowledge": 8},
                       "xp_bonus": {"SIM_SESSION_COMPLETED": 1.15, "QUIZ_PASSED": 1.05},
                       "intro": "Strategu, reguła bez walidacji to opinia. Zacznij od sesji w symulatorze i zapisz wynik bez upiększania."},
    "THE_SNIPER": {"name": "THE SNIPER", "avatar": "sniper", "specialization": "Cierpliwość i precyzja wejścia",
                   "description": "Mało wejść, dużo czekania. Wygrywa ten, kto potrafi nie handlować.",
                   "start": {"discipline": 14, "risk_management": 12, "analytical_intelligence": 10, "strategy_mastery": 8, "psychology": 10,
                             "patience": 16, "consistency": 8, "market_knowledge": 8},
                   "xp_bonus": {"TRADE_REVIEWED": 1.15, "RISK_EXERCISE": 1.10},
                   "intro": "Snajperze, dzień bez wejścia nie jest porażką. Twój pierwszy cel: przegląd jednej transakcji bez emocji."},
    "THE_QUANT": {"name": "THE QUANT", "avatar": "quant", "specialization": "Statystyka i odporność",
                  "description": "Liczby przed narracją: oczekiwana wartość, rozkład wyników, overfitting.",
                  "start": {"discipline": 10, "risk_management": 12, "analytical_intelligence": 14, "strategy_mastery": 12, "psychology": 8,
                            "patience": 8, "consistency": 10, "market_knowledge": 10},
                  "xp_bonus": {"QUIZ_PASSED": 1.15, "SIM_SESSION_COMPLETED": 1.05},
                  "intro": "Quancie, mała próba kłamie najgłośniej. Zacznij od testu wiedzy z poziomu 4 i policz, czego jeszcze nie wiesz."},
}

DIFFICULTIES = {
    "EASY": {"name": "EASY — THE APPRENTICE", "milestone": 10_000, "focus": ["edukacja podstawowa", "proste ćwiczenia", "podstawy ryzyka"]},
    "MEDIUM": {"name": "MEDIUM — THE PROFESSIONAL", "milestone": 50_000, "focus": ["ćwiczenia zaawansowane", "budowa strategii", "backtest i statystyka"]},
    "HARD": {"name": "HARD — THE LEGEND", "milestone": 100_000, "focus": ["trening ilościowy", "walidacja strategii", "zaawansowane ryzyko"]},
}
MILESTONE_NOTE = "Kamień milowy to wirtualny cel gry, nie obietnica ani prognoza zarobku."

RANKS = ((10, "Beginner"), (20, "Apprentice"), (30, "Trader"), (40, "Skilled Trader"), (50, "Professional"), (60, "Senior Trader"),
         (70, "Expert"), (80, "Master"), (90, "Grandmaster"), (100, "Trading Legend"))

# XP needed to REACH level L (cumulative): 0 for L=1, then 50 * (L-1)^1.6 rounded. Deterministic, documented, configurable via XP_BASE/XP_EXP.
XP_BASE, XP_EXP, MAX_LEVEL = 50, 1.6, 100

# activity -> (base XP, attribute deltas). Only verified learning / discipline activities. NO trade count, volume, leverage, deposits.
ACTIVITIES = {
    "JOURNAL_NOTE_COMPLETED": (25, {"discipline": 1, "consistency": 1}),
    "TRADE_REVIEWED": (30, {"psychology": 1, "discipline": 1}),
    "LESSON_COMPLETED": (40, {"market_knowledge": 1}),
    "QUIZ_PASSED": (60, {"analytical_intelligence": 1, "market_knowledge": 1}),
    "RISK_EXERCISE": (50, {"risk_management": 2}),
    "CHART_ANALYSIS": (20, {"analytical_intelligence": 1}),
    "PLAN_PREPARED": (20, {"discipline": 1, "patience": 1}),
    "SIM_SESSION_COMPLETED": (45, {"strategy_mastery": 1, "patience": 1}),
    "WEEKLY_REVIEW": (80, {"consistency": 2, "psychology": 1}),
    "MISTAKE_IDENTIFIED": (25, {"psychology": 1}),
    "QUEST_COMPLETED": (0, {}),                 # quest rewards carry their own XP
}
DAILY_ACTIVITY_CAP = {"CHART_ANALYSIS": 5, "PLAN_PREPARED": 3, "JOURNAL_NOTE_COMPLETED": 10, "TRADE_REVIEWED": 10, "MISTAKE_IDENTIFIED": 5}

SKILL_BRANCHES = {
    "RISK": "Risk Management", "TA": "Technical Analysis", "PSY": "Trading Psychology", "QUANT": "Quantitative Analysis", "STRAT": "Strategy Development",
}
SKILLS = [
    # id, branch, name, description, min_level, requires
    ("RISK_1", "RISK", "Ryzyko na transakcję", "Stałe ryzyko procentowe i liczenie wielkości pozycji od SL.", 1, []),
    ("RISK_2", "RISK", "Limit dzienny", "Dzienny limit straty i zasada stopu po serii.", 5, ["RISK_1"]),
    ("RISK_3", "RISK", "Korelacja ekspozycji", "Łączne ryzyko skorelowanych pozycji.", 15, ["RISK_2"]),
    ("RISK_4", "RISK", "Drawdown i powrót", "Matematyka obsunięcia i plan ograniczenia ryzyka.", 30, ["RISK_3"]),
    ("TA_1", "TA", "Struktura rynku", "Swingi, BOS i CHoCH na zamkniętych świecach.", 1, []),
    ("TA_2", "TA", "Poziomy i strefy", "Wsparcia, opory, strefy podaży/popytu.", 5, ["TA_1"]),
    ("TA_3", "TA", "Sesje i płynność", "Zakresy sesji, sweep i reclaim.", 15, ["TA_2"]),
    ("TA_4", "TA", "Kontekst wielu interwałów", "Zgodność HTF/LTF bez przeuczenia.", 30, ["TA_3"]),
    ("PSY_1", "PSY", "Dziennik emocji", "Zapisywanie stanu przed i po wejściu.", 1, []),
    ("PSY_2", "PSY", "Bez zemsty", "Przerwa po stracie zamiast odgrywania się.", 5, ["PSY_1"]),
    ("PSY_3", "PSY", "Akceptacja niepewności", "Myślenie seriami, nie pojedynczą transakcją.", 15, ["PSY_2"]),
    ("PSY_4", "PSY", "Rutyna wydajności", "Stały proces przed sesją i po niej.", 30, ["PSY_3"]),
    ("QUANT_1", "QUANT", "Oczekiwana wartość", "Win rate × średni zysk − loss rate × średnia strata.", 1, []),
    ("QUANT_2", "QUANT", "Wielkość próby", "Dlaczego 20 transakcji nic nie dowodzi.", 10, ["QUANT_1"]),
    ("QUANT_3", "QUANT", "Monte Carlo", "Rozkład obsunięć z permutacji wyników.", 20, ["QUANT_2"]),
    ("QUANT_4", "QUANT", "Out-of-sample", "Walk-forward, embargo i overfitting.", 35, ["QUANT_3"]),
    ("STRAT_1", "STRAT", "Reguły wejścia", "Setup, trigger, unieważnienie zapisane z góry.", 1, []),
    ("STRAT_2", "STRAT", "Backtest", "Test historyczny bez podglądu przyszłości.", 8, ["STRAT_1"]),
    ("STRAT_3", "STRAT", "Koszty i poślizg", "Spread, prowizja, swap w wyniku strategii.", 18, ["STRAT_2"]),
    ("STRAT_4", "STRAT", "Portfel strategii", "Dywersyfikacja reguł i reżimów.", 35, ["STRAT_3"]),
]
SKILL_XP_COST = 100          # XP "spent" is not deducted from progression - skill points = floor(level/2) unlock budget

# Quests: verified by counting authoritative game events inside the quest window (UTC day / ISO week / lifetime)
QUESTS = [
    # id, category, title, description, activity, count, xp, gold, difficulty (min difficulty or None)
    ("D_JOURNAL", "DAILY", "Uzupełnij dziennik", "Dodaj kompletny wpis do co najmniej jednej transakcji.", "JOURNAL_NOTE_COMPLETED", 1, 30, 10, None),
    ("D_CHART", "DAILY", "Przeanalizuj wykres", "Zapisz analizę wykresu z poziomem unieważnienia.", "CHART_ANALYSIS", 1, 20, 5, None),
    ("D_PLAN", "DAILY", "Przygotuj plan dnia", "Zapisz plan: rynek, sesja, scenariusze, maks. ryzyko.", "PLAN_PREPARED", 1, 20, 5, None),
    ("D_LESSON", "DAILY", "Ćwiczenie edukacyjne", "Ukończ jedną lekcję akademii.", "LESSON_COMPLETED", 1, 25, 10, None),
    ("D_REVIEW", "DAILY", "Przegląd transakcji", "Oceń wykonanie jednej wcześniejszej transakcji.", "TRADE_REVIEWED", 1, 25, 10, None),
    ("W_BACKTEST", "WEEKLY", "Trzy backtesty", "Ukończ trzy sesje symulatora.", "SIM_SESSION_COMPLETED", 3, 120, 40, None),
    ("W_SETUPS", "WEEKLY", "Dziesięć setupów", "Przeanalizuj dziesięć historycznych setupów.", "CHART_ANALYSIS", 10, 120, 40, None),
    ("W_REPORT", "WEEKLY", "Raport tygodniowy", "Wygeneruj i zapisz przegląd tygodnia.", "WEEKLY_REVIEW", 1, 100, 40, None),
    ("W_MISTAKES", "WEEKLY", "Trzy powtarzalne błędy", "Nazwij trzy powtarzające się błędy.", "MISTAKE_IDENTIFIED", 3, 90, 30, None),
    ("W_RISK", "WEEKLY", "Ocena zarządzania ryzykiem", "Zalicz ćwiczenie z ryzyka.", "RISK_EXERCISE", 1, 100, 40, None),
    ("S_7DAYS", "SPECIAL", "7 dni dyscypliny", "Wpis w dzienniku lub plan dnia przez 7 różnych dni.", "DISCIPLINE_DAYS", 7, 300, 150, None),
    ("S_NO_REVENGE", "SPECIAL", "Bez revenge tradingu", "5 przeglądów transakcji ze zgodnością z regułami.", "RULE_COMPLIANT_REVIEW", 5, 250, 120, None),
    ("S_PERFECT_WEEK", "SPECIAL", "Perfekcyjny tydzień dziennika", "Wpisy w dzienniku w 5 różnych dniach jednego tygodnia.", "JOURNAL_DAYS_WEEK", 5, 250, 120, None),
    ("S_RISK_MASTER", "SPECIAL", "Mistrz ryzyka", "Zalicz 5 ćwiczeń z ryzyka.", "RISK_EXERCISE", 5, 300, 150, None),
    ("S_BUILDER", "SPECIAL", "Budowniczy strategii", "Ukończ 10 sesji symulatora.", "SIM_SESSION_COMPLETED", 10, 300, 150, None),
    ("S_PSYCHO", "SPECIAL", "Trening psychologii", "Ukończ wszystkie lekcje psychologii (poziom 2).", "LESSON_COMPLETED", 8, 250, 120, None),
    ("M_EASY", "MAIN", "Kampania Apprentice", "Ukończ poziom 1 i 2 akademii oraz zalicz ich testy.", "QUIZ_PASSED", 2, 500, 250, "EASY"),
    ("M_MEDIUM", "MAIN", "Kampania Professional", "Zalicz testy poziomów 1–3 akademii.", "QUIZ_PASSED", 3, 800, 400, "MEDIUM"),
    ("M_HARD", "MAIN", "Kampania Legend", "Zalicz testy wszystkich 4 poziomów akademii.", "QUIZ_PASSED", 4, 1200, 600, "HARD"),
]
DIFF_ORDER = {"EASY": 1, "MEDIUM": 2, "HARD": 3}


def _lesson(lid, title, body, example, exercise):
    return {"id": lid, "title": title, "body": body, "example": example, "exercise": exercise, "source": "AUTHORED_REFERENCE"}


ACADEMY = {
    1: {"name": "FOUNDATIONS", "lessons": [
        _lesson("L1_MARKET", "Podstawy rynku", "Cena to miejsce, gdzie kupujący i sprzedający się zgadzają. Bid/ask i spread to koszt wejścia.",
                "Spread 0,30 na XAUUSD oznacza, że świeża pozycja zaczyna od straty 0,30 na uncję.", "Zapisz bieżący spread instrumentu i porównaj z ATR."),
        _lesson("L1_CANDLES", "Świece", "Świeca to OHLC jednego interwału. Liczy się tylko świeca ZAMKNIĘTA – formująca może się zmienić.",
                "Długi dolny knot po spadku = odrzucenie niższych cen w tym interwale, nie gwarancja odwrócenia.", "Opisz 3 ostatnie zamknięte świece H1."),
        _lesson("L1_SR", "Wsparcie i opór", "Poziom to obszar, nie linia. Wielokrotne reakcje zwiększają jego znaczenie.",
                "Strefa 2400–2403 z trzema odrzuceniami.", "Zaznacz dwie strefy na D1 i jedną na H1."),
        _lesson("L1_TA", "Analiza techniczna – podstawy", "Trend, zakres, zmienność. Wskaźnik opisuje przeszłość, nie przyszłość.",
                "EMA 50 rosnąca + wyższe dołki = kontekst trendu wzrostowego.", "Sklasyfikuj rynek: trend / zakres / kompresja."),
    ], "quiz": [
        ("Która świeca może być podstawą sygnału?", ["Formująca", "Zamknięta", "Dowolna"], 1),
        ("Spread to:", ["Koszt wejścia", "Zysk brokera z dźwigni", "Zmienność"], 0),
        ("Poziom wsparcia najlepiej traktować jako:", ["Dokładną linię", "Obszar", "Sygnał kupna"], 1),
    ]},
    2: {"name": "TRADING SKILLS", "lessons": [
        _lesson("L2_RISK", "Zarządzanie ryzykiem", "Ryzyko na transakcję = odległość SL × wielkość pozycji. Stały % konta chroni przed ruiną.",
                "Konto 10 000, ryzyko 1% = 100; SL 5,00 → wielkość 20 jednostek.", "Policz wielkość pozycji dla SL 3,50 i ryzyka 0,5%."),
        _lesson("L2_STRUCTURE", "Struktura rynku", "HH/HL to trend wzrostowy; złamanie ostatniego HL zmienia strukturę.",
                "BOS w górę po sweepie dołka.", "Zaznacz ostatni BOS i CHoCH na M15."),
        _lesson("L2_SESSIONS", "Sesje", "Azja, Londyn, Nowy Jork mają różną płynność. Godziny brokera ≠ godziny giełdy.",
                "Otwarcie Londynu często wybija zakres Azji – to obserwacja, nie reguła.", "Zapisz zakres sesji azjatyckiej z wczoraj."),
        _lesson("L2_PLAN", "Plan wejścia i wyjścia", "Przed wejściem: setup, trigger, SL, TP, unieważnienie i maks. czas.",
                "Wejście po retest, SL za ekstremum, TP 2R, wyjście po 20 świecach.", "Napisz plan dla jednego scenariusza."),
        _lesson("L2_PSY_1", "Emocje i decyzje", "Strach i chciwość zmieniają wykonanie planu. Dziennik ujawnia wzorce.",
                "Trzy wejścia po stracie w 15 minut = sygnał przerwy.", "Opisz swój stan przed ostatnią transakcją."),
        _lesson("L2_PSY_2", "Revenge trading", "Odgrywanie się po stracie zwiększa ryzyko i zmniejsza jakość decyzji.",
                "Zasada: po 2 stratach koniec dnia.", "Ustal własną regułę przerwy."),
        _lesson("L2_PSY_3", "Cierpliwość", "Brak setupu = brak wejścia. Dzień bez transakcji jest neutralny.",
                "Snajper czeka na A+ setup.", "Policz, ile dni w tygodniu było bez setupu."),
        _lesson("L2_PSY_4", "Rutyna", "Stały proces przed sesją i po sesji zmniejsza przypadkowość.",
                "Checklista 5 punktów przed otwarciem platformy.", "Spisz swoją checklistę."),
    ], "quiz": [
        ("Konto 10 000, ryzyko 1%, SL 5,00 – wielkość pozycji:", ["2", "20", "200"], 1),
        ("Po serii strat najlepiej:", ["Zwiększyć wielkość", "Zrobić przerwę wg reguły", "Zmienić strategię od razu"], 1),
        ("Godziny serwera brokera to zawsze godziny giełdy:", ["Tak", "Nie"], 1),
    ]},
    3: {"name": "STRATEGY DEVELOPMENT", "lessons": [
        _lesson("L3_BUILD", "Budowa strategii", "Strategia = jednoznaczne reguły: kontekst, setup, trigger, wyjście, ryzyko.",
                "Jeśli dwie osoby różnie odczytują regułę, reguła jest niejednoznaczna.", "Zapisz regułę tak, by dało się ją zaprogramować."),
        _lesson("L3_BACKTEST", "Backtest", "Test na historii tylko z danymi dostępnymi w danej chwili – bez podglądu przyszłości.",
                "Wejście po close świecy, nie w jej środku.", "Wykonaj sesję w symulatorze i zapisz 10 wyników."),
        _lesson("L3_EXPECT", "Oczekiwana wartość", "E = WR × śr. zysk − (1−WR) × śr. strata, po kosztach.",
                "WR 40%, zysk 2R, strata 1R → E = 0,2R.", "Policz E dla WR 55%, zysk 1R, strata 1R, koszt 0,1R."),
        _lesson("L3_PF", "Profit Factor", "PF = suma zysków / suma strat. PF < 1 = strategia traci.",
                "Zyski 1500, straty 1000 → PF 1,5.", "Policz PF z ostatnich 20 wyników symulatora."),
        _lesson("L3_DD", "Drawdown", "Maks. obsunięcie od szczytu kapitału. Powrót z −50% wymaga +100%.",
                "Kapitał 12 000 → 9 000: DD 25%.", "Policz DD dla swojej krzywej symulatora."),
    ], "quiz": [
        ("WR 40%, zysk 2R, strata 1R – oczekiwana wartość:", ["0,2R", "0,4R", "−0,2R"], 0),
        ("PF 0,8 oznacza:", ["Zysk", "Stratę", "Brak danych"], 1),
        ("Backtest może używać ceny zamknięcia świecy przed jej zamknięciem:", ["Tak", "Nie"], 1),
    ]},
    4: {"name": "ADVANCED QUANT", "lessons": [
        _lesson("L4_STATS", "Analiza statystyczna", "Rozkład wyników, wariancja i przedziały ufności zamiast pojedynczej liczby.",
                "30 transakcji to bardzo szeroki przedział dla WR.", "Policz odchylenie standardowe wyników w R."),
        _lesson("L4_MC", "Monte Carlo", "Permutacje kolejności wyników pokazują rozkład obsunięć.",
                "Ta sama lista wyników może dać DD 8% albo 22%.", "Opisz, dlaczego kolejność wyników zmienia DD."),
        _lesson("L4_ROBUST", "Odporność strategii", "Strategia odporna działa w sąsiedztwie parametrów, nie tylko w jednym punkcie.",
                "EMA 20 działa, EMA 19 i 21 nie → podejrzenie overfittingu.", "Sprawdź wynik dla ±10% parametru."),
        _lesson("L4_OOS", "Out-of-sample", "Dane testowe nie mogą wpływać na wybór parametrów. Walk-forward z embargiem.",
                "Strojenie na 2020–2023, test na 2024 bez zmian.", "Podziel swoją historię na IS i OOS."),
        _lesson("L4_OVERFIT", "Overfitting", "Im więcej prób, tym większa szansa na fałszywie dobry wynik.",
                "100 wariantów → najlepszy często jest szczęściem.", "Zapisz liczbę testowanych wariantów."),
    ], "quiz": [
        ("Najlepszy z 100 wariantów na tych samych danych to:", ["Dowód przewagi", "Możliwe szczęście (multiple testing)", "Gwarancja"], 1),
        ("Out-of-sample służy do:", ["Strojenia parametrów", "Niezależnej oceny", "Zwiększenia próby"], 1),
        ("Monte Carlo kolejności wyników pokazuje:", ["Rozkład obsunięć", "Przyszłą cenę", "Win rate"], 0),
    ]},
}
QUIZ_PASS = 2 / 3                       # >= 2 of 3 correct
RISK_QUIZ_LEVEL = 2                     # level-2 quiz also counts as a RISK_EXERCISE

LIFESTYLE = [
    # id, slot, name, price (Trader Gold), min_level
    ("DESK_BASIC", "desk", "Biurko tradera", 0, 1), ("DESK_PRO", "desk", "Biurko z blatem dębowym", 150, 5),
    ("MON_DUAL", "monitors", "Dwa monitory", 100, 3), ("MON_SIX", "monitors", "Ściana 6 monitorów", 600, 25),
    ("PC_WORK", "computer", "Stacja robocza", 200, 8), ("PC_QUANT", "computer", "Serwer obliczeniowy", 900, 40),
    ("OFFICE_HOME", "office", "Domowe biuro", 0, 1), ("OFFICE_CITY", "office", "Biuro w centrum", 1200, 45),
    ("APT_STUDIO", "apartment", "Kawalerka", 0, 1), ("APT_LOFT", "apartment", "Loft", 1500, 50),
    ("FURN_CHAIR", "furniture", "Fotel ergonomiczny", 120, 4), ("CLOTH_SUIT", "clothing", "Garnitur", 250, 10),
    ("WATCH_STEEL", "watch", "Zegarek stalowy", 300, 15), ("WATCH_GOLD", "watch", "Zegarek złoty", 1000, 60),
    ("CAR_SEDAN", "vehicle", "Sedan", 800, 30), ("CAR_SPORT", "vehicle", "Auto sportowe", 2500, 75),
    ("ROOM_PREMIUM", "room", "Premium Trading Room", 3000, 85),
    ("TITLE_DISCIPLINED", "title", "Tytuł: Zdyscyplinowany", 200, 10), ("FRAME_GOLD", "frame", "Złota ramka profilu", 400, 20),
]
DEFAULT_ITEMS = ("DESK_BASIC", "OFFICE_HOME", "APT_STUDIO")
