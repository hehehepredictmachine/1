"""Builds the two PDF manuals (§6 of the update package; 1.30: without the removed license system):

  release/Instrukcja_Administrator_PepeMarketWizard.pdf   (administrator / owner of the bot)
  release/Instrukcja_Klient_PepeMarketWizard.pdf          (user)

  python tools/make_manuals.py [--shots data/logs] [--out release]

Layout of the manuals delivered with the package (header band, chapters "N / title", note and warning boxes, footer with the version),
text matching the 1.30 screens. Fonts: DejaVu Sans embedded (Polish characters). Screenshots (optional) come from the UI tests
(data/logs/ui_*), taken on the terminal SIMULATOR - every picture is captioned as synthetic data. Requires reportlab.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.40.2"
TAG = VERSION.replace(".", "_")
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts"), ROOT / "build" / "fonts"]

DARK = colors.HexColor("#14261b")
GREEN = colors.HexColor("#1f6b45")
NOTE_BG, NOTE_LINE = colors.HexColor("#eef6f0"), colors.HexColor("#b9d8c4")
WARN_BG, WARN_LINE = colors.HexColor("#fff4e6"), colors.HexColor("#f0c890")
BLOCK_BG, BLOCK_LINE = colors.HexColor("#fdecec"), colors.HexColor("#e5a3a3")
GREY = colors.HexColor("#555b66")


def fonts() -> None:
    for d in FONT_DIRS:
        reg, bold = d / "DejaVuSans.ttf", d / "DejaVuSans-Bold.ttf"
        if reg.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("DejaVu", str(reg)))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))
            pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu", boldItalic="DejaVu-Bold")
            from reportlab import rl_config
            rl_config.canvas_basefontname = "DejaVu"          # no unembedded Helvetica reference anywhere in the file
            return
    sys.exit("brak czcionek DejaVu Sans (DejaVuSans.ttf, DejaVuSans-Bold.ttf) – potrzebne do polskich znaków")


ST = {}


def styles() -> None:
    ST["title"] = ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=27, leading=32, textColor=DARK, spaceAfter=10)
    ST["lead"] = ParagraphStyle("lead", fontName="DejaVu", fontSize=11.5, leading=16, textColor=GREY, spaceAfter=12)
    ST["h1"] = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=17, leading=22, textColor=DARK, spaceBefore=2, spaceAfter=8)
    ST["h2"] = ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=11.5, leading=15, textColor=GREEN, spaceBefore=8, spaceAfter=4)
    ST["p"] = ParagraphStyle("p", fontName="DejaVu", fontSize=9.6, leading=13.6, textColor=colors.black, spaceAfter=5, alignment=TA_LEFT,
                             bulletFontName="DejaVu")
    ST["li"] = ParagraphStyle("li", parent=ST["p"], spaceAfter=3)
    ST["box"] = ParagraphStyle("box", parent=ST["p"], fontSize=9.2, leading=13, spaceAfter=0)
    ST["cap"] = ParagraphStyle("cap", parent=ST["p"], fontSize=8, leading=10.5, textColor=GREY, spaceAfter=8)
    ST["cell"] = ParagraphStyle("cell", parent=ST["p"], fontSize=8.4, leading=11, spaceAfter=0)
    ST["cellb"] = ParagraphStyle("cellb", parent=ST["cell"], fontName="DejaVu-Bold")


def P(text: str, st: str = "p") -> Paragraph:
    return Paragraph(text, ST[st])


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(P(t, "li"), leftIndent=12, value="•", bulletFontName="DejaVu") for t in items], bulletType="bullet", start="•",
                        leftIndent=12, bulletFontName="DejaVu", bulletFontSize=9)


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(P(t, "li"), leftIndent=16, bulletFontName="DejaVu-Bold") for t in items], bulletType="1", leftIndent=16,
                        bulletFontName="DejaVu-Bold",
                        bulletFontSize=9, bulletFormat="%s.")


def box(text: str, kind: str = "note") -> Table:
    bg, line = {"note": (NOTE_BG, NOTE_LINE), "warn": (WARN_BG, WARN_LINE), "block": (BLOCK_BG, BLOCK_LINE)}[kind]
    t = Table([[P(text, "box")]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.8, line),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([Spacer(1, 4), t, Spacer(1, 6)])


def table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[P(c, "cellb" if i == 0 else "cell") for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("BACKGROUND", (0, 0), (-1, 0), NOTE_BG), ("GRID", (0, 0), (-1, -1), 0.4, NOTE_LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def shot(shots: Path | None, rel: str, caption: str, width_mm: float = 170, crop: tuple | None = None) -> list:
    """Screenshot from the UI tests (simulator) with a caption; skipped when not available."""
    if not shots:
        return []
    p = shots / rel
    if not p.exists():
        return []
    src = p
    if crop:
        from PIL import Image as PILImage
        im = PILImage.open(p)
        w, h = im.size
        box_ = (int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h))
        tmp = Path(ROOT / "build" / "manual_img")
        tmp.mkdir(parents=True, exist_ok=True)
        src = tmp / (p.stem + f"_{abs(hash(crop)) % 10**6}.png")
        im.crop(box_).save(src)
    from PIL import Image as PILImage
    im = PILImage.open(src)
    if im.width > 1400 or p.stat().st_size > 400_000:   # artwork screenshots (1.32): embedded as a smaller JPEG, not a multi-MB PNG
        tmp = Path(ROOT / "build" / "manual_img")
        tmp.mkdir(parents=True, exist_ok=True)
        im = im.convert("RGB")
        if im.width > 1400:
            im = im.resize((1400, round(im.height * 1400 / im.width)), PILImage.LANCZOS)
        src = tmp / (src.stem + "_s.jpg")
        im.save(src, quality=84, optimize=True)
    w, h = PILImage.open(src).size
    width = width_mm * mm
    return [KeepTogether([Image(str(src), width=width, height=width * h / w), P(caption + " <i>(symulator – dane syntetyczne)</i>", "cap")])]


def page_deco(role: str):
    def deco(c, doc):
        w, h = A4
        c.saveState()
        c.setFillColor(DARK)
        c.rect(0, h - 15 * mm, w, 15 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("DejaVu-Bold", 8.5)
        c.drawString(18 * mm, h - 9.4 * mm, "PEPEMARKETWIZARD")
        c.setFont("DejaVu", 7.5)
        c.drawRightString(w - 18 * mm, h - 9.4 * mm, role)
        c.setStrokeColor(NOTE_LINE)
        c.setLineWidth(0.6)
        c.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        c.setFillColor(GREY)
        c.setFont("DejaVu", 7)
        c.drawString(18 * mm, 9.5 * mm, f"INSTRUKCJA • WERSJA {VERSION} • {role}")
        c.drawRightString(w - 18 * mm, 9.5 * mm, str(doc.page))
        c.restoreState()
    return deco


def build(path: Path, role: str, story: list, title: str) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=24 * mm, bottomMargin=20 * mm,
                            title=title, author="PepeMarketWizard", subject=f"PepeMarketWizard {VERSION}", creator="tools/make_manuals.py",
                            initialFontName="DejaVu", initialFontSize=9)
    deco = page_deco(role)
    doc.build(story, onFirstPage=deco, onLaterPages=deco)


# ---------------------------------------------------------------------------------------------------------------- administrator
def admin(shots: Path | None) -> list:
    s: list = [Spacer(1, 18 * mm), P("Instrukcja<br/>administratora", "title"),
               P("Obsługa bota PepeMarketWizard " + VERSION + ": uruchomienie (launcher JOIN THE CULT), menu główne – stół neuronowy (osiem wież), "
                 "panele Lightning / Wind / Control / Strategy Lab, wykresy i strefy, trening modeli, wydawanie paczek, aktualizacja "
                 "i powrót.", "lead"),
               box("<b>Stan:</b> instrukcja odpowiada wersji <b>" + VERSION + "</b>. Opisane ekrany i polecenia zostały uruchomione "
                   "i sprawdzone testami w Chromium na symulatorze terminala. Czego nie dało się sprawdzić – oznaczono "
                   "„nie sprawdzono”. <b>System licencji został usunięty</b> (na Twoją prośbę): program działa bez klucza, "
                   "nie ma License Managera, okna KEY FOR MAGIC, wersji CLIENT ani serwera licencji."),
               P("Co znajdziesz w instrukcji", "h2"),
               bullets(["Uruchomienie aplikacji (launcher JOIN THE CULT) i połączenie z MT5.",
                        "Menu główne (sześć wież), panele Lightning / Wind / Control / Strategy Lab, menu boczne i pasek stanu.",
                        "Wykresy: „Wyznacz strefy”, własne ustawienia wykresu, warstwy.", "Eksport danych i trening modeli.",
                        "Paczki do przekazania innym osobom (bez licencji).", "Aktualizacja z 1.29, kopia i powrót, typowe problemy."]),
               box("Nie przeprowadzono tutaj testu na Twoim Windows ani połączenia z prawdziwym MT5. Zrzuty ekranu pochodzą "
                   "z symulatora (dane syntetyczne). Sprawdź działanie na rachunku DEMO, zanim użyjesz AUTO LIVE.", "warn"),
               PageBreak()]
    # 1
    s += [P("1 / Pierwsze uruchomienie", "h1"), P("Przygotowanie", "h2"),
          bullets(["Rozpakuj paczkę <b>PepeMarketWizard_DESKTOP_" + TAG + ".zip</b> do nowego folderu (nie nadpisuj starej wersji). "
                   "Zachowaj kopię danych sprzed aktualizacji (rozdział 6).",
                   "Uruchom MT5 i zaloguj się do właściwego rachunku. Symbol brokera (np. <b>XAUUSD-</b>) musi być widoczny w Market Watch.",
                   "Windows potrzebuje WebView2. Pierwszy start instaluje zależności z Internetu (lub z paczki OFFLINE)."]),
          P("Start aplikacji", "h2"),
          P("Uruchom <b>PepeMarketWizardDesktop.exe</b> (tytuł okna: <b>PepeMarketWizard " + VERSION + "</b>). Klucz licencji nie jest potrzebny. "
            "Przy problemie uruchom <b>02_DIAGNOSTYKA.bat</b> i zachowaj wynik."),
          P("Najpierw otwiera się małe okno <b>JOIN THE CULT</b> (launcher): pokazuje postęp pierwszego startu, wybór danych poprzedniej "
            "instalacji albo błąd z przyciskami <b>Spróbuj ponownie</b>, <b>Otwórz folder logów</b> i <b>Zamknij</b>. Gdy silnik działa, "
            "launcher pokazuje <b>SYSTEM READY</b> – bot pracuje już w tle. Tłem launchera jest grafika Pepe przemawiającego do zgromadzenia. "
            "<b>JOIN THE CULT</b> (na dole, pośrodku) powiększa okno do 85 % ekranu i otwiera menu główne (<b>stół neuronowy</b>) po krótkim "
            "intro „lotu przez sieć neuronów” (<b>Pomiń intro</b> albo Esc; przy ograniczonych animacjach systemu intro jest pomijane). "
            "W przeglądarce (bez aplikacji Windows) ten sam launcher pojawia się na początku sesji."),
          *shot(shots, "ui_neural_city/01_launcher_1920.png", "Launcher JOIN THE CULT – SYSTEM READY.", width_mm=150),
          P("Dane aplikacji Windows: <b>%LOCALAPPDATA%\\PepeMarketWizard\\data</b> (tryb portable: folder programu). Kopie sprzed "
            "aktualizacji: <b>%LOCALAPPDATA%\\PepeMarketWizard\\backups</b>."),
          box("Pliki EXE nie są podpisane cyfrowo (brak certyfikatu Authenticode) – Windows SmartScreen może pokazać ostrzeżenie. "
              "Uruchamiaj tylko paczkę, której sumę SHA-256 porównałeś z plikiem .sha256 / raportem.", "warn"),
          PageBreak()]
    # 2
    s += [P("2 / Interfejs: menu główne – stół neuronowy (osiem wież), panele i pasek stanu", "h1"),
          P("Menu główne (1.36, Main Menu V2) to <b>stół neuronowy</b>: trzech Pepe w garniturach przy okrągłym stole z ośmioma wieżami. "
            "Małe logo jest w lewym górnym rogu, nawigacja wszystkich ośmiu modułów na górze; ekran nie ma paneli informacyjnych ani "
            "przycisków na dole. Najechanie na wieżę pokazuje jej opis, kliknięcie wieży albo pozycji na górnym pasku (ten sam cel), Enter "
            "lub dotknięcie listy na małym ekranie otwiera panel (Esc anuluje przejście). Menu nie pobiera danych MT5 i nie pokazuje statystyk. "
            "Scena działa w trybie <b>2.5D</b> (ścieżki neuronowe z impulsami, pierścienie, portal na grafice – nie modele 3D); jakość "
            "animacji: ✧ (Cinematic / Balanced / Performance), Ⅱ wstrzymuje, Studio – w górnym pasku."),
          table([["Wieża", "Panel"],
                 ["PEPE$WTC (dawniej WTC PEPE)", "PEPE$WTC – Neural Market Command Center (multi-chart, Kronos, strefy, Volume Profile)"],
                 ["PEPE$SIGNAL (dawniej BRAIN SIGNAL)", "PEPE$SIGNAL – Signal Intelligence Center (sygnały, warunki, oceny AI)"],
                 ["PEPE$BANK (dawniej AI AGENT)", "Lightning Tower – pełne informacje i historia sygnałów"],
                 ["PEPE$ROI (dawniej LEADERBOARD)", "Profits – rozliczone pozycje i wynik rachunku"],
                 ["STRATEGIES", "Strategy Lab – silnik, ustawienia, biblioteka, porównanie"],
                 ["MARKET NEWS", "Kontekst rynku – wiadomości i kalendarz makro"],
                 ["TRAINING LAB", "Centrum treningu – eksport, walidacja, trening, aktywacja"],
                 ["SETTINGS", "Ustawienia"]], [55, 115]),
          *shot(shots, "ui_neural_city/04_menu_1920.png", "Menu główne – stół neuronowy z ośmioma wieżami.", width_mm=160),
          P("Menu boczne obszarów (bez zmian) – kliknięcie obszaru otwiera jego pierwszą zakładkę; pozostałe są na pasku zakładek."),
          table([["Obszar", "Zawartość"],
                 ["Menu główne", "stół neuronowy – osiem wież (logo w lewym górnym rogu również tu prowadzi)"],
                 ["Precision", "Pulpit, Wykresy MTF, Strefy rynkowe, Scalping MTF, Kontekst rynku, Indykatory, Analiza sygnału, Neural Cyberpunk"],
                 ["Dyscypline", "Scenariusze, Setup silnika S01–S12, SCALPING / HEDGING, Analiza AI, Formacje, Lightning Tower, Strategy Lab"],
                 ["Profits", "Pozycje i ryzyko, Dziennik i wyniki, widok Profits"],
                 ["Modele i trening", "Modele, Centrum treningu, Neural System, Structure Intelligence, Testy, Badania i walidacja, Wind Portal"],
                 ["Ustawienia i diagnostyka", "Ustawienia (z mapą ekranów), Dane i źródła, Diagnostyka, Control Tower"]], [45, 125]),
          box("Control Tower zapisuje ustawienia w konfiguracji bota (progi, filtry, limity ryzyka, szablon i przełączniki Telegram, "
              "presety strategii) – obowiązują od następnej decyzji. Nieprawidłową wartość bot odrzuca i panel to pokazuje. "
              "STOP nowych wejść oraz TEST / DEPLOY strategii wymagają potwierdzenia; tryb wykonania zmienia się tylko w oknie "
              "trybów z potwierdzeniem rachunku.", "warn"),
          P("Pasek stanu (każdy ekran)", "h2"),
          P("U góry każdego ekranu (zwykłego, wież i terminala): instrument i symbol brokera, MT5, jakość i <b>czas ostatnich danych</b>, "
            "rodzaj danych <b>DEMO / LIVE / SYNTETYCZNE</b>, tryb wykonania i STOP."),
          *shot(shots, "ui_interface_129/01_owner_appshell_1920.png", "Pasek stanu i menu obszarów.", crop=(0, 0, 1, 0.42)),
          P("Gdzie są dawne zakładki? <b>Ustawienia i diagnostyka → Ustawienia → Mapa ekranów</b>. Dotychczasowe linki "
            "(np. #/wykresy, #/ai, #/warunki/…) działają bez zmian; dawny link #/licencje otwiera Ustawienia."),
          PageBreak()]
    # 3
    s += [P("3 / Wykresy i strefy", "h1"), P("Wyznacz strefy w głównym obszarze wykresów", "h2"),
          steps(["Otwórz <b>Precision → Wykresy MTF</b> (albo Analiza AI). Nad wykresami jest pasek <b>Strefy XAUUSD</b> / BTC.",
                 "Wybierz zakres: <b>M1 + M5 + M15 (wszystkie trzy)</b> – domyślnie, albo pojedynczo M1, M5, M15, M30, albo wszystkie cztery.",
                 "Kliknij <b>Wyznacz strefy</b>. Widać postęp, czas ostatniego udanego przeliczenia i stan źródła każdego interwału "
                 "(połączone / dane nieaktualne / brak danych / błąd). Wielokrotne kliknięcie nie uruchamia kilku zadań.",
                 "<b>LIVE</b> przelicza strefy po zamknięciu każdej świecy wybranych interwałów; <b>Zatrzymaj</b> kończy."]),
          *shot(shots, "ui_chart_prefs/01_bot_charts_zones.png", "Pasek „Wyznacz strefy” nad wykresami.", crop=(0.13, 0.31, 1, 0.48)),
          P("Strefy rysują się wyłącznie na wykresie tego samego instrumentu, symbolu brokera i interwału. Strefa nieaktualna jest szara "
            "z dopiskiem „nieakt.”. Analiza stref nie otwiera pozycji i nie zmienia trybu ani ustawień handlu."),
          P("Ustawienia wykresu i warstwy", "h2"),
          bullets(["Przycisk <b>⚙</b> na pasku wykresu: kolory świec, knotów, tła, siatki i tekstu; rozmiar tekstu; siatka; wolumen; strefa "
                   "czasu; kolor i krycie każdego typu strefy; etykiety; <b>szablony</b> i <b>Przywróć domyślne</b>.",
                   "Ustawienia są zapisane dla danego wykresu (instrument + interwał) i wracają po ponownym uruchomieniu.",
                   "<b>Warstwy</b>: FVG, OB, popyt/podaż, wsparcie/opór, płynność (hipoteza), etykiety.",
                   "Przybliżenie, przesunięcie i automatyczna skala ceny (przyciski +, −, Dopasuj, A) są zapamiętywane osobno dla wykresu."]),
          *shot(shots, "ui_chart_prefs/03_settings_dialog.png", "Okno „Ustawienia wykresu”.", width_mm=120, crop=(0.22, 0.13, 0.78, 0.87)),
          box("EQH/EQL to równe szczyty i dołki wyznaczone z OHLC – <b>hipoteza</b> płynności, nie zmierzona płynność ani zlecenia "
              "oczekujące. Wynik jakości strefy 0–100 nie jest prawdopodobieństwem.", "warn"),
          PageBreak()]
    # 4
    s += [P("4 / Eksport danych i trening modeli", "h1"), P("Centrum treningu (Modele i trening → Centrum treningu)", "h2"),
          steps(["Połącz MT5, sprawdź symbol i dostępność historii u brokera.",
                 "Wybierz XAUUSD albo BTC – instrumenty trenuj i oceniaj osobno.",
                 "<b>Eksportuj dane</b> (przyrostowo). Sprawdź okres, interwały, liczbę świec, luki i raport jakości.",
                 "<b>Przygotuj dataset</b>, <b>Trenuj</b> albo <b>Uruchom cały proces</b>. Postęp, log i anulowanie są w panelu.",
                 "Porównaj wersje z modelem bazowym: walidacja czasowa (purging, embargo), zbiór końcowy nieużyty do strojenia, koszty.",
                 "<b>Aktywuj</b> tylko po teście zgodności i predykcji; <b>Rollback</b> cofa aktywację."]),
          P("Bez bota: <b>32_CENTRUM_TRENINGU.bat</b>."),
          box("Wytrenowany model nie jest dowodem przewagi. Nowe modele działają w trybie OBSERVATION (nie głosują w strategiach). "
              "Wynik na danych syntetycznych nic nie mówi o rynku.", "warn"),
          P("Kronos AI Forecast (1.31; od 1.37 Kronos-base) – przetrenowany model, bez treningu w bocie", "h2"),
          bullets(["Instalacja: Wykresy bota → <b>Kronos AI Forecast</b> → <b>Zainstaluj model Kronos</b> albo <b>33_KRONOS_INSTALUJ.bat</b> "
                   "(osobne .venv_kronos, PyTorch CPU, oficjalne wagi NeoQuasar w przypiętych rewizjach, sumy sprawdzane ze źródłem).",
                   "<b>Sprawdź instalację</b> naprawdę ładuje model i robi prognozę testową. Po instalacji działa bez internetu.",
                   "Domyślnie SHADOW (obserwacja) na M5 i M15 dla XAUUSD i BTC (BTC po potwierdzeniu symbolu). Prognoza nie składa zleceń.",
                   "Warunek w strategiach (REQUIRED) tylko po pozytywnej walidacji walk-forward na danych rzeczywistych – może jedynie wstrzymać setup.",
                   "Szczegóły, statusy i rozwiązywanie problemów: <b>INSTRUKCJA_KRONOS.md</b>."]),
          PageBreak()]
    # 4b - 1.33
    s += [P("4b / Nowe w 1.33: rodziny modeli, Studio, koordynator decyzji", "h1"),
          P("Rodziny modeli (Centrum treningu → Rodziny modeli 1.33)", "h2"),
          bullets(["15 rodzin: ARIMA, SARIMAX, GARCH, mikrostruktura, para, koszyk, Kalman, breakout, RF, SVM, XGBoost, LSTM, GRU, PPO, NLP. "
                   "Każda ma trzy osie stanu (implementacja / artefakt / użycie), przyciski Trenuj, Aktywuj ostatni, Rollback i wybór OFF / SHADOW / ASSIST.",
                   "Profil treningu: <b>smoke</b> (szybki test), <b>research</b>, <b>full</b>. Trening nie aktywuje modelu.",
                   "LSTM / GRU / PPO potrzebują osobnego środowiska: <b>34_DEEP_INSTALUJ.bat</b>. Plik <b>35_RODZINY_MODELI.bat</b> – lista i trening z wiersza poleceń.",
                   "ASSIST tylko po walidacji APPROVED na Twoich danych REAL – model może wtedy wyłącznie <b>wstrzymać</b> wejście."]),
          *shot(shots, "ui_pmw133/decyzje.png", "Koordynator decyzji (Ustawienia i diagnostyka → Koordynator decyzji).", width_mm=160),
          P("Koordynator decyzji", "h2"),
          bullets(["Jedna logika dla ścieżek S01–S12 i SCALPING/HEDGING. Role modeli: OBSERVE (bez wpływu), ASSIST (tylko wstrzymanie), "
                   "REQUIRED (lista <b>decision.required_models</b> w config.json – domyślnie pusta).",
                   "Wspólna <b>rezerwacja limitów</b> portfela: dwie ścieżki naraz nie przekroczą Twojego limitu pozycji ani dziennej straty.",
                   "Intencje wykonania: podwójne kliknięcie = DUPLICATE; brak odpowiedzi brokera (UNKNOWN) nie jest wysyłany ponownie – rozstrzyga rekonsyliacja."]),
          P("Pepe Data & Training Studio", "h2"),
          bullets(["Osobna aplikacja do eksportu historii i treningu wszystkich modeli: przycisk <b>Studio</b> w górnym pasku lub w menu, "
                   "<b>PepeTrainingStudio.exe</b> albo <b>36_STUDIO.bat</b>. Studio nigdy nie składa zleceń.",
                   "Gdy bot działa, Studio bierze dane z jego magazynu świec; gdy nie działa – eksportuje pełną historię własnym połączeniem tylko do odczytu.",
                   "Gotową paczkę przenosisz do bota przyciskiem „Przenieś” – w bocie jest nieaktywnym kandydatem do ręcznej aktywacji."]),
          box("Szczegóły: docs/INSTRUKCJA_TRENINGU_PL.md, docs/DATA_TRAINING_STUDIO.md, docs/DECISION_LOGIC.md.", "note"),
          PageBreak()]
    # 5
    # 4h - 1.40
    s += [P("4h / Nowe w 1.40: Granite TTM zamiast FinCast, Memory Governor, trening Granite, nowy WTC$PEPE", "h1"),
          bullets(["<b>Granite TTM</b> (IBM, 0,8 M parametrów, Apache-2.0) zastępuje wycofany FinCast: instalacja <b>38_MODELE_CHRONOS2_GRANITE.bat</b> "
                   "albo „Zainstaluj” w sekcji Modele prognoz; ok. 3 MB wag, ok. 0,35 GB RAM. Prognoza punktowa (bez kwantyli i świec), rola OBSERVE.",
                   "Historia prognoz FinCast zostaje (tylko do odczytu); jego ustawienia zapisano w kopii, role nie przeszły na Granite.",
                   "<b>Memory Governor</b> (Modele prognoz → Zasoby): profile LOW_MEMORY_16GB / ECO / BALANCED / MANUAL, pomiar RAM procesów, progi 75/80/85 %, "
                   "jeden ciężki model naraz. Wstrzymana prognoza ma stan STALE z powodem – nigdy wartości zastępczej.",
                   "<b>Dotrenowanie Granite</b> na Twojej historii MT5: osobny proces, test na niewidzianych danych, aktywacja tylko przy wyniku lepszym od bazowego.",
                   "<b>WTC$PEPE</b> ma układ z paczki WTC 2.1 na danych bota; menu Galaxy i panel działają płynniej (docs/WYDAJNOSC_UI_1_40_PL.md).",
                   "Walidacja na złocie (Q4 2025): żaden model (Granite, Chronos-2, Kronos) nie pokonał prognozy „ostatnia cena” – modele są informacją, "
                   "nie sygnałem."]),
          PageBreak()]
    # 4g - 1.39
    s += [P("4g / Nowe w 1.39: LIVE od startu, GARCH, intro, menu Galaxy, WTC PEPE 2.1", "h1"),
          box("<b>Bot startuje w AUTO LIVE</b> (na Twoje polecenie) i przy pierwszej decyzji wiąże się z zalogowanym rachunkiem REAL. "
              "Zdjęte bramki walidacji (VALIDATED, skalibrowany model, znana prowizja) są teraz ostrzeżeniami; STOP, limity ryzyka, spread, "
              "deduplikacja, uzgadnianie z MT5 i wymóg rachunku REAL działają dalej. Wyłączenie: STOP albo data\\config.json → "
              "execution.start_mode = \"SIGNALS\", execution.live_autobind = false.", "block"),
          bullets(["Do handlu nadal potrzebne: ścieżka główna instrumentu (ACTIVE / SH) i limity ryzyka – bez nich bot pokazuje powód i nie wchodzi.",
                   "<b>GARCH</b>: rodzina VOL_GARCH może liczyć sigmę strategii PMW_HG09 (volatility_method = VOL_GARCH). Bez aktywnego modelu "
                   "HG09 zwraca NO_DATA (GARCH_NOT_READY) – bez cichego zastępstwa.",
                   "<b>Intro</b> „$PEPEMARKET WIZARD” (ok. 8,5 s; POMIŃ INTRO / Esc, Ctrl+Alt+B – ponownie) i <b>menu Galaxy</b> (#/menu): 7 planet, "
                   "pełna sieć 21/21, edytor „Projektuj”, planety otwierają prawdziwe ekrany. Neural City: #/neural-city.",
                   "<b>WTC PEPE → CUSTOMIZE CHART</b> (Chart Lab 2.1) i Session Volume Profile (POC / VA, London / New York / Asia, impuls 3/5/8/12) "
                   "na prawdziwych świecach MT5.",
                   "Instalacja bota i modeli oraz trening krok po kroku: <b>Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf</b>."]),
          *shot(shots, "ui_galaxy/galaxy_1920x1080.png", "Menu Galaxy V2.", width_mm=150),
          PageBreak()]
    # 4f - 1.38
    s += [P("4f / Nowe w 1.38: pakiet 20 strategii XAUUSD (SCALPING + HEDGING)", "h1"),
          bullets(["Strona <b>Strategie</b> → panel <b>Pakiet 20 strategii</b>: PMW_SC01–SC10 (scalp: TP1 ≥ 25 pips, RR planu netto ≥ 2) i "
                   "PMW_HG01–HG10 (hedge: TP1 ≥ 40 pips, RR koszyka netto ≥ 3). Stan każdego wariantu na każdym TF z powodem, plan Entry/SL/TP1/TP2, "
                   "warunek hedge i postęp, historia sygnałów.",
                   "Wykresy: warstwa <b>Pakiet 20</b> – strzałka sygnału na świecy, na której informacja była dostępna, linie wybranego planu "
                   "i aktywnych pozycji (nie 20 kompletów naraz), filtry Scalp/Hedge, strategia, historia.",
                   "Wykonanie tylko istniejącą ścieżką i w bieżącym trybie: SIGNALS – zero zleceń, PAPER – symulacja, AUTO_LIVE – tylko wariant z walidacją "
                   "VALIDATED na Twoich danych. Bot nie zmienia trybu. Hedge tylko na rachunku HEDGING, jedna aktywacja, maks. 50 % bazy.",
                   "Walidacja na Twojej historii MT5: <b>39_PAKIET_20_WALIDACJA.bat</b>. Bez niej wszystkie warianty mają status NOT_VALIDATED."]),
          *shot(shots, "ui_kronos/sh_pack_panel.png", "Panel Pakiet 20 strategii (symulator MT5, świeży start – oceny po pierwszej zamkniętej M1).", width_mm=165, crop=(0, 0, 1, 0.68)),
          box("Szczegóły: docs/strategies20/RUNBOOK_PL.md, STRATEGY_SPECIFICATIONS.md, RISK_AND_UNITS.md. Nazwa strategii i linia 1:3 na wykresie nie są "
              "dowodem przewagi.", "warn"),
          PageBreak()]
    # 4e - 1.37
    s += [P("4e / Nowe w 1.37: Kronos-base, Chronos-2 i FinCast (FinCast wycofany w 1.40)", "h1"),
          bullets(["<b>Kronos-base</b> (102,3M) zastępuje Kronos-small – to największy publiczny Kronos (Kronos-large nie jest udostępniony). "
                   "Po aktualizacji uruchom <b>33_KRONOS_INSTALUJ.bat</b>; do tego czasu Kronos pokazuje „brak zweryfikowanych wag”. "
                   "Bot nigdy nie przechodzi po cichu na mniejszy model.",
                   "<b>Chronos-2</b> (Amazon, 120M) i <b>FinCast</b> (ok. 1B): instalacja <b>38_MODELE_CHRONOS2_FINCAST.bat</b> albo przyciski "
                   "„Zainstaluj” w sekcji <b>Modele prognoz</b> (Wykresy bota). FinCast potrzebuje ok. 8 GB wolnej pamięci przy ładowaniu.",
                   "Sekcja <b>Modele prognoz</b>: status, czasy, linie prognoz z przełącznikiem dla każdego modelu (nieaktualna = kropkowana), "
                   "porównanie na tej samej świecy, walidacja walk-forward i rola w strategiach.",
                   "Domyślnie <b>obserwacja</b>. ASSIST / REQUIRED tylko po pozytywnej walidacji na danych rzeczywistych i z potwierdzeniem – model może "
                   "wyłącznie wstrzymać setup. Prognoza to cena, nie prawdopodobieństwo; zgodność modeli nie jest niezależnym potwierdzeniem."]),
          *shot(shots, "ui_foundation/live.png", "Modele prognoz – trzy modele na symulatorze MT5 (dane syntetyczne).", width_mm=165),
          box("Szczegóły, zasoby, testy i ograniczenia: docs/MODELE_KRONOS_CHRONOS2_FINCAST_1_37_PL.md.", "note"),
          PageBreak()]
    # 4d - 1.36
    s += [P("4d / Nowe w 1.36: wieże PEPE$WTC i PEPE$SIGNAL", "h1"),
          P("PEPE$WTC – Neural Market Command Center", "h2"),
          bullets(["Duży wykres główny aktywnego instrumentu z wyborem interwału; <b>Multi-Chart Workspace</b>: „＋ Dodaj wykres”, × usuwa, "
                   "każdy wykres ma własny interwał, kliknięcie nazwy przenosi go na wykres główny; „Reset widoku” przywraca układ.",
                   "<b>Indicator Manager</b> pokazuje tylko warstwy, które bot naprawdę liczy (EMA, VWAP, RSI, MACD, ATR, BOS/CHoCH, OB/FVG, sesje, "
                   "strefy, S/R + profil sesji, SVP, walls, SAR, IQ/PAL, poziomy AI). Bollinger Bands = N/A (brak w bocie).",
                   "<b>Kronos M1 / M5</b>: OFF / AUTO / MANUAL („Przelicz” na żądanie), prognoza jako linia na wykresie; status z backendu "
                   "(np. NOT_INSTALLED) – bez wymyślonego confidence.",
                   "<b>AI Live Zones</b>: AUTO = przeliczenie stref po zamknięciu każdej świecy M1–M30, MANUAL = „Wyznacz teraz”; filtr typów.",
                   "<b>Volume Profile Auto Zones</b>: POC, VAH/VAL, HVN, LVN z silnika PMW-SVP-1 dla okna wykresu (100/200/500 świec) – "
                   "kolumna profilu przy wykresie i typowane strefy na wykresie. Poziom VP to informacja, nie sygnał.",
                   "<b>Smart Trade Setup Builder</b> liczy R:R = |TP − Entry| / |Entry − SL| – nie ma przycisku zlecenia."]),
          *shot(shots, "ui_towers/01_wtc_1672.png", "PEPE$WTC (symulator MT5).", width_mm=165, crop=(0, 0, 1, 0.55)),
          P("PEPE$SIGNAL – Signal Intelligence Center", "h2"),
          bullets(["Strumień sygnałów wszystkich strategii bota (S01–S12, skaner rynków, SCALPING / HEDGING) z filtrami: strategia, symbol, "
                   "interwał, kierunek, status, czas, siła. Ⅱ zamraża listę.",
                   "Wybór sygnału (z listy albo tabeli) aktualizuje wykres (Entry / SL / TP, przewinięty do chwili sygnału), podsumowanie, "
                   "warunki <b>ENTRY / TRIGGER / INVALIDATION</b> z checklisty strategii, narrację, oceny modeli, metryki i zgodność MTF.",
                   "Sygnał oczekujący jest zawsze <b>WAIT</b>. Siła sygnału to heurystyka 0–100, wynik modelu nie jest prawdopodobieństwem, "
                   "o ile model nie jest skalibrowany. Dla starych sygnałów oceny modeli są oznaczone jako bieżące.",
                   "Zakładki: LIVE SIGNALS, ALL STRATEGIES, AI EVALUATION, SIGNAL HISTORY, PERFORMANCE (wyniki w R), SETUP BUILDER (widok setupu)."]),
          *shot(shots, "ui_towers/02_signal_1672.png", "PEPE$SIGNAL (symulator MT5).", width_mm=165, crop=(0, 0, 1, 0.6)),
          box("Obie wieże tylko analizują – nie otwierają ani nie zamykają pozycji. Dawne panele: Trading Intelligence i Wind Portal "
              "są dostępne w menu bocznym wież.", "note"),
          PageBreak()]
    # 4c - 1.35
    s += [P("4c / Nowe w 1.35: PMW Quant Core (SHADOW)", "h1"),
          bullets(["Wspólny silnik: snapshot zamkniętych świec z kontrolą jakości → wyniki wszystkich dostępnych modeli w jednym kontrakcie → "
                   "kontrola (aliasy, czas z przyszłości, przeterminowanie, błędy kontraktu) → ocena setupu przez <b>Quant MetaModel</b>.",
                   "Działa sam w tle, także przy zamkniętym panelu. Domyślnie <b>SHADOW</b> – liczy i zapisuje, bez wpływu na decyzje.",
                   "Sekcje „PMW Quant Core”: <b>Ustawienia i diagnostyka → Koordynator decyzji</b> (stan danych, modele gotowe / wykluczone z powodem, "
                   "czasy, oceny setupów) oraz <b>Modele i trening → Centrum treningu</b> (dowody w ledgerze, trening, aktywacja, rollback).",
                   "Meta-model uczy się wyłącznie na rzeczywistych kandydatach zapisanych w chwili decyzji i rozstrzygniętych później. "
                   "Bez wystarczającej liczby wyników pokazuje <b>brak wytrenowanego modelu dla tego zdarzenia</b> – nigdy 0 % ani 50 %.",
                   "<b>ASSIST</b> tylko po walidacji (VALIDATED_SHADOW) i Twoim potwierdzeniu – może wyłącznie wstrzymać kandydata; nie składa zleceń "
                   "i nie zmienia limitów. Menu z wiersza poleceń: <b>37_QUANT_CORE.bat</b>; szczegóły: <b>docs/quant/RUNBOOK_PL.md</b>."]),
          *shot(shots, "ui_quant/trening_quant.png", "PMW Quant Core w Centrum treningu.", width_mm=160),
          box("Wynik na danych syntetycznych (tryb demo) sprawdza działanie programu, nie skuteczność. Wycofanie: tryb SHADOW / OFF albo "
              "docs/quant/ROLLBACK.md.", "warn"),
          PageBreak()]
    s += [P("5 / Paczki do przekazania", "h1"),
          P("Od 1.30 jest jedna wersja programu – bez licencji, bez podziału na OWNER i CLIENT. Inna osoba dostaje tę samą paczkę co Ty:"),
          table([["Paczka", "Dla kogo"],
                 ["PepeMarketWizard_DESKTOP_" + TAG + ".zip", "aplikacja Windows: EXE + wbudowany Python + program (główna paczka)"],
                 ["PepeMarketWizard_" + TAG + ".zip", "sam folder programu (uruchamianie plikami .bat, własny Python)"]], [70, 100]),
          steps(["Przekaż paczkę razem z plikiem <b>.sha256</b> i <b>Instrukcją użytkownika</b>.",
                 "Paczka nie zawiera Twoich danych, kluczy API, haseł MT5, bazy ani dziennika – każdy użytkownik konfiguruje swój MT5 sam.",
                 "Sprawdzenie paczki: <b>python tools\\verify_release.py &lt;paczka&gt;</b> (ścieżki, sumy, brak plików zabronionych)."]),
          box("Program nie blokuje nikomu dostępu – kto ma paczkę, może jej używać. Jeśli chcesz kiedyś wrócić do licencji, system z "
              "wersji 1.27–1.29 jest zachowany w historii repozytorium (git)."),
          PageBreak()]
    # 6
    s += [P("6 / Aktualizacja z 1.32, kopia i powrót", "h1"),
          P("Aktualizację i powrót sprawdzono na kopiach danych (<b>tools/migration_check.py --old-ref 5e5d82a</b>): 1.33 uruchamia się na danych "
            "1.32, zachowuje konfigurację, migracje bazy i strefy; 1.32 działa na kopii sprzed aktualizacji oraz na danych po 1.33 z przywróconą "
            "kopią konfiguracji."),
          P("Aktualizacja", "h2"),
          steps(["Zatrzymaj aplikację (STOP nowych wejść → zamknij). Zapisz kopię folderu danych.",
                 "Rozpakuj 1.33 do nowego folderu i uruchom; aplikacja Windows sama robi kopię danych przed migracją.",
                 "Pierwszy start: migracja bazy 0025 (nowe tabele) i konfiguracja v13 – oryginał 1.32 zostaje jako <b>data\\config.v12.bak.json</b>."]),
          P("Powrót do 1.32", "h2"),
          steps(["Zatrzymaj 1.33. W folderze <b>data</b> zmień nazwę config.json na config.v13.json i skopiuj <b>config.v12.bak.json</b> jako config.json "
                 "(1.32 odrzuca nowe sekcje konfiguracji). Albo przywróć cały folder danych z kopii (backups).",
                 "Uruchom program 1.32 z jego folderu. Baza może zostać – 1.32 ignoruje tabele dodane w 1.33.",
                 "Pełna instrukcja: <b>docs/AKTUALIZACJA_1_33_PL.md</b>."]),
          P("7 / Typowe problemy", "h1"),
          table([["Objaw", "Co zrobić"],
                 ["MT5 rozłączony / dane nieaktualne", "uruchom terminal, sprawdź logowanie, symbol, historię i 02_DIAGNOSTYKA.bat"],
                 ["Brak stref", "wybierz zakres, sprawdź stan źródła i czas danych, kliknij Wyznacz strefy, odczytaj błąd"],
                 ["Brak wejść", "sprawdź tryb (SIGNALS nie składa zleceń), STOP, ścieżkę główną, limity ryzyka i jakość danych"],
                 ["Trening pominięty", "sprawdź log zadania, zakres historii, luki, RAM i wymagania modelu"]], [60, 110]),
          box("Nie dołączaj do zgłoszeń haseł, tokenów, kluczy prywatnych ani plików bazy. "
              "Wyniki testów: release/RAPORT_KONCOWY.md (PASS / FAIL / BLOCKED).", "warn")]
    return s


# ---------------------------------------------------------------------------------------------------------------- user
def client(shots: Path | None) -> list:
    s: list = [Spacer(1, 18 * mm), P("Instrukcja<br/>użytkownika", "title"),
               P("Instalacja, połączenie z MT5 i korzystanie z PepeMarketWizard 1.30.", "lead"),
               box("<b>Stan:</b> wersja 1.30 działa <b>bez klucza licencji</b> – nie ma okna aktywacji. Ekrany opisane tutaj sprawdzono "
                   "na symulatorze terminala; jeśli Twoja paczka wygląda inaczej, zapytaj osobę, od której ją dostałeś, o aktualną wersję."),
               P("Co przygotować", "h2"),
               bullets(["Komputer z Windows 10/11 i połączeniem z Internetem (pierwsze uruchomienie pobiera składniki).",
                        "Paczkę <b>PepeMarketWizard_DESKTOP_" + TAG + ".zip</b> i jej plik <b>.sha256</b>.",
                        "Terminal MetaTrader 5 z dostępem do własnego rachunku."]),
               box("Nie wysyłaj nikomu hasła do MT5 ani kodów bezpieczeństwa.", "warn"),
               box("<b>Od wersji 1.39 bot startuje w trybie AUTO LIVE</b> i po pierwszej decyzji handluje na zalogowanym rachunku REAL "
                   "(prawdziwe pieniądze). Przycisk <b>STOP</b> natychmiast zatrzymuje nowe wejścia. Jeśli chcesz tylko oglądać sygnały, "
                   "poproś administratora o tryb SIGNALS (data\\config.json → execution.start_mode). Po starcie zobaczysz intro "
                   "„$PEPEMARKET WIZARD” (POMIŃ INTRO / Esc) i menu <b>Galaxy</b> z siedmioma planetami – kliknięcie planety otwiera jej ekran.", "block"),
               PageBreak()]
    s += [P("1 / Instalacja", "h1"), P("Pierwsze uruchomienie", "h2"),
          steps(["Rozpakuj całą paczkę do nowego folderu. Nie uruchamiaj programu z wnętrza ZIP-a.",
                 "Uruchom <b>PepeMarketWizardDesktop.exe</b> (tytuł okna: <b>PepeMarketWizard " + VERSION + "</b>). Pierwszy start pobiera "
                 "wymagane składniki – może potrwać kilka minut. Postęp widać w małym oknie <b>JOIN THE CULT</b>.",
                 "Gdy launcher pokaże <b>SYSTEM READY</b>, kliknij <b>JOIN THE CULT</b> (na dole ekranu). Okno się powiększy i po krótkim intro "
                 "(<b>Pomiń intro</b> / Esc) pokaże menu główne – <b>stół neuronowy</b> z ośmioma wieżami. Przy pierwszym starcie kreator prosi o "
                 "limity ryzyka i koszty."]),
          *shot(shots, "ui_neural_city/01_launcher_1920.png", "Launcher JOIN THE CULT.", width_mm=140),
          *shot(shots, "ui_neural_city/04_menu_1920.png", "Menu główne – osiem wież.", width_mm=150),
          box("Pliki EXE nie są podpisane cyfrowo – Windows SmartScreen może pokazać ostrzeżenie. Porównaj sumę SHA-256 paczki "
              "z plikiem .sha256."),
          PageBreak()]
    s += [P("2 / Połączenie z MT5", "h1"),
          steps(["Uruchom MetaTrader 5 i zaloguj się na właściwy rachunek. Dane logowania wpisuj tylko w polach do tego przeznaczonych.",
                 "W Market Watch sprawdź dokładną nazwę instrumentu (np. <b>XAUUSD-</b>; zależy od brokera).",
                 "W <b>Ustawienia i diagnostyka → Ustawienia</b> sprawdź symbol i mapowanie BTC.",
                 "Ustaw znane koszty (prowizja) i limity ryzyka zgodnie z rachunkiem."]),
          P("Jak czytać pasek stanu", "h2"),
          table([["Element", "Znaczenie"],
                 ["XAUUSD / BTC i symbol", "instrument i symbol brokera, na którym pracuje bot"],
                 ["MT5 połączony / rozłączony", "stan terminala według programu"],
                 ["Ostatnie dane", "czas ostatniego notowania z MT5 – jeśli stary, wykres nie pokazuje bieżącego rynku"],
                 ["DEMO / LIVE / SYNTETYCZNE", "rodzaj rachunku potwierdzony przez terminal; SYNTETYCZNE = symulator, nie Twój rachunek"],
                 ["Tryb, STOP", "SIGNALS / PAPER / AUTO DEMO / AUTO LIVE; STOP zatrzymuje nowe wejścia"]], [55, 115]),
          PageBreak()]
    s += [P("3 / Korzystanie z panelu", "h1"),
          P("Menu główne ma osiem wież: <b>PEPE$WTC</b> (wykresy, Kronos, strefy i Volume Profile), <b>PEPE$SIGNAL</b> (sygnały i oceny AI), "
            "<b>PEPE$BANK</b> (historia sygnałów), <b>PEPE$ROI</b> (wyniki rachunku), <b>STRATEGIES</b> (strategie), "
            "<b>MARKET NEWS</b> (wiadomości i kalendarz makro), <b>TRAINING LAB</b> (trening modeli) i <b>SETTINGS</b> (ustawienia). Najedź na wieżę – zobaczysz opis, kliknij wieżę albo przycisk "
            "na górnym pasku – otworzysz panel (Esc anuluje). Menu boczne obszarów: <b>Precision</b>, "
            "<b>Dyscypline</b>, <b>Profits</b>, <b>Modele i trening</b>, <b>Ustawienia i diagnostyka</b>. Logo prowadzi do menu głównego."),
          box("Znaczniki przy wartościach mówią, skąd pochodzą: <b>DEMO · symulator</b> (dane syntetyczne), <b>DEMO</b> (rachunek "
              "demonstracyjny), <b>REAL</b>, <b>brak danych</b>, <b>nieaktualne</b>, <b>błąd synchronizacji</b>. Wynik, win rate czy "
              "ROI z symulatora nie są wynikami Twojego rachunku."),
          P("Strefy na wykresie", "h2"),
          steps(["Otwórz <b>Precision → Wykresy MTF</b>.",
                 "Na pasku <b>Strefy</b> wybierz M1 + M5 + M15 (domyślnie) albo pojedynczy interwał; M30 też jest dostępny.",
                 "Kliknij <b>Wyznacz strefy</b>. <b>LIVE</b> przelicza strefy po zamknięciu kolejnej świecy.",
                 "Szczegóły stref (checklista, historia): <b>Precision → Strefy rynkowe</b>."]),
          P("Własne ustawienia wykresu", "h2"),
          bullets(["<b>⚙</b> na pasku wykresu: kolory, siatka, rozmiar tekstu, wolumen, strefa czasu, kolor i krycie stref, szablony, "
                   "„Przywróć domyślne”. Ustawienia każdego wykresu są pamiętane po ponownym uruchomieniu.",
                   "<b>Warstwy</b>: pokaż / ukryj FVG, OB, popyt/podaż, wsparcie/opór, płynność (hipoteza) i etykiety."]),
          box("Strefy to informacja analityczna – przycisk nie otwiera pozycji i nie zmienia ustawień handlu. Płynność EQH/EQL to "
              "hipoteza wyznaczona z OHLC, nie zmierzone zlecenia.", "warn"),
          PageBreak()]
    s += [P("3b / Nowe w 1.33: DXY, SVP, plany Scalp/Hedge, Studio", "h1"),
          bullets(["<b>Precision → XAUUSD × DXY i wskaźniki PMW</b>: korelacja i beta złota do DXY na zwrotach H1 (okna 24/72/240 h), AVWAP sesji, "
                   "spread względem sesji, semiwariancja, arkusz zleceń MT5. Symbol DXY brokera ustawisz w Ustawieniach.",
                   "<b>Precision → SVP</b>: profil wolumenu sesji albo zakresu dat (POC, VAH/VAL), zamrożenie, LIVE, strefy ręczne, z algorytmu i propozycje AI.",
                   "Na każdym wykresie przyciski <b>Scalp Plan</b>, <b>Hedge Plan</b>, <b>AVWAP</b> i <b>SVP</b> dorysowują poziomy planu SCALPING / HEDGING "
                   "(wejście, SL, TP, cena wykonania, SL po BE, aktywacja hedge), linię AVWAP i granice stref. Przełączanie warstw nie zmienia zleceń.",
                   "Przycisk <b>Studio</b> (górny pasek / menu) otwiera Pepe Data & Training Studio – osobny program do danych i treningu modeli."]),
          *shot(shots, "ui_pmw133/dxy.png", "XAUUSD × DXY i wskaźniki PMW (symulator: DXY wyłączony, bo nie ustawiono symbolu).", width_mm=150),
          *shot(shots, "ui_pmw133/wykresy_layers.png", "Przyciski warstw 1.33 na wykresach.", width_mm=150, crop=(0, 0, 1, 0.55)),
          box("Wskaźniki, profile i strefy to informacja analityczna; pasma σ nie są przedziałami prawdopodobieństwa.", "warn"),
          PageBreak()]
    s += [P("4 / Tryby i pomoc", "h1"), P("Tryb pracy", "h2"),
          P("<b>SIGNALS</b> – analiza bez nowych zleceń. <b>PAPER</b> – symulacja. <b>AUTO DEMO</b> i <b>AUTO LIVE</b> – zlecenia na "
            "odpowiednim rachunku, z potwierdzeniem. Zacznij od SIGNALS lub PAPER i rachunku DEMO. <b>STOP</b> zatrzymuje nowe wejścia; "
            "otwarte pozycje są dalej prowadzone (SL/TP po stronie brokera)."),
          P("Rozwiązywanie problemów", "h2"),
          table([["Objaw", "Co zrobić"],
                 ["Program się nie uruchamia", "sprawdź Internet przy pierwszym starcie, uruchom 02_DIAGNOSTYKA.bat i zachowaj wynik"],
                 ["Brak wykresu", "uruchom MT5, sprawdź symbol, historię i stan połączenia"],
                 ["Brak stref", "wybierz interwały, sprawdź czas danych i stan źródła, kliknij Wyznacz strefy"],
                 ["Brak wejść", "sprawdź tryb (SIGNALS nie składa zleceń), STOP, limity ryzyka i jakość danych"]], [55, 115]),
          box("Wyniki historyczne i wyniki modeli nie gwarantują przyszłych wyników. Nie przekazuj nikomu haseł ani pełnych danych "
              "dostępowych.", "warn")]
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "data" / "logs"), help="folder ze zrzutami testów UI (opcjonalnie)")
    ap.add_argument("--out", default=str(ROOT / "release"))
    a = ap.parse_args()
    fonts()
    styles()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = Path(a.shots) if Path(a.shots).is_dir() else None
    build(out / "Instrukcja_Administrator_PepeMarketWizard.pdf", "ADMINISTRATOR", admin(shots), "PepeMarketWizard – instrukcja administratora")
    build(out / "Instrukcja_Klient_PepeMarketWizard.pdf", "UŻYTKOWNIK", client(shots), "PepeMarketWizard – instrukcja użytkownika")
    for n in ("Instrukcja_Administrator_PepeMarketWizard.pdf", "Instrukcja_Klient_PepeMarketWizard.pdf"):
        print(f"{n}: {(out / n).stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
